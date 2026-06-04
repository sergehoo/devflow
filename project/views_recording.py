"""
Vues du module Enregistrement audio + transcription IA (PR-REC-3).

  * Pages HTML : SpeakerMappingView, RecordingSummaryView, StatusFragmentView
  * Endpoints JSON : upload_recording, recording_status
  * Stream audio sécurisé (HMAC token) : stream_audio, stream_speaker_sample
  * Actions POST : SpeakerMappingPostView, ConfirmSpeakersView,
    CreateDecisionsView, CreateActionPlansView

Sécurité workspace : toutes les vues filtrent par
``self.filter_by_workspace(...)`` ou via ``get_user_workspace_ids(user)``.
"""

from __future__ import annotations

import json
import logging
import os
import time

from django.contrib import messages
from django.http import (
    Http404, HttpResponse, JsonResponse, StreamingHttpResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.http import require_GET, require_POST

from project import models as dm
from project.services.recording.audio_tokens import (
    generate_audio_token, verify_audio_token,
)
from project.services.recording.speaker_mapping import (
    confirm_all_mappings, map_speaker_to_participant,
)
from project.utils.workspaces import get_user_workspace_ids
from project.views import DevflowBaseMixin, WorkspaceSecurityMixin

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Pages HTML
# ─────────────────────────────────────────────────────────────────────
class SpeakerMappingView(WorkspaceSecurityMixin, DevflowBaseMixin, View):
    """Page d'identification manuelle des voix détectées."""
    template_name = "project/meeting/recording_speakers.html"

    def get(self, request, meeting_pk, recording_pk):
        recording = self._get_recording(request, recording_pk)
        speakers = recording.speakers.select_related("mapped_participant").order_by("speaker_label")
        # Liste des participants du meeting
        users = list(recording.meeting.internal_participants.all())
        # Ajoute organisateur et créateur si manquants
        for u in [recording.meeting.organizer, recording.meeting.created_by]:
            if u and u not in users:
                users.append(u)
        participants_list = [
            {
                "id": str(u.pk),
                "full_name": u.get_full_name() or u.get_username(),
                "email": u.email or "",
            }
            for u in users if u
        ]
        # Token audio pour chaque speaker sample
        for sp in speakers:
            if sp.sample_audio:
                sp.sample_token = generate_audio_token(
                    resource_path=(
                        f"/meetings/{recording.meeting_id}/recordings/"
                        f"{recording.pk}/speakers/{sp.speaker_label}/sample/"
                    ),
                    user_id=str(request.user.pk),
                )
            else:
                sp.sample_token = ""
        all_mapped = all(sp.mapped_participant_id for sp in speakers) and len(speakers) > 0
        return render(request, self.template_name, {
            "meeting": recording.meeting,
            "recording": recording,
            "speakers": speakers,
            "participants": participants_list,
            "all_mapped": all_mapped,
            "section": "meetings",
            "page_title": "Identifier les voix",
            "breadcrumb": "Collaboration · Réunions · Mapping voix",
        })

    def _get_recording(self, request, recording_pk):
        ws_ids = get_user_workspace_ids(request.user)
        recording = dm.MeetingRecording.objects.filter(
            pk=recording_pk, workspace_id__in=ws_ids,
        ).first()
        if recording is None:
            raise Http404("Enregistrement introuvable.")
        return recording


class SpeakerMappingPostView(WorkspaceSecurityMixin, DevflowBaseMixin, View):
    """POST du formulaire de mapping voix → user."""

    @method_decorator(csrf_protect)
    def post(self, request, recording_pk):
        ws_ids = get_user_workspace_ids(request.user)
        recording = get_object_or_404(
            dm.MeetingRecording, pk=recording_pk, workspace_id__in=ws_ids,
        )
        from django.contrib.auth import get_user_model
        User = get_user_model()
        speakers = list(recording.speakers.all())
        ok, fail = 0, 0
        for sp in speakers:
            user_id = request.POST.get(f"speaker_{sp.speaker_label}")
            if not user_id:
                continue
            try:
                u = User.objects.filter(pk=user_id).first()
                if u is None:
                    continue
                map_speaker_to_participant(
                    recording=recording, speaker_label=sp.speaker_label,
                    participant=u, confirmed_by=request.user,
                )
                ok += 1
            except (PermissionError, ValueError) as exc:
                logger.warning("speaker_mapping: %s", exc)
                fail += 1
        if ok:
            messages.success(request, f"{ok} association(s) enregistrée(s).")
        if fail:
            messages.error(request, f"{fail} association(s) refusée(s) (cross-tenant ?).")
        return redirect(
            "recording_speakers",
            meeting_pk=recording.meeting_id, recording_pk=recording.pk,
        )


class ConfirmSpeakersView(WorkspaceSecurityMixin, DevflowBaseMixin, View):
    """POST final : confirme tous les mappings et lance pipeline summary."""

    @method_decorator(csrf_protect)
    def post(self, request, recording_pk):
        ws_ids = get_user_workspace_ids(request.user)
        recording = get_object_or_404(
            dm.MeetingRecording, pk=recording_pk, workspace_id__in=ws_ids,
        )
        try:
            confirm_all_mappings(recording=recording, confirmed_by=request.user)
        except ValueError as exc:
            messages.error(request, f"Impossible de confirmer : {exc}")
            return redirect(
                "recording_speakers",
                meeting_pk=recording.meeting_id, recording_pk=recording.pk,
            )
        try:
            from project.tasks import finalize_recording_task
            finalize_recording_task.delay(recording.pk)
            messages.info(
                request,
                "Génération du compte-rendu IA lancée — vous serez notifié.",
            )
        except Exception:
            # Fallback synchrone si Celery indispo
            from project.services.recording.pipeline import finalize_recording
            try:
                finalize_recording(recording.pk)
            except Exception as exc:
                logger.exception("finalize sync failed: %s", exc)
        return redirect(
            "recording_summary",
            meeting_pk=recording.meeting_id, recording_pk=recording.pk,
        )


class RecordingSummaryView(WorkspaceSecurityMixin, DevflowBaseMixin, View):
    """Page de visualisation du compte-rendu IA + extractions à valider."""
    template_name = "project/meeting/recording_summary.html"

    def get(self, request, meeting_pk, recording_pk):
        ws_ids = get_user_workspace_ids(request.user)
        recording = get_object_or_404(
            dm.MeetingRecording.objects.select_related("meeting", "workspace"),
            pk=recording_pk, workspace_id__in=ws_ids,
        )
        extractions = recording.ai_extractions.all().order_by("kind", "id")
        decisions = [e for e in extractions if e.kind == "decision"]
        actions = [e for e in extractions if e.kind == "action"]
        risks = [e for e in extractions if e.kind == "risk"]
        return render(request, self.template_name, {
            "meeting": recording.meeting,
            "recording": recording,
            "decisions": decisions,
            "actions": actions,
            "risks": risks,
            "section": "meetings",
            "page_title": "Compte-rendu IA",
            "breadcrumb": "Collaboration · Réunions · Compte-rendu",
        })


class RecordingStatusFragmentView(WorkspaceSecurityMixin, DevflowBaseMixin, View):
    """Fragment HTML retourné par polling htmx (toutes les 3s)."""
    template_name = "project/meeting/recording_status_fragment.html"

    def get(self, request, recording_pk):
        ws_ids = get_user_workspace_ids(request.user)
        recording = get_object_or_404(
            dm.MeetingRecording, pk=recording_pk, workspace_id__in=ws_ids,
        )
        return render(request, self.template_name, {
            "recording": recording,
            "is_terminal": recording.is_terminal or
                           recording.status == dm.MeetingRecording.Status.WAITING_SPEAKER_MAPPING,
        })


# ─────────────────────────────────────────────────────────────────────
# Création décisions / actions depuis extractions IA
# ─────────────────────────────────────────────────────────────────────
class CreateActionPlansView(WorkspaceSecurityMixin, DevflowBaseMixin, View):
    """POST : transforme les RecordingAIExtraction (action) cochées en
    vrais MeetingActionItem."""

    @method_decorator(csrf_protect)
    def post(self, request, recording_pk):
        ws_ids = get_user_workspace_ids(request.user)
        recording = get_object_or_404(
            dm.MeetingRecording, pk=recording_pk, workspace_id__in=ws_ids,
        )
        ids = request.POST.getlist("accept_action")
        created = 0
        for ext in recording.ai_extractions.filter(
            pk__in=ids, kind=dm.RecordingAIExtraction.Kind.ACTION,
            is_accepted=False,
        ):
            try:
                item = dm.MeetingActionItem.objects.create(
                    meeting=recording.meeting,
                    title=ext.title[:240],
                    description=ext.description or "",
                    priority=(ext.priority_hint or "MEDIUM").upper()[:15],
                )
                ext.is_accepted = True
                ext.accepted_at = timezone.now()
                ext.created_action_item = item
                ext.save(update_fields=[
                    "is_accepted", "accepted_at", "created_action_item", "updated_at",
                ])
                created += 1
            except Exception as exc:
                logger.warning("create action item failed: %s", exc)
        messages.success(request, f"{created} action(s) créée(s).")
        return redirect("recording_summary",
                        meeting_pk=recording.meeting_id, recording_pk=recording.pk)


class CreateDecisionsView(WorkspaceSecurityMixin, DevflowBaseMixin, View):
    """POST : marque les RecordingAIExtraction (decision) comme acceptées.
    Pour l'instant on n'a pas de modèle Decision dédié dans DevFlow — on
    se contente de marquer is_accepted=True (la décision restera visible
    dans le CR)."""

    @method_decorator(csrf_protect)
    def post(self, request, recording_pk):
        ws_ids = get_user_workspace_ids(request.user)
        recording = get_object_or_404(
            dm.MeetingRecording, pk=recording_pk, workspace_id__in=ws_ids,
        )
        ids = request.POST.getlist("accept_decision")
        n = recording.ai_extractions.filter(
            pk__in=ids, kind=dm.RecordingAIExtraction.Kind.DECISION,
        ).update(is_accepted=True, accepted_at=timezone.now())
        messages.success(request, f"{n} décision(s) validée(s).")
        return redirect("recording_summary",
                        meeting_pk=recording.meeting_id, recording_pk=recording.pk)


# ─────────────────────────────────────────────────────────────────────
# API JSON (utilisées par recorder.js)
# ─────────────────────────────────────────────────────────────────────
@require_POST
def api_upload_recording(request, meeting_pk):
    """Upload du Blob audio depuis le JS recorder."""
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Non authentifié"}, status=401)
    ws_ids = get_user_workspace_ids(request.user)
    meeting = get_object_or_404(
        dm.ProjectMeeting, pk=meeting_pk, workspace_id__in=ws_ids,
    )
    audio = request.FILES.get("audio")
    if not audio:
        return JsonResponse({"detail": "Fichier audio requis."}, status=400)
    from django.conf import settings
    max_mb = getattr(settings, "MAX_RECORDING_UPLOAD_MB", 600)
    if audio.size > max_mb * 1024 * 1024:
        return JsonResponse(
            {"detail": f"Fichier trop volumineux (max {max_mb} Mo)."},
            status=400,
        )
    consent = request.POST.get("consent_acknowledged", "false") == "true"
    duration = float(request.POST.get("duration_seconds", 0) or 0)

    rec_id = request.POST.get("recording_id")
    if rec_id:
        recording = dm.MeetingRecording.objects.filter(
            pk=rec_id, meeting=meeting,
        ).first()
        if recording is None:
            return JsonResponse({"detail": "Recording introuvable."}, status=404)
    else:
        recording = dm.MeetingRecording.objects.create(
            workspace=meeting.workspace, meeting=meeting,
            recorded_by=request.user,
            consent_acknowledged=consent,
            consent_acknowledged_at=timezone.now() if consent else None,
        )
    recording.status = dm.MeetingRecording.Status.UPLOADING
    recording.save(update_fields=["status", "updated_at"])
    try:
        from django.core.files.base import ContentFile
        filename = audio.name or "recording.webm"
        recording.audio_file.save(filename, audio, save=False)
        recording.original_filename = filename
        recording.mime_type = audio.content_type or ""
        recording.duration_seconds = duration
        recording.file_size_bytes = audio.size
        recording.status = dm.MeetingRecording.Status.UPLOADED
        recording.save(update_fields=[
            "audio_file", "original_filename", "mime_type",
            "duration_seconds", "file_size_bytes", "status", "updated_at",
        ])
    except Exception as exc:
        logger.exception("upload save failed: %s", exc)
        return JsonResponse(
            {"detail": f"Erreur stockage : {exc}",
             "recording_id": str(recording.pk)},
            status=502,
        )

    # Lance le pipeline en async
    try:
        from project.tasks import process_recording_task
        process_recording_task.delay(recording.pk)
    except Exception as exc:
        logger.warning("Celery dispatch failed: %s", exc)

    return JsonResponse({
        "recording_id": str(recording.pk),
        "status": recording.status,
        "status_url": f"/api/v1/recordings/{recording.pk}/status/",
        "redirect_url": (
            f"/meetings/{meeting.pk}/recordings/{recording.pk}/speakers/"
        ),
    }, status=202)


@require_GET
def api_recording_status(request, recording_pk):
    """Polling JSON — état actuel du pipeline."""
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Non authentifié"}, status=401)
    ws_ids = get_user_workspace_ids(request.user)
    rec = dm.MeetingRecording.objects.filter(
        pk=recording_pk, workspace_id__in=ws_ids,
    ).first()
    if rec is None:
        return JsonResponse({"detail": "Recording introuvable."}, status=404)
    redirect_url = None
    if rec.status == dm.MeetingRecording.Status.WAITING_SPEAKER_MAPPING:
        redirect_url = f"/meetings/{rec.meeting_id}/recordings/{rec.pk}/speakers/"
    elif rec.status == dm.MeetingRecording.Status.COMPLETED:
        redirect_url = f"/meetings/{rec.meeting_id}/recordings/{rec.pk}/summary/"
    return JsonResponse({
        "id": str(rec.pk),
        "status": rec.status,
        "status_label": rec.get_status_display(),
        "duration_seconds": rec.duration_seconds,
        "speakers_count": rec.speakers.count(),
        "error_message": rec.error_message,
        "redirect_url": redirect_url,
        "is_terminal": rec.is_terminal,
    })


# ─────────────────────────────────────────────────────────────────────
# Stream audio (HMAC token)
# ─────────────────────────────────────────────────────────────────────
@require_GET
def stream_speaker_sample(request, meeting_pk, recording_pk, speaker_label):
    """
    Stream un extrait audio MP3 d'un speaker. Authentification :
    soit session Django + workspace, soit token HMAC en query string.
    """
    rec = dm.MeetingRecording.objects.filter(pk=recording_pk).first()
    if rec is None:
        raise Http404("Recording introuvable.")
    if not _verify_audio_access(request, rec):
        return JsonResponse({"detail": "Token audio invalide."}, status=401)
    speaker = dm.DetectedSpeaker.objects.filter(
        recording=rec, speaker_label=speaker_label,
    ).first()
    if speaker is None or not speaker.sample_audio:
        raise Http404("Extrait audio non disponible.")
    return _stream_file_response(
        speaker.sample_audio, content_type="audio/mpeg",
        filename=f"{speaker_label}.mp3",
    )


@require_GET
def stream_recording_audio(request, recording_pk):
    """Stream le fichier audio brut complet (privilégier l'écoute partielle)."""
    rec = dm.MeetingRecording.objects.filter(pk=recording_pk).first()
    if rec is None:
        raise Http404("Recording introuvable.")
    if not _verify_audio_access(request, rec):
        return JsonResponse({"detail": "Token audio invalide."}, status=401)
    if not rec.audio_file:
        raise Http404("Aucun fichier audio.")
    content_type = rec.mime_type or "audio/webm"
    return _stream_file_response(
        rec.audio_file, content_type=content_type,
        filename=os.path.basename(rec.audio_file.name or "recording"),
    )


def _verify_audio_access(request, recording):
    """Vérifie token HMAC OU session Django + workspace."""
    token = request.GET.get("token")
    if token:
        payload = verify_audio_token(token=token, resource_path=request.path)
        if payload is None:
            return False
        return True
    # Sinon : session Django
    if not request.user.is_authenticated:
        return False
    ws_ids = get_user_workspace_ids(request.user)
    return recording.workspace_id in ws_ids


def _stream_file_response(file_field, *, content_type, filename):
    try:
        file_field.open("rb")
    except Exception as exc:
        logger.exception("Cannot open audio: %s", exc)
        raise Http404("Fichier inaccessible.")

    def _iter():
        try:
            while True:
                chunk = file_field.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            try:
                file_field.close()
            except Exception:
                pass

    response = StreamingHttpResponse(_iter(), content_type=content_type)
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    response["Cache-Control"] = "private, max-age=3600"
    response["Accept-Ranges"] = "bytes"
    return response
