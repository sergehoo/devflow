"""
Réunions & enregistrements — API JSON du frontend React (chantier « meetings »).

Aucune règle métier n'est réécrite :

* **lecture** : on exécute les vues Django existantes (``ProjectMeetingListView``,
  ``ProjectMeetingDetailView``, ``MeetingDashboardView.build_context``,
  ``RecordingSummaryView.build_context``…) — mêmes querysets, même scoping
  workspace, mêmes droits — et on sérialise leur contexte ;
* **écriture** : pont ``run_action_view`` vers les vues d'action existantes
  (RSVP, présences, ordre du jour, actions, revues, mapping des voix,
  extractions IA…) ; création / modification / suppression via les ponts
  génériques ``forms/meeting|meeting-series`` et ``resources/…/delete`` ;
* **IA payante** (analyse, résumé, synthèse d'enregistrement) :
  ``AIActionRateThrottle`` ;
* **e-mails** : uniquement via Celery (pas d'envoi synchrone dans la requête).

L'enregistreur React (et l'ancien widget) postent sur
``/api/v1/meetings/<id>/recordings/upload/`` : ``MeetingRecordingUploadView``
recouvre la route historique (l'include ``api/v1/`` est résolu avant) et
exécute la même vue ``api_upload_recording``, avec ``AIActionRateThrottle``
(l'upload déclenche transcription + synthèse IA payantes).
"""

from __future__ import annotations

import logging

from django.urls import NoReverseMatch, reverse
from django.utils.module_loading import import_string
from rest_framework import permissions, status
from rest_framework.exceptions import NotFound
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from project import models as dm
from project.api.form_bridge import describe_form, run_action_view
from project.api.resources import _run
from project.api.throttles import AIActionRateThrottle

logger = logging.getLogger(__name__)

FINAL_RECORDING_STATUSES = {"completed", "failed", "cancelled"}
SEGMENTS_LIMIT = 2000


# ─────────────────────────────────────────────────────────────────────
# Helpers de sérialisation
# ─────────────────────────────────────────────────────────────────────
def _iso(value):
    return value.isoformat() if value else None


def _name(user) -> str:
    return (user.get_full_name() or user.get_username()) if user else ""


def _user(user):
    return {"id": user.pk, "name": _name(user), "email": user.email or ""} if user else None


def _choices(pairs) -> list[dict]:
    return [{"value": str(v), "label": str(label)} for v, label in pairs]


def _html(text) -> str:
    """Même rendu que le filtre ``safe_html`` des templates (bleach, XSS-safe)."""
    from project.templatetags.devflow_extras import safe_html

    return str(safe_html(text or ""))


def _url(name: str, **kwargs) -> str | None:
    try:
        return reverse(name, kwargs=kwargs)
    except NoReverseMatch:
        return None


def _legacy(view_class, request, **kwargs):
    """Instancie une vue Django historique sur la requête courante (sans la rendre)."""
    django_request = request._request
    django_request.user = request.user
    view = view_class()
    view.setup(django_request, **kwargs)
    return view


def _meeting_row(m) -> dict:
    return {
        "id": m.pk,
        "title": m.title,
        "status": m.status,
        "status_label": m.get_status_display(),
        "meeting_type": m.meeting_type,
        "type_label": m.get_meeting_type_display(),
        "scheduled_at": _iso(m.scheduled_at),
        "duration_minutes": m.duration_minutes,
        "duration_label": m.duration_label,
        "project": {"id": m.project_id, "name": m.project.name} if m.project_id else None,
        "organizer": _name(m.organizer) if m.organizer_id else "",
        "location": m.location or "",
        "series_id": m.series_id,
    }


def _recording_status(r) -> dict:
    """Équivalent JSON du fragment htmx ``recording_status_fragment.html``."""
    return {
        "id": r.pk,
        "meeting_id": r.meeting_id,
        "status": r.status,
        "status_label": r.get_status_display(),
        "progress_percent": r.progress_percent,
        "progress_label": r.progress_label,
        "is_terminal": r.is_terminal,
        "is_final": r.status in FINAL_RECORDING_STATUSES,
        "created_at": _iso(r.created_at),
        "started_at": _iso(r.started_at),
        "completed_at": _iso(r.completed_at),
        "duration_seconds": r.duration_seconds,
        "transcription_provider": r.transcription_provider or "",
        "summary_provider": r.summary_provider or "",
        "error_message": r.error_message or "",
        "speakers_count": r.speakers.count(),
        "recorded_by": _name(r.recorded_by) if r.recorded_by_id else "",
        "has_summary": bool(r.summary_markdown),
    }


def _extraction(e) -> dict:
    return {
        "id": e.pk,
        "kind": e.kind,
        "kind_label": e.get_kind_display(),
        "title": e.title,
        "description": e.description or "",
        "assignee_hint": e.assignee_hint or "",
        "due_date_hint": e.due_date_hint or "",
        "priority_hint": e.priority_hint or "",
        "confidence": e.confidence,
        "is_accepted": e.is_accepted,
        "accepted_at": _iso(e.accepted_at),
    }


def _participation(p) -> dict:
    return {
        "user": _user(p.user),
        "rsvp_status": p.rsvp_status,
        "rsvp_label": p.get_rsvp_status_display(),
        "rsvp_note": p.rsvp_note or "",
        "rsvp_at": _iso(p.rsvp_at),
        "attendance_status": p.attendance_status,
        "attendance_label": p.get_attendance_status_display(),
        "self_confirmed": p.self_confirmed,
        "attendance_marked_by": _name(p.attendance_marked_by) if p.attendance_marked_by_id else "",
        "attendance_marked_at": _iso(p.attendance_marked_at),
    }


def _reviews(ctx) -> dict | None:
    """Formset des revues projet (``MeetingReviewsSaveView``) décrit pour React."""
    formset = ctx.get("review_formset")
    if formset is None:
        return None
    management = formset.management_form
    forms = []
    for form in formset.forms:
        fields = describe_form(form)["fields"]
        for f in fields:
            if f["name"] == "project":  # rendu caché dans l'ancien template
                f["type"] = "hidden"
                f.pop("choices", None)
        review = form.instance
        forms.append({
            "id": review.pk,
            "prefix": form.prefix,
            "project": {"id": review.project_id, "name": review.project.name} if review.project_id else None,
            "status_label": review.get_status_snapshot_display(),
            "progress_pct": review.progress_pct,
            "fields": fields,
        })
    return {
        "prefix": formset.prefix,
        "management": {
            f"{formset.prefix}-{name}": management[name].value() for name in management.fields
        },
        "forms": forms,
    }


# ─────────────────────────────────────────────────────────────────────
# Lecture
# ─────────────────────────────────────────────────────────────────────
class MeetingListView(APIView):
    """``GET meetings/`` — ``ProjectMeetingListView`` (tri à venir/passées, ``q``, ``type``, ``status``, ``project``)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from project.views_meeting import ProjectMeetingListView

        view, ctx = _run(ProjectMeetingListView, request, {})
        page = ctx.get("page_obj")
        items = list(ctx.get("object_list") or [])
        current_project = None
        raw_project = request.query_params.get("project", "")
        if raw_project.isdigit():
            current_project = (
                view.filter_by_workspace(dm.Project.objects.filter(pk=raw_project))
                .values("id", "name").first()
            )
        rows = []
        for m in items:
            row = _meeting_row(m)
            row["is_past"] = bool(getattr(m, "is_past", 0))
            row["participants_count"] = m.participants_count
            rows.append(row)
        return Response({
            "results": rows,
            "count": page.paginator.count if page else len(rows),
            "page": page.number if page else 1,
            "num_pages": page.paginator.num_pages if page else 1,
            "type_choices": _choices(ctx.get("meeting_type_choices") or []),
            "status_choices": _choices(ctx.get("status_choices") or []),
            "current_project": current_project,
        })


class MeetingDetailView(APIView):
    """``GET meetings/<pk>/`` — contexte complet de ``ProjectMeetingDetailView``."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        from project.views_meeting import ProjectMeetingDetailView, can_convert_to_task

        _view, ctx = _run(ProjectMeetingDetailView, request, {"pk": pk})
        m = ctx["meeting"]
        participations = ctx.get("participations") or []
        my = ctx.get("my_participation")
        recordings = list(m.recordings.select_related("recorded_by").order_by("-created_at"))
        action_priority = dm.MeetingActionItem._meta.get_field("priority").choices
        data = {
            **_meeting_row(m),
            "projects": [{"id": p.pk, "name": p.name} for p in m.projects.all()],
            "sprint": {"id": m.sprint_id, "name": m.sprint.name} if m.sprint_id else None,
            "series": {"id": m.series_id, "name": m.series.name} if m.series_id else None,
            "organizer_user": _user(m.organizer),
            "meeting_link": m.meeting_link or "",
            "external_participants": m.external_participants or "",
            "participants_count": m.participants_count,
            "attachments_count": m.attachments.count(),
            "agenda_html": _html(m.agenda),
            "notes_html": _html(m.notes),
            "decisions_html": _html(m.decisions),
            "blockers_html": _html(m.blockers),
            "next_steps_html": _html(m.next_steps),
            "ai_summary": m.ai_summary or "",
            "ai_used_provider": m.ai_used_provider or "",
            "ai_extracted_at": _iso(m.ai_extracted_at),
            "created_by": _name(m.created_by) if m.created_by_id else "",
            "created_at": _iso(m.created_at),
            "updated_by": _name(m.updated_by) if m.updated_by_id else "",
            "updated_at": _iso(m.updated_at),
            "agenda_items": [
                {
                    "id": item.pk,
                    "position": item.position,
                    "title": item.title,
                    "description": item.description or "",
                    "description_html": _html(item.description),
                    "notes": item.notes or "",
                    "notes_html": _html(item.notes),
                    "owner": _user(item.owner),
                    "duration_minutes": item.duration_minutes,
                    "status": item.status,
                    "status_label": item.get_status_display(),
                    "started_at": _iso(item.started_at),
                    "completed_at": _iso(item.completed_at),
                }
                for item in ctx.get("agenda_items") or []
            ],
            "agenda_status_choices": _choices(dm.MeetingAgendaItem.Status.choices),
            "action_items": [
                {
                    "id": a.pk,
                    "title": a.title,
                    "description": a.description or "",
                    "owner": _user(a.owner),
                    "due_date": _iso(a.due_date),
                    "status": a.status,
                    "status_label": a.get_status_display(),
                    "priority": a.priority,
                    "priority_label": a.get_priority_display(),
                    "converted_task_id": a.converted_task_id,
                    "converted_at": _iso(a.converted_at),
                }
                for a in m.action_items.all()
            ],
            "action_priority_choices": _choices(action_priority),
            # Même règle que MeetingActionItemConvertToTaskView (RBAC task.create / responsable).
            "can_convert_actions": can_convert_to_task(request.user, m.workspace, m.project),
            "participations": [_participation(p) for p in participations],
            "my_participation": _participation(my) if my else None,
            "participations_stats": ctx.get("participations_stats") or {},
            "can_mark_attendance": bool(ctx.get("user_can_mark_attendance")),
            "rsvp_choices": _choices(dm.MeetingParticipation.RSVPStatus.choices),
            "attendance_choices": _choices(dm.MeetingParticipation.AttendanceStatus.choices),
            "reviews": _reviews(ctx),
            "structured_decisions": [
                {
                    "id": d.pk, "title": d.title, "status": d.status, "status_label": d.get_status_display(),
                    "category_label": d.get_category_display(), "decided_at": _iso(d.decided_at),
                }
                for d in m.structured_decisions.filter(is_archived=False).order_by("-decided_at")[:50]
            ],
            "recordings": [_recording_status(r) for r in recordings],
            "max_upload_mb": ctx.get("MAX_RECORDING_UPLOAD_MB", 600),
            "downloads": {
                "docx": _url("meeting_minutes_docx", pk=m.pk),
                "pdf": _url("meeting_minutes_pdf", pk=m.pk),
            },
            "legacy_url": _url("meeting_detail", pk=m.pk),
        }
        return Response(data)


class MeetingDashboardView(APIView):
    """``GET meetings/dashboard/`` — ``MeetingDashboardView.build_context`` (workspaces de l'utilisateur)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from project.views_meeting import MeetingDashboardView as Legacy

        ctx = _legacy(Legacy, request).build_context(request._request)

        def row(m):
            data = _meeting_row(m)
            data["projects_count"] = m.projects.count() if hasattr(m, "projects") else 0
            return data

        return Response({
            "month_stats": {k: v or 0 for k, v in (ctx.get("month_stats") or {}).items()},
            "upcoming": [row(m) for m in ctx.get("upcoming_meetings") or []],
            "recent": [_meeting_row(m) for m in ctx.get("recent_meetings") or []],
            "top_projects": [
                {"id": p["project_id"], "name": p["project__name"], "count": p["nb"]}
                for p in ctx.get("top_projects") or []
            ],
            "active_series": [
                {"id": s.pk, "name": s.name, "recurrence_label": s.recurrence_label}
                for s in ctx.get("active_series") or []
            ],
            "calendar": [
                {
                    "day": c.get("day"),
                    "date": _iso(c.get("date")),
                    "count": c.get("nb", 0),
                    "is_today": bool(c.get("is_today")),
                    "is_weekend": bool(c.get("is_weekend")),
                }
                for c in ctx.get("calendar_grid") or []
            ],
            "speaking": ctx.get("speaking_rows") or [],
            "execution_rate": ctx.get("execution_rate", 0),
            "total_decisions_year": ctx.get("total_decisions_year", 0),
            "executed_decisions_year": ctx.get("executed_decisions_year", 0),
            "top_discussed_projects": [
                {"title": p["title"], "count": p["nb"]} for p in ctx.get("top_discussed_projects") or []
            ],
        })


class MeetingDecisionsView(APIView):
    """``GET meetings/decisions/`` — ``MeetingDecisionListView.build_context`` (filtres ``status``, ``category``)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from project.views_meeting import MeetingDecisionListView

        ctx = _legacy(MeetingDecisionListView, request).build_context(request._request)
        decisions = list(ctx.get("decisions") or [])
        return Response({
            "results": [
                {
                    "id": d.pk,
                    "title": d.title,
                    "description": d.description or "",
                    "category": d.category,
                    "category_label": d.get_category_display(),
                    "status": d.status,
                    "status_label": d.get_status_display(),
                    "decided_by": _name(d.decided_by) if d.decided_by_id else "",
                    "decided_at": _iso(d.decided_at),
                    "executed_at": _iso(d.executed_at),
                    "meeting": {"id": d.meeting_id, "title": d.meeting.title} if d.meeting_id else None,
                    "projects": [{"id": p.pk, "name": p.name} for p in d.projects.all()],
                }
                for d in decisions
            ],
            "count": len(decisions),
            "status_choices": _choices(ctx.get("status_choices") or []),
            "category_choices": _choices(ctx.get("category_choices") or []),
        })


class MeetingSeriesListView(APIView):
    """``GET meetings/series/`` — ``MeetingSeriesListView`` (recherche ``q``, pagination)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from project.views_meeting import MeetingSeriesListView as Legacy

        _view, ctx = _run(Legacy, request, {})
        page = ctx.get("page_obj")
        items = list(ctx.get("object_list") or [])
        return Response({
            "results": [
                {
                    "id": s.pk,
                    "name": s.name,
                    "description": s.description or "",
                    "type_label": s.get_meeting_type_display(),
                    "recurrence_label": s.recurrence_label,
                    "default_projects_count": s.default_projects.count(),
                    "is_active": s.is_active,
                }
                for s in items
            ],
            "count": page.paginator.count if page else len(items),
            "page": page.number if page else 1,
            "num_pages": page.paginator.num_pages if page else 1,
        })


class MeetingSeriesDetailView(APIView):
    """``GET meetings/series/<pk>/`` — ``MeetingSeriesDetailView`` (occurrences à venir et passées)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        from project.views_meeting import MeetingSeriesDetailView as Legacy

        _view, ctx = _run(Legacy, request, {"pk": pk})
        s = ctx["series"]

        def occ(m):
            return {"id": m.pk, "scheduled_at": _iso(m.scheduled_at), "status": m.status,
                    "status_label": m.get_status_display(), "title": m.title}

        return Response({
            "id": s.pk,
            "name": s.name,
            "description": s.description or "",
            "meeting_type": s.meeting_type,
            "type_label": s.get_meeting_type_display(),
            "recurrence": s.recurrence,
            "recurrence_label": s.recurrence_label,
            "start_date": _iso(s.start_date),
            "end_date": _iso(s.end_date),
            "time_local": s.time_local.strftime("%H:%M") if s.time_local else "",
            "duration_minutes": s.duration_minutes,
            "location": s.location or "",
            "meeting_link": s.meeting_link or "",
            "is_active": s.is_active,
            "organizer": _name(s.organizer) if s.organizer_id else "",
            "default_participants": [_user(u) for u in s.default_participants.all()],
            "default_projects": [{"id": p.pk, "name": p.name} for p in s.default_projects.all()],
            "default_agenda": s.default_agenda or "",
            "upcoming": [occ(m) for m in ctx.get("upcoming_occurrences") or []],
            "past": [occ(m) for m in ctx.get("past_occurrences") or []],
            "legacy_url": _url("meeting_series_detail", pk=s.pk),
        })


class MeetingRecordingStatusView(APIView):
    """``GET meetings/recordings/<pk>/status/`` — équivalent JSON du fragment de polling htmx."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, recording_pk):
        from project.views_recording import _get_recording_for_user

        return Response(_recording_status(_get_recording_for_user(request, recording_pk)))


class MeetingRecordingDetailView(APIView):
    """
    ``GET meetings/recordings/<pk>/`` — page « compte-rendu » + page « identifier
    les voix » : ``RecordingSummaryView.build_context`` et
    ``SpeakerMappingView.build_context`` (scoping identique), transcription.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, recording_pk):
        from project.views_meeting import can_convert_to_project, can_convert_to_task
        from project.views_recording import RecordingSummaryView, SpeakerMappingView

        summary = _legacy(RecordingSummaryView, request).build_context(request._request, recording_pk)
        speakers_ctx = _legacy(SpeakerMappingView, request).build_context(request._request, recording_pk)
        rec = summary["recording"]
        meeting = summary["meeting"]
        speakers = list(speakers_ctx["speakers"])
        names = {
            sp.speaker_label: (sp.display_name or _name(sp.mapped_participant) or sp.speaker_label)
            for sp in speakers
        }
        segments_qs = rec.segments.order_by("start_seconds", "id")
        segments = list(segments_qs[:SEGMENTS_LIMIT])

        def sample_url(sp):
            if not sp.sample_audio:
                return None
            base = _url(
                "recording_stream_speaker_sample",
                meeting_pk=rec.meeting_id, recording_pk=rec.pk, speaker_label=sp.speaker_label,
            )
            token = getattr(sp, "sample_token", "")
            return f"{base}?token={token}" if base and token else base

        def extractions(key):
            return [_extraction(e) for e in summary.get(key) or []]

        return Response({
            **_recording_status(rec),
            "meeting": {
                "id": meeting.pk,
                "title": meeting.title,
                "scheduled_at": _iso(meeting.scheduled_at),
                "internal_participants_count": meeting.internal_participants.count(),
                "has_external_participants": bool((meeting.external_participants or "").strip()),
            },
            "consent_acknowledged": rec.consent_acknowledged,
            "original_filename": rec.original_filename or "",
            "file_size_bytes": rec.file_size_bytes,
            "tokens_used": rec.tokens_used,
            "summary_markdown": rec.summary_markdown or "",
            "transcript": rec.final_transcript or rec.full_transcript or "",
            "segments": [
                {
                    "speaker_label": s.speaker_label,
                    "speaker": names.get(s.speaker_label, s.speaker_label),
                    "start": s.start_seconds,
                    "end": s.end_seconds,
                    "text": s.text,
                }
                for s in segments
            ],
            "segments_total": segments_qs.count(),
            "speakers": [
                {
                    "label": sp.speaker_label,
                    "display_name": sp.display_name or "",
                    "total_duration_seconds": sp.total_duration_seconds,
                    "total_segments": sp.total_segments,
                    "mapped_participant_id": sp.mapped_participant_id,
                    "is_confirmed": sp.is_confirmed,
                    "sample_url": sample_url(sp),
                }
                for sp in speakers
            ],
            "participants": speakers_ctx.get("participants") or [],
            "all_mapped": bool(speakers_ctx.get("all_mapped")),
            "decisions": extractions("decisions"),
            "actions": extractions("actions"),
            "risks": extractions("risks"),
            "project_suggestions": extractions("project_suggestions"),
            "sprint_suggestions": extractions("sprint_suggestions"),
            "milestone_suggestions": extractions("milestone_suggestions"),
            "task_suggestions": extractions("task_suggestions"),
            "mentions": extractions("mentions"),
            # Mêmes règles que RecordingConvertSuggestionView (RBAC).
            "can_create_projects": can_convert_to_project(request.user, rec.workspace),
            "can_create_tasks": can_convert_to_task(
                request.user, rec.workspace, meeting.project or meeting.projects.first(),
            ),
            "audio_url": _url("recording_stream_audio", recording_pk=rec.pk) if rec.audio_file else None,
            "downloads": {
                "docx": _url("recording_minutes_docx", meeting_pk=rec.meeting_id, recording_pk=rec.pk),
                "pdf": _url("recording_minutes_pdf", meeting_pk=rec.meeting_id, recording_pk=rec.pk),
            },
        })


# ─────────────────────────────────────────────────────────────────────
# Upload audio — vue historique, avec quota IA
# ─────────────────────────────────────────────────────────────────────
class MeetingRecordingUploadView(APIView):
    """
    ``POST meetings/<meeting_pk>/recordings/upload/`` (multipart ``audio``,
    ``duration_seconds``, ``consent_acknowledged``, ``recording_id``) — exécute
    ``api_upload_recording`` (scoping workspace, taille max, pipeline Celery)
    sans rien réécrire. L'upload lance une transcription puis une synthèse IA
    payantes : ``AIActionRateThrottle`` (même quota que les autres actions IA).
    Cette route recouvre la route historique ``api_recording_upload`` : l'ancien
    widget d'enregistrement est donc limité lui aussi.
    """

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [AIActionRateThrottle]

    def post(self, request, meeting_pk):
        from project.views_recording import api_upload_recording

        django_request = request._request
        django_request.user = request.user
        return api_upload_recording(django_request, meeting_pk)


# ─────────────────────────────────────────────────────────────────────
# Écriture — pont vers les vues d'action existantes
# ─────────────────────────────────────────────────────────────────────
class _LegacyAction(APIView):
    """POST multipart → vue Django d'action (``run_action_view`` : JSON, messages → JSON, 403/404 conservés)."""

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    legacy_view = ""

    def post(self, request, **kwargs):
        return run_action_view(request, import_string(self.legacy_view), kwargs)


def _bridge(path: str, *, ai: bool = False):
    attrs = {"legacy_view": path, "__doc__": f"POST → ``{path}``" + (" (IA : AIActionRateThrottle)" if ai else "")}
    if ai:
        attrs["throttle_classes"] = [AIActionRateThrottle]
    return type(path.rsplit(".", 1)[1] + "Bridge", (_LegacyAction,), attrs)


_VM = "project.views_meeting."
_VR = "project.views_recording."

# Fiche réunion
MeetingAIProcessAction = _bridge(_VM + "MeetingAIProcessView", ai=True)
MeetingAISummaryAction = _bridge(_VM + "MeetingMinutesAISummaryView", ai=True)
MeetingReviewsSaveAction = _bridge(_VM + "MeetingReviewsSaveView")
MeetingRSVPAction = _bridge(_VM + "MeetingRSVPView")
MeetingSelfPresentAction = _bridge(_VM + "MeetingSelfPresentView")
MeetingAttendanceAction = _bridge(_VM + "MeetingMarkAttendanceView")
MeetingAgendaCreateAction = _bridge(_VM + "MeetingAgendaItemCreateView")
MeetingAgendaUpdateAction = _bridge(_VM + "MeetingAgendaItemUpdateView")
MeetingAgendaDeleteAction = _bridge(_VM + "MeetingAgendaItemDeleteView")
MeetingAgendaReorderAction = _bridge(_VM + "MeetingAgendaReorderView")
MeetingActionItemCreateAction = _bridge(_VM + "MeetingActionItemCreateView")
MeetingActionItemConvertAction = _bridge(_VM + "MeetingActionItemConvertToTaskView")
# Enregistrements
RecordingSpeakerMappingAction = _bridge(_VR + "SpeakerMappingPostView")
RecordingConfirmSpeakersAction = _bridge(_VR + "ConfirmSpeakersView", ai=True)
RecordingRegenerateAction = _bridge(_VR + "RecordingRegenerateSummaryView", ai=True)
RecordingDeleteAction = _bridge(_VR + "RecordingDeleteView")
RecordingAcceptDecisionsAction = _bridge(_VR + "CreateDecisionsView")
RecordingCreateActionsAction = _bridge(_VR + "CreateActionPlansView")
RecordingConvertSuggestionsAction = _bridge(_VM + "RecordingConvertSuggestionView")


# ─────────────────────────────────────────────────────────────────────
# Envoi des comptes rendus — Celery uniquement
# ─────────────────────────────────────────────────────────────────────
SEND_UNAVAILABLE = "Le service d'envoi est indisponible, réessayez dans quelques instants."


class MeetingSendMinutesView(APIView):
    """
    ``POST meetings/<pk>/send-minutes/`` — même scoping que ``MeetingSendMinutesView``
    (workspace courant) ; tâche Celery existante ``send_meeting_minutes_email_async``.
    """

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        from project.tasks import send_meeting_minutes_email_async
        from project.views_meeting import MeetingSendMinutesView as Legacy

        view = _legacy(Legacy, request, pk=pk)
        meeting = view.filter_by_workspace(dm.ProjectMeeting.objects.all()).filter(pk=pk).first()
        if meeting is None:
            raise NotFound("Réunion introuvable.")
        include_external = str(request.data.get("include_external", "1")) == "1"
        try:
            send_meeting_minutes_email_async.delay(meeting.pk, include_external)
        except Exception:
            logger.exception("send_meeting_minutes_email_async dispatch failed")
            return Response({"detail": SEND_UNAVAILABLE}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({"messages": ["Envoi du compte-rendu lancé en arrière-plan."]})


class RecordingSendMinutesView(APIView):
    """
    ``POST meetings/recordings/<pk>/send-minutes/`` (``extra_emails``) — mêmes
    destinataires que ``RecordingSendEmailView`` ; envoi par Celery
    (``send_recording_minutes_email_async``) au lieu d'un envoi synchrone.
    """

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, recording_pk):
        from project.services.recording.export import _EMAIL_RE, _collect_recipients
        from project.tasks import send_recording_minutes_email_async
        from project.views_recording import _get_recording_for_user

        recording = _get_recording_for_user(request, recording_pk)
        extra_emails = _EMAIL_RE.findall(str(request.data.get("extra_emails", "") or ""))
        recipients = _collect_recipients(recording, include_external=True, extra_emails=extra_emails)
        if not recipients:
            return Response(
                {"detail": "Aucun destinataire — vérifiez les emails des participants ou ajoutez des adresses externes."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            send_recording_minutes_email_async.delay(recording.pk, extra_emails, True)
        except Exception:
            logger.exception("send_recording_minutes_email_async dispatch failed")
            return Response({"detail": SEND_UNAVAILABLE}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({"messages": [f"Envoi du compte-rendu lancé à {len(recipients)} destinataire(s)."]})
