"""
Vues du module Réunions DevFlow.
Architecture alignée sur les vues génériques DevFlow.
"""

from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from project.utils.workspaces import get_user_workspace_ids
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View

from project import models as dm
from project.forms_meeting import MeetingActionItemForm, ProjectMeetingForm
from project.services.ai.services.meeting_intelligence import (
    MeetingIntelligenceService,
)
from project.utils.workspaces import get_user_workspace_ids
from project.views import (
    DevflowCreateView,
    DevflowDeleteView,
    DevflowDetailView,
    DevflowListView,
    DevflowUpdateView,
)

logger = logging.getLogger(__name__)


class ProjectMeetingListView(DevflowListView):
    model = dm.ProjectMeeting
    template_name = "project/meeting/list.html"
    section = "project"
    page_title = "Réunions projet"
    search_fields = ("title", "agenda", "notes", "decisions", "project__name")
    paginate_by = 20

    def get_queryset(self):
        # PR-MEET-SORT : on trie d'abord par "futur vs passé" (futur en
        # haut), puis par distance à maintenant (la plus proche d'abord
        # dans chaque bucket).
        #
        #   1. is_past=0 (futures) — triées par scheduled_at ASC
        #   2. is_past=1 (passées) — triées par scheduled_at DESC
        #
        # Astuce SQL : on utilise une `offset_from_now` qui est toujours
        # positive et croissante quand on s'éloigne de maintenant, peu
        # importe le sens. Combiné avec is_past, ça nous donne le bon ordre.
        from django.db.models import (
            Case, When, F, Value, IntegerField, DurationField,
            ExpressionWrapper,
        )
        now = timezone.now()
        qs = (
            super().get_queryset()
            .select_related("project", "organizer", "sprint", "workspace")
            .prefetch_related("internal_participants")
            .annotate(
                is_past=Case(
                    When(scheduled_at__lt=now, then=Value(1)),
                    default=Value(0),
                    output_field=IntegerField(),
                ),
                offset_from_now=Case(
                    When(
                        scheduled_at__gte=now,
                        then=ExpressionWrapper(
                            F("scheduled_at") - now,
                            output_field=DurationField(),
                        ),
                    ),
                    default=ExpressionWrapper(
                        now - F("scheduled_at"),
                        output_field=DurationField(),
                    ),
                ),
            )
            .order_by("is_past", "offset_from_now")
        )
        project_id = self.request.GET.get("project")
        meeting_type = self.request.GET.get("type")
        status_q = self.request.GET.get("status")
        if project_id:
            qs = qs.filter(project_id=project_id)
        if meeting_type:
            qs = qs.filter(meeting_type=meeting_type)
        if status_q:
            qs = qs.filter(status=status_q)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["meeting_type_choices"] = dm.ProjectMeeting.MeetingType.choices
        ctx["status_choices"] = dm.ProjectMeeting.Status.choices
        ctx["current_type"] = self.request.GET.get("type", "")
        ctx["current_status"] = self.request.GET.get("status", "")
        ctx["current_project"] = self.request.GET.get("project", "")
        # PR-MEET-SORT : moment "maintenant" pour qu'on puisse marquer
        # visuellement la séparation futur/passé dans le template
        ctx["now"] = timezone.now()
        return ctx


class ProjectMeetingDetailView(DevflowDetailView):
    model = dm.ProjectMeeting
    template_name = "project/meeting/detail.html"
    context_object_name = "meeting"
    section = "project"
    page_title = "Détail réunion"

    def get_queryset(self):
        return (
            super().get_queryset()
            .select_related("project", "sprint", "organizer", "created_by", "updated_by", "series", "workspace")
            .prefetch_related(
                "internal_participants", "action_items__owner", "attachments",
                "projects", "project_reviews__project", "project_reviews__presented_by",
            )
        )

    def get_context_data(self, **kwargs):
        # PR-MEET-3 : formset des MeetingProjectReview pour l'édition
        # inline projet par projet, dans la page de détail.
        from project.forms_meeting import build_project_review_formset
        ctx = super().get_context_data(**kwargs)
        ws = (self.get_current_workspace() if hasattr(self, "get_current_workspace")
              else self.object.workspace)
        FormSet = build_project_review_formset(ws, extra=0)
        ctx["review_formset"] = FormSet(instance=self.object)
        ctx["reviews"] = self.object.project_reviews.select_related(
            "project", "presented_by",
        ).order_by("position", "id")

        # PR-MEET-RSVP : participations + stats RSVP/présence + droits
        meeting = self.object
        participations = list(
            meeting.participations
            .select_related("user", "attendance_marked_by")
            .order_by(
                "user__first_name", "user__last_name", "user__username",
            )
        )
        ctx["participations"] = participations

        user = self.request.user
        my_p = next(
            (p for p in participations if p.user_id == user.pk),
            None,
        )
        ctx["my_participation"] = my_p

        # Stats agrégées pour l'encart latéral
        from collections import Counter
        rsvp_counts = Counter(p.rsvp_status for p in participations)
        att_counts = Counter(p.attendance_status for p in participations)
        ctx["participations_stats"] = {
            "accepted": rsvp_counts.get("ACCEPTED", 0),
            "declined": rsvp_counts.get("DECLINED", 0),
            "tentative": rsvp_counts.get("TENTATIVE", 0),
            "pending": rsvp_counts.get("INVITED", 0),
            "present": att_counts.get("PRESENT", 0) + att_counts.get("LATE", 0) + att_counts.get("LEFT_EARLY", 0),
            "absent": att_counts.get("ABSENT", 0),
        }

        # Droits de marquage présence (organisateur, créateur, superadmin, RBAC)
        can_mark = (
            user.is_superuser
            or meeting.organizer_id == user.pk
            or meeting.created_by_id == user.pk
        )
        if not can_mark:
            try:
                from project.services.rbac import RBACService
                can_mark = RBACService.can(
                    user, "meeting.manage", target=meeting,
                    workspace=meeting.workspace,
                )
            except Exception:
                pass
        ctx["user_can_mark_attendance"] = can_mark

        # PR-MEET-AGENDA-LIVE : items structurés de l'ordre du jour
        ctx["agenda_items"] = list(
            meeting.agenda_items
            .select_related("owner")
            .order_by("position", "id")
        )

        # PR-REC-UX : limite d'upload audio (affichée dans le widget)
        from django.conf import settings
        ctx["MAX_RECORDING_UPLOAD_MB"] = getattr(
            settings, "MAX_RECORDING_UPLOAD_MB", 600,
        )

        return ctx


class ProjectMeetingCreateView(DevflowCreateView):
    model = dm.ProjectMeeting
    form_class = ProjectMeetingForm
    template_name = "project/meeting/form.html"
    section = "project"
    page_title = "Nouvelle réunion"
    success_list_url_name = "meeting_list"

    def get_initial(self):
        initial = super().get_initial()
        project_id = self.request.GET.get("project")
        if project_id:
            initial["project"] = project_id
        initial.setdefault("scheduled_at", timezone.now().strftime("%Y-%m-%dT%H:%M"))
        return initial

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        form.instance.updated_by = self.request.user
        if form.instance.organizer_id is None and self.request.user.is_authenticated:
            form.instance.organizer = self.request.user
        response = super().form_valid(form)
        # PR-MEET-3 : initialise les slots de revue pour les projets cochés
        try:
            from project.services.meeting import MeetingService
            MeetingService.sync_review_slots(self.object)
        except Exception as exc:
            logger.warning("sync_review_slots failed: %s", exc)
        messages.success(self.request, "Réunion enregistrée.")
        return response

    def get_success_url(self):
        if self.object:
            return reverse_lazy("meeting_detail", kwargs={"pk": self.object.pk})
        return super().get_success_url()


class ProjectMeetingUpdateView(DevflowUpdateView):
    model = dm.ProjectMeeting
    form_class = ProjectMeetingForm
    template_name = "project/meeting/form.html"
    section = "project"
    page_title = "Modifier réunion"
    success_list_url_name = "meeting_list"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if hasattr(self, "get_current_workspace"):
            kwargs["current_workspace"] = self.get_current_workspace()
        kwargs["request"] = self.request
        return kwargs

    def form_valid(self, form):
        form.instance.updated_by = self.request.user
        response = super().form_valid(form)
        # PR-MEET-3 : sync les slots de revue si la liste de projets change
        try:
            from project.services.meeting import MeetingService
            MeetingService.sync_review_slots(self.object)
        except Exception as exc:
            logger.warning("sync_review_slots failed: %s", exc)
        messages.success(self.request, "Réunion mise à jour.")
        return response

    def get_success_url(self):
        return reverse_lazy("meeting_detail", kwargs={"pk": self.object.pk})


class ProjectMeetingDeleteView(DevflowDeleteView):
    model = dm.ProjectMeeting
    template_name = "project/crud/confirm_delete.html"
    section = "project"
    page_title = "Supprimer réunion"
    success_list_url_name = "meeting_list"


# =========================================================================
# Action items
# =========================================================================
class MeetingActionItemCreateView(LoginRequiredMixin, View):
    def post(self, request, meeting_pk):
        # SECURITY (Phase 0): scoper la réunion aux workspaces du user.
        user_workspace_ids = get_user_workspace_ids(request.user)
        meeting = get_object_or_404(
            dm.ProjectMeeting,
            pk=meeting_pk,
            workspace_id__in=user_workspace_ids,
        )
        form = MeetingActionItemForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Action invalide.")
            return redirect("meeting_detail", pk=meeting.pk)
        item = form.save(commit=False)
        item.meeting = meeting
        item.save()
        messages.success(request, "Action ajoutée.")
        return redirect("meeting_detail", pk=meeting.pk)


class MeetingActionItemConvertToTaskView(LoginRequiredMixin, View):
    """
    Transforme une MeetingActionItem en vraie Task DevFlow rattachée au
    projet de la réunion. Lien bidirectionnel via converted_task.
    """

    def post(self, request, item_pk):
        # SECURITY (Phase 0): scoper l'action item via le workspace de la
        # réunion parente pour empêcher la conversion cross-tenant.
        user_workspace_ids = get_user_workspace_ids(request.user)
        item = get_object_or_404(
            dm.MeetingActionItem.objects.select_related("meeting", "meeting__project", "owner"),
            pk=item_pk,
            meeting__workspace_id__in=user_workspace_ids,
        )
        if item.converted_task_id:
            messages.info(request, "Cette action est déjà liée à une tâche.")
            return redirect("meeting_detail", pk=item.meeting_id)

        meeting = item.meeting
        try:
            task = dm.Task.objects.create(
                workspace=meeting.workspace,
                project=meeting.project,
                title=item.title[:220],
                description=(item.description or "") + (
                    f"\n\n— Issue de la réunion « {meeting.title} » du "
                    f"{meeting.scheduled_at:%d/%m/%Y}"
                ),
                priority=item.priority or "MEDIUM",
                assignee=item.owner,
                reporter=request.user if request.user.is_authenticated else None,
                due_date=item.due_date,
            )
        except Exception as exc:
            logger.exception("Convert action to task failed")
            messages.error(request, f"Conversion impossible : {exc}")
            return redirect("meeting_detail", pk=meeting.pk)

        item.converted_task = task
        item.converted_at = timezone.now()
        item.converted_by = request.user if request.user.is_authenticated else None
        item.status = dm.MeetingActionItem.Status.IN_PROGRESS
        item.save(update_fields=[
            "converted_task", "converted_at", "converted_by", "status", "updated_at",
        ])
        messages.success(request, f"Tâche « {task.title} » créée à partir de l'action.")
        return redirect("meeting_detail", pk=meeting.pk)


# =========================================================================
# Traitement IA
# =========================================================================
class MeetingAIProcessView(LoginRequiredMixin, View):
    """Lance le pipeline complet IA : résumé + décisions + actions + risques."""

    def post(self, request, meeting_pk):
        # SECURITY (Phase 0): scoper la réunion aux workspaces du user pour
        # éviter qu'un utilisateur ne lance le pipeline IA (et n'expose son
        # contenu) sur une réunion d'un autre tenant.
        user_workspace_ids = get_user_workspace_ids(request.user)
        meeting = get_object_or_404(
            dm.ProjectMeeting,
            pk=meeting_pk,
            workspace_id__in=user_workspace_ids,
        )
        try:
            result = MeetingIntelligenceService.full_process(meeting, actor=request.user)
        except Exception as exc:
            logger.exception("Meeting AI processing failed")
            messages.error(request, f"Traitement IA impossible : {exc}")
            return redirect("meeting_detail", pk=meeting.pk)

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({
                "ok": True,
                "summary": result.summary,
                "decisions": result.decisions,
                "action_items_created": result.created_action_items,
                "risks_created": result.created_risk_insights,
                "used_provider": result.used_provider,
            })

        messages.success(
            request,
            f"✨ IA ({result.used_provider}) — {result.created_action_items} action(s), "
            f"{result.created_risk_insights} risque(s) créé(s).",
        )
        return redirect("meeting_detail", pk=meeting.pk)


# =========================================================================
# PR-MEET-3 : Séries récurrentes + actions compte-rendu
# =========================================================================
from django.http import Http404, HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect

from project.forms_meeting import (
    MeetingSeriesForm,
    build_project_review_formset,
)
from project.services.meeting import MeetingService
from project.views import DevflowBaseMixin, WorkspaceSecurityMixin


# ─── Séries récurrentes ─────────────────────────────────────────────
class MeetingSeriesListView(DevflowListView):
    model = dm.MeetingSeries
    template_name = "project/meeting/series_list.html"
    section = "meetings"
    page_title = "Séries de réunions"
    paginate_by = 25
    search_fields = ("name", "description")
    search_placeholder = "Rechercher une série…"


class MeetingSeriesCreateView(DevflowCreateView):
    model = dm.MeetingSeries
    form_class = MeetingSeriesForm
    template_name = "project/meeting/series_form.html"
    section = "meetings"
    page_title = "Nouvelle série"
    success_list_url_name = "meeting_series_list"

    def form_valid(self, form):
        series = form.save(commit=False)
        series.workspace = self.get_current_workspace()
        series.created_by = self.request.user
        series.save()
        form.save_m2m()
        try:
            created = MeetingService.generate_occurrences(series, horizon_days=60)
            messages.success(
                self.request,
                f"Série créée — {len(created)} occurrence(s) générée(s).",
            )
        except Exception as exc:
            logger.warning("generate_occurrences failed at create: %s", exc)
            messages.success(self.request, "Série créée.")
        return redirect("meeting_series_detail", pk=series.pk)


class MeetingSeriesDetailView(DevflowDetailView):
    model = dm.MeetingSeries
    template_name = "project/meeting/series_detail.html"
    section = "meetings"
    page_title = "Série de réunions"
    context_object_name = "series"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["upcoming_occurrences"] = (
            self.object.occurrences.filter(scheduled_at__gte=timezone.now())
            .order_by("scheduled_at")[:20]
        )
        ctx["past_occurrences"] = (
            self.object.occurrences.filter(scheduled_at__lt=timezone.now())
            .order_by("-scheduled_at")[:20]
        )
        return ctx


class MeetingSeriesUpdateView(DevflowUpdateView):
    model = dm.MeetingSeries
    form_class = MeetingSeriesForm
    template_name = "project/meeting/series_form.html"
    section = "meetings"
    page_title = "Modifier série"
    success_list_url_name = "meeting_series_list"

    def get_success_url(self):
        return reverse_lazy("meeting_series_detail", kwargs={"pk": self.object.pk})


class MeetingSeriesDeleteView(DevflowDeleteView):
    model = dm.MeetingSeries
    template_name = "project/crud/confirm_delete.html"
    section = "meetings"
    page_title = "Supprimer série"
    success_list_url_name = "meeting_series_list"


class MeetingSeriesRegenerateView(WorkspaceSecurityMixin, DevflowBaseMixin, View):
    """POST : régénère les occurrences futures (horizon 60 jours)."""

    @method_decorator(csrf_protect)
    def post(self, request, pk):
        series = self.filter_by_workspace(
            dm.MeetingSeries.objects.all()
        ).filter(pk=pk).first()
        if series is None:
            raise Http404("Série introuvable.")
        created = MeetingService.generate_occurrences(series, horizon_days=60)
        messages.success(
            request,
            f"{len(created)} occurrence(s) (re)générée(s).",
        )
        return redirect("meeting_series_detail", pk=series.pk)


# ─── Actions compte-rendu ──────────────────────────────────────────
class MeetingReviewsSaveView(WorkspaceSecurityMixin, DevflowBaseMixin, View):
    """POST : enregistre toutes les MeetingProjectReview du formset."""

    @method_decorator(csrf_protect)
    def post(self, request, pk):
        meeting = self.filter_by_workspace(
            dm.ProjectMeeting.objects.all()
        ).filter(pk=pk).first()
        if meeting is None:
            raise Http404("Réunion introuvable.")
        ws = self.get_current_workspace() or meeting.workspace
        FormSet = build_project_review_formset(ws, extra=0)
        formset = FormSet(request.POST, instance=meeting)
        if formset.is_valid():
            formset.save()
            messages.success(request, "Revues projet enregistrées.")
        else:
            messages.error(request, "Erreur dans le formulaire de revue.")
        return redirect("meeting_detail", pk=meeting.pk)


class MeetingMinutesAISummaryView(WorkspaceSecurityMixin, DevflowBaseMixin, View):
    """POST : génère un résumé IA structuré du compte-rendu."""

    @method_decorator(csrf_protect)
    def post(self, request, pk):
        meeting = self.filter_by_workspace(
            dm.ProjectMeeting.objects.all()
        ).filter(pk=pk).first()
        if meeting is None:
            raise Http404("Réunion introuvable.")
        text = MeetingService.generate_ai_summary(meeting)
        if text:
            messages.success(request, "Résumé IA généré.")
        else:
            messages.warning(request, "IA indisponible ou résumé vide.")
        return redirect("meeting_detail", pk=meeting.pk)


class MeetingMinutesDocxView(WorkspaceSecurityMixin, DevflowBaseMixin, View):
    """GET : télécharge le compte-rendu .docx avec branding workspace."""

    def get(self, request, pk):
        meeting = self.filter_by_workspace(
            dm.ProjectMeeting.objects.all()
        ).filter(pk=pk).first()
        if meeting is None:
            raise Http404("Réunion introuvable.")
        try:
            docx_bytes = MeetingService.render_minutes_docx(meeting)
        except ImportError:
            messages.error(request, "python-docx n'est pas installé.")
            return redirect("meeting_detail", pk=meeting.pk)
        except Exception as exc:
            logger.exception("render_minutes_docx failed: %s", exc)
            messages.error(request, f"Génération .docx échouée : {exc}")
            return redirect("meeting_detail", pk=meeting.pk)
        filename = f"CR-{meeting.title.replace(' ', '_')}.docx"
        response = HttpResponse(
            docx_bytes,
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class MeetingDashboardView(WorkspaceSecurityMixin, DevflowBaseMixin, View):
    """
    Tableau de bord global des réunions du workspace (PR-MEET-4).

    Vue panoramique :
      * Prochaines réunions (7 jours glissants)
      * Mini-calendrier du mois courant avec dots par jour
      * Statistiques du mois (total, par statut, par type)
      * Réunions par projet (compteur des 10 plus actifs)
      * Séries actives
    """
    template_name = "project/meeting/dashboard.html"

    def get(self, request):
        from django.db.models import Count, Q
        from datetime import datetime, timedelta
        from calendar import monthrange

        ws_ids = get_user_workspace_ids(request.user)
        all_meetings = dm.ProjectMeeting.objects.filter(workspace_id__in=ws_ids)

        now = timezone.now()
        today = now.date()

        # Prochaines réunions (jusqu'à +14 jours)
        upcoming = (
            all_meetings
            .filter(
                scheduled_at__gte=now,
                scheduled_at__lte=now + timedelta(days=14),
                status__in=[
                    dm.ProjectMeeting.Status.PLANNED,
                    dm.ProjectMeeting.Status.HELD,
                ],
            )
            .select_related("project", "organizer", "series")
            .prefetch_related("projects")
            .order_by("scheduled_at")[:20]
        )

        # Réunions récentes (dernière semaine)
        recent = (
            all_meetings
            .filter(scheduled_at__lt=now, scheduled_at__gte=now - timedelta(days=7))
            .select_related("project", "organizer")
            .order_by("-scheduled_at")[:10]
        )

        # Stats du mois courant
        month_start = today.replace(day=1)
        month_end_day = monthrange(today.year, today.month)[1]
        month_end = today.replace(day=month_end_day)
        month_qs = all_meetings.filter(
            scheduled_at__date__gte=month_start,
            scheduled_at__date__lte=month_end,
        )
        stats = month_qs.aggregate(
            total=Count("id"),
            held=Count("id", filter=Q(status=dm.ProjectMeeting.Status.HELD)),
            planned=Count("id", filter=Q(status=dm.ProjectMeeting.Status.PLANNED)),
            cancelled=Count("id", filter=Q(status=dm.ProjectMeeting.Status.CANCELLED)),
        )

        # Top projets par nombre de réunions sur l'année courante
        year_start = today.replace(month=1, day=1)
        top_projects = (
            all_meetings
            .filter(scheduled_at__date__gte=year_start, project__isnull=False)
            .values("project_id", "project__name")
            .annotate(nb=Count("id"))
            .order_by("-nb")[:10]
        )

        # Séries actives
        active_series = (
            dm.MeetingSeries.objects
            .filter(workspace_id__in=ws_ids, is_active=True, is_archived=False)
            .order_by("name")[:10]
        )

        # ── PR-MEET-10 : analyses qualitatives ──
        # Temps de parole par participant (cumul sur tous les recordings
        # du workspace, sur l'année courante)
        from django.db.models import F, FloatField, ExpressionWrapper
        speaking_qs = (
            dm.SpeakerSegment.objects
            .filter(
                recording__workspace_id__in=ws_ids,
                recording__created_at__date__gte=year_start,
            )
            .annotate(dur=ExpressionWrapper(
                F("end_seconds") - F("start_seconds"),
                output_field=FloatField(),
            ))
        )
        from django.db.models import Sum
        # On joint via DetectedSpeaker.mapped_participant
        speaking_by_user = (
            speaking_qs
            .filter(
                # ne garder que les segments dont le label est mappé à un user
                recording__speakers__speaker_label=F("speaker_label"),
                recording__speakers__mapped_participant__isnull=False,
            )
            .values(
                "recording__speakers__mapped_participant_id",
                "recording__speakers__mapped_participant__first_name",
                "recording__speakers__mapped_participant__last_name",
                "recording__speakers__mapped_participant__username",
            )
            .annotate(total_seconds=Sum("dur"))
            .order_by("-total_seconds")[:10]
        )

        # Taux d'exécution des décisions du workspace
        decisions_qs = dm.MeetingDecision.objects.filter(
            workspace_id__in=ws_ids,
            decided_at__date__gte=year_start,
            is_archived=False,
        )
        total_dec = decisions_qs.count()
        executed_dec = decisions_qs.filter(
            status=dm.MeetingDecision.Status.EXECUTED,
        ).count()
        execution_rate = (
            round(100.0 * executed_dec / total_dec, 1) if total_dec else 0
        )

        # Top projets discutés (basé sur PROJECT_MENTION dans les
        # extractions IA des recordings du workspace, année courante)
        top_discussed_projects = (
            dm.RecordingAIExtraction.objects
            .filter(
                recording__workspace_id__in=ws_ids,
                kind=dm.RecordingAIExtraction.Kind.PROJECT_MENTION,
                created_at__date__gte=year_start,
            )
            .values("title")
            .annotate(nb=Count("id"))
            .order_by("-nb")[:8]
        )

        # Calendrier mini-mois : pour chaque jour, nombre de réunions
        days_with_meetings = (
            month_qs
            .extra(select={"day": "DATE(scheduled_at)"})
            .values("day")
            .annotate(nb=Count("id"))
        )
        calendar_map = {row["day"]: row["nb"] for row in days_with_meetings}
        # Construit la grille du mois
        first_weekday = month_start.weekday()  # 0=lundi
        calendar_grid = []
        # Cases vides du début
        for _ in range(first_weekday):
            calendar_grid.append({"day": None, "nb": 0})
        for d in range(1, month_end_day + 1):
            day_date = today.replace(day=d)
            calendar_grid.append({
                "day": d,
                "date": day_date,
                "nb": calendar_map.get(day_date, 0),
                "is_today": (day_date == today),
                "is_weekend": (day_date.weekday() >= 5),
            })

        # Préformate les données speaking pour template
        speaking_rows = []
        for row in speaking_by_user:
            name = (
                (row["recording__speakers__mapped_participant__first_name"] or "")
                + " "
                + (row["recording__speakers__mapped_participant__last_name"] or "")
            ).strip() or row["recording__speakers__mapped_participant__username"]
            speaking_rows.append({
                "name": name,
                "minutes": round((row["total_seconds"] or 0) / 60, 1),
            })

        return render(request, self.template_name, {
            "upcoming_meetings": upcoming,
            "recent_meetings": recent,
            "month_stats": stats,
            "top_projects": top_projects,
            "active_series": active_series,
            "calendar_grid": calendar_grid,
            "current_month_label": today.strftime("%B %Y").capitalize(),
            # PR-MEET-10
            "speaking_rows": speaking_rows,
            "execution_rate": execution_rate,
            "total_decisions_year": total_dec,
            "executed_decisions_year": executed_dec,
            "top_discussed_projects": top_discussed_projects,
            "section": "meetings",
            "page_title": "Tableau de bord réunions",
            "breadcrumb": "Collaboration · Réunions · Vue d'ensemble",
        })


# =========================================================================
# PR-MEET-9 : PDF compte-rendu + Registre décisions + Convert IA
# =========================================================================
class MeetingMinutesPDFView(WorkspaceSecurityMixin, DevflowBaseMixin, View):
    """GET : télécharge le compte-rendu en PDF avec branding workspace."""

    def get(self, request, pk):
        from django.http import HttpResponse
        ws_ids = get_user_workspace_ids(request.user)
        meeting = get_object_or_404(
            dm.ProjectMeeting, pk=pk, workspace_id__in=ws_ids,
        )
        try:
            from project.services.meeting import MeetingService
            pdf_bytes = MeetingService.render_minutes_pdf(meeting)
        except Exception as exc:
            logger.exception("render_minutes_pdf failed: %s", exc)
            messages.error(request, f"Génération PDF échouée : {exc}")
            return redirect("meeting_detail", pk=meeting.pk)
        filename = f"CR-{meeting.title.replace(' ', '_')}.pdf"
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{filename}"'
        return response


class MeetingDecisionListView(WorkspaceSecurityMixin, DevflowBaseMixin, View):
    """Registre transversal de toutes les décisions du workspace."""
    template_name = "project/meeting/decisions_list.html"

    def get(self, request):
        from django.shortcuts import render
        ws = self.get_current_workspace()
        qs = dm.MeetingDecision.objects.filter(workspace=ws, is_archived=False) \
            .select_related("meeting", "decided_by", "executed_by") \
            .prefetch_related("projects").order_by("-decided_at")
        status_filter = request.GET.get("status", "")
        category_filter = request.GET.get("category", "")
        if status_filter:
            qs = qs.filter(status=status_filter)
        if category_filter:
            qs = qs.filter(category=category_filter)
        return render(request, self.template_name, {
            "decisions": qs[:200],
            "status_choices": dm.MeetingDecision.Status.choices,
            "category_choices": dm.MeetingDecision.Category.choices,
            "current_status": status_filter,
            "current_category": category_filter,
            "section": "meetings",
            "page_title": "Registre des décisions",
            "breadcrumb": "Collaboration · Réunions · Décisions",
        })


class RecordingConvertSuggestionView(WorkspaceSecurityMixin, DevflowBaseMixin, View):
    """
    POST : transforme une RecordingAIExtraction (project_suggestion /
    sprint_suggestion / milestone_suggestion) en VRAI objet DevFlow.

    Body : `extraction_id` (PK de l'extraction à convertir).
    """

    @method_decorator(csrf_protect)
    def post(self, request, recording_pk):
        ws_ids = get_user_workspace_ids(request.user)
        recording = get_object_or_404(
            dm.MeetingRecording, pk=recording_pk, workspace_id__in=ws_ids,
        )
        ext_ids = request.POST.getlist("accept_suggestion")
        created_projects = 0
        created_tasks = 0
        skipped = 0
        for ext_id in ext_ids:
            ext = recording.ai_extractions.filter(
                pk=ext_id, is_accepted=False,
            ).first()
            if not ext:
                continue
            kind = ext.kind
            try:
                if kind == dm.RecordingAIExtraction.Kind.PROJECT_SUGGESTION:
                    proj = dm.Project.objects.create(
                        workspace=recording.workspace,
                        name=ext.title[:200],
                        description=ext.description or "",
                        status=getattr(dm.Project, "Status", None) and
                               dm.Project.Status.PLANNED or "PLANNED",
                    )
                    ext.is_accepted = True
                    ext.accepted_at = timezone.now()
                    ext.save(update_fields=["is_accepted", "accepted_at", "updated_at"])
                    created_projects += 1

                elif kind == dm.RecordingAIExtraction.Kind.TASK_SUGGESTION:
                    # PR-MEET-AI-ENRICH : créer une vraie Task à partir d'une suggestion IA
                    # Heuristique projet parent : meeting.project > meeting.projects.first()
                    parent_project = recording.meeting.project
                    if parent_project is None:
                        parent_project = recording.meeting.projects.first()
                    if parent_project is None:
                        # Pas de projet rattaché → on marque accepté mais on demande
                        # création manuelle (Task.project est obligatoire).
                        ext.is_accepted = True
                        ext.accepted_at = timezone.now()
                        ext.save(update_fields=[
                            "is_accepted", "accepted_at", "updated_at",
                        ])
                        skipped += 1
                        continue

                    # Mapping priorité hint → choix Task
                    priority_map = {
                        "low": "LOW", "medium": "MEDIUM",
                        "high": "HIGH", "critical": "CRITICAL",
                    }
                    priority = priority_map.get(
                        (ext.priority_hint or "").lower(), "MEDIUM",
                    )

                    # Recherche d'un assignee à partir du hint
                    assignee = None
                    if ext.assignee_hint:
                        from project.utils.workspaces import users_in_workspaces
                        hint = ext.assignee_hint.strip().lower()
                        qs = users_in_workspaces([recording.workspace_id])
                        # Match par username/first_name/last_name/full_name
                        from django.db.models import Q
                        assignee = qs.filter(
                            Q(username__icontains=hint)
                            | Q(first_name__icontains=hint)
                            | Q(last_name__icontains=hint)
                            | Q(email__icontains=hint)
                        ).first()

                    # Création
                    task_kwargs = {
                        "workspace": recording.workspace,
                        "project": parent_project,
                        "title": ext.title[:200],
                        "description": ext.description or "",
                        "priority": priority,
                        "assignee": assignee,
                        "created_by": request.user,
                    }
                    # Sprint éventuel (du meeting)
                    if recording.meeting.sprint_id:
                        task_kwargs["sprint"] = recording.meeting.sprint
                    try:
                        new_task = dm.Task.objects.create(**task_kwargs)
                    except Exception as exc:
                        logger.warning("Task creation from extraction %s failed: %s", ext_id, exc)
                        # Fallback : on essaie sans assignee si le champ n'existe pas
                        task_kwargs.pop("assignee", None)
                        new_task = dm.Task.objects.create(**task_kwargs)
                    ext.is_accepted = True
                    ext.accepted_at = timezone.now()
                    ext.save(update_fields=[
                        "is_accepted", "accepted_at", "updated_at",
                    ])
                    created_tasks += 1

                else:
                    # Sprint/Milestone : besoin d'un project parent — on
                    # se contente de marquer accepté et l'utilisateur les
                    # crée à la main pour l'instant (à enrichir)
                    ext.is_accepted = True
                    ext.accepted_at = timezone.now()
                    ext.save(update_fields=["is_accepted", "accepted_at", "updated_at"])
                    skipped += 1
            except Exception as exc:
                logger.warning("convert suggestion %s failed: %s", ext_id, exc)
        if created_projects:
            messages.success(request, f"{created_projects} projet(s) créé(s).")
        if created_tasks:
            messages.success(request, f"{created_tasks} tâche(s) créée(s).")
        if skipped:
            messages.info(request, f"{skipped} suggestion(s) acceptée(s) (création manuelle requise — rattachez un projet à la réunion).")
        return redirect("recording_summary",
                        meeting_pk=recording.meeting_id, recording_pk=recording.pk)


class MeetingSendMinutesView(WorkspaceSecurityMixin, DevflowBaseMixin, View):
    """POST : envoie le compte-rendu .docx par email aux participants."""

    @method_decorator(csrf_protect)
    def post(self, request, pk):
        meeting = self.filter_by_workspace(
            dm.ProjectMeeting.objects.all()
        ).filter(pk=pk).first()
        if meeting is None:
            raise Http404("Réunion introuvable.")
        include_external = request.POST.get("include_external", "1") == "1"
        try:
            from project.tasks import send_meeting_minutes_email_async
            send_meeting_minutes_email_async.delay(meeting.pk, include_external)
            messages.success(
                request, "Envoi du compte-rendu lancé en arrière-plan.",
            )
        except Exception:
            # Fallback synchrone si Celery indispo
            try:
                sent = MeetingService.send_minutes_email(
                    meeting, include_external=include_external,
                )
                messages.success(
                    request, f"Compte-rendu envoyé à {sent} destinataire(s).",
                )
            except Exception as exc:
                logger.exception("send_minutes_email sync failed: %s", exc)
                messages.error(request, f"Envoi échoué : {exc}")
        return redirect("meeting_detail", pk=meeting.pk)


# ─────────────────────────────────────────────────────────────────────
# PR-MEET-RSVP : Endpoints RSVP + Présence
# ─────────────────────────────────────────────────────────────────────
class _ParticipationMixin(WorkspaceSecurityMixin, DevflowBaseMixin):
    """Helpers communs aux vues RSVP / Attendance."""

    def _get_meeting(self, request, meeting_pk):
        from django.http import Http404
        ws_ids = get_user_workspace_ids(request.user)
        meeting = (
            dm.ProjectMeeting.objects
            .filter(pk=meeting_pk, workspace_id__in=ws_ids)
            .first()
        )
        if meeting is None:
            raise Http404("Réunion introuvable.")
        return meeting

    def _user_is_meeting_admin(self, user, meeting) -> bool:
        """L'utilisateur peut-il modifier la présence des autres ?"""
        if user.is_superuser:
            return True
        if meeting.organizer_id == user.pk:
            return True
        if meeting.created_by_id == user.pk:
            return True
        # On peut aussi vérifier le rôle RBAC du workspace
        try:
            from project.services.rbac import RBACService
            return RBACService.can(
                user, "meeting.manage", target=meeting,
                workspace=meeting.workspace,
            )
        except Exception:
            return False


class MeetingRSVPView(_ParticipationMixin, View):
    """POST /meetings/<pk>/rsvp/ — un participant met à jour SA réponse RSVP."""

    @method_decorator(csrf_protect)
    def post(self, request, meeting_pk):
        meeting = self._get_meeting(request, meeting_pk)
        # Le user doit être dans les participants invités
        participation = (
            dm.MeetingParticipation.objects
            .filter(meeting=meeting, user=request.user)
            .first()
        )
        if participation is None:
            # Auto-création si l'user est invité mais sans row (cas legacy)
            if meeting.internal_participants.filter(pk=request.user.pk).exists():
                participation = dm.MeetingParticipation.objects.create(
                    meeting=meeting, user=request.user,
                )
            else:
                messages.error(request, "Vous n'êtes pas invité à cette réunion.")
                return redirect("meeting_detail", pk=meeting.pk)

        new_status = (request.POST.get("rsvp_status") or "").strip().upper()
        valid = {c[0] for c in dm.MeetingParticipation.RSVPStatus.choices}
        if new_status not in valid:
            messages.error(request, "Statut RSVP invalide.")
            return redirect("meeting_detail", pk=meeting.pk)

        participation.rsvp_status = new_status
        participation.rsvp_at = timezone.now()
        note = (request.POST.get("rsvp_note") or "").strip()[:300]
        if note:
            participation.rsvp_note = note
        participation.save(update_fields=[
            "rsvp_status", "rsvp_at", "rsvp_note", "updated_at",
        ])
        messages.success(
            request,
            f"Réponse enregistrée : {participation.get_rsvp_status_display()}.",
        )
        return redirect("meeting_detail", pk=meeting.pk)


class MeetingSelfPresentView(_ParticipationMixin, View):
    """POST /meetings/<pk>/confirm-presence/ — un participant confirme sa présence."""

    @method_decorator(csrf_protect)
    def post(self, request, meeting_pk):
        meeting = self._get_meeting(request, meeting_pk)
        participation = (
            dm.MeetingParticipation.objects
            .filter(meeting=meeting, user=request.user)
            .first()
        )
        if participation is None:
            messages.error(request, "Vous n'êtes pas invité à cette réunion.")
            return redirect("meeting_detail", pk=meeting.pk)
        participation.attendance_status = dm.MeetingParticipation.AttendanceStatus.PRESENT
        participation.self_confirmed = True
        participation.attendance_marked_at = timezone.now()
        participation.save(update_fields=[
            "attendance_status", "self_confirmed",
            "attendance_marked_at", "updated_at",
        ])
        messages.success(request, "Votre présence est confirmée.")
        return redirect("meeting_detail", pk=meeting.pk)


# ─────────────────────────────────────────────────────────────────────
# PR-MEET-AGENDA-LIVE : CRUD ordre du jour structuré
# ─────────────────────────────────────────────────────────────────────
class _AgendaMixin(WorkspaceSecurityMixin, DevflowBaseMixin):
    """Helpers communs aux vues CRUD agenda."""

    def _get_meeting(self, request, meeting_pk):
        from django.http import Http404
        ws_ids = get_user_workspace_ids(request.user)
        meeting = (
            dm.ProjectMeeting.objects
            .filter(pk=meeting_pk, workspace_id__in=ws_ids)
            .first()
        )
        if meeting is None:
            raise Http404("Réunion introuvable.")
        return meeting

    def _get_item(self, request, meeting_pk, item_pk):
        from django.http import Http404
        meeting = self._get_meeting(request, meeting_pk)
        item = meeting.agenda_items.filter(pk=item_pk).first()
        if item is None:
            raise Http404("Point d'ordre du jour introuvable.")
        return meeting, item


class MeetingAgendaItemCreateView(_AgendaMixin, View):
    """POST /meetings/<pk>/agenda/create/ — ajoute un nouveau point."""

    @method_decorator(csrf_protect)
    def post(self, request, meeting_pk):
        meeting = self._get_meeting(request, meeting_pk)
        title = (request.POST.get("title") or "").strip()
        if not title:
            messages.error(request, "Le titre du point est obligatoire.")
            return redirect("meeting_detail", pk=meeting.pk)

        # Position = max + 1
        last_pos = (
            meeting.agenda_items
            .order_by("-position")
            .values_list("position", flat=True)
            .first()
            or 0
        )

        owner = None
        owner_id = request.POST.get("owner") or ""
        if owner_id.isdigit():
            from project.utils.workspaces import users_in_workspaces
            owner = users_in_workspaces([meeting.workspace_id]).filter(pk=owner_id).first()

        try:
            duration = max(0, int(request.POST.get("duration_minutes") or 5))
        except (ValueError, TypeError):
            duration = 5

        dm.MeetingAgendaItem.objects.create(
            meeting=meeting,
            title=title[:200],
            description=(request.POST.get("description") or "").strip(),
            owner=owner,
            duration_minutes=duration,
            position=last_pos + 1,
            created_by=request.user,
        )
        messages.success(request, "Point ajouté à l'ordre du jour.")
        return redirect("meeting_detail", pk=meeting.pk)


class MeetingAgendaItemUpdateView(_AgendaMixin, View):
    """POST /meetings/<pk>/agenda/<item_pk>/update/ — édite titre/description/owner/durée."""

    @method_decorator(csrf_protect)
    def post(self, request, meeting_pk, item_pk):
        meeting, item = self._get_item(request, meeting_pk, item_pk)

        changed = []
        title = (request.POST.get("title") or "").strip()
        if title and title != item.title:
            item.title = title[:200]
            changed.append("title")
        if "description" in request.POST:
            item.description = (request.POST.get("description") or "").strip()
            changed.append("description")
        if "owner" in request.POST:
            owner_id = (request.POST.get("owner") or "").strip()
            if owner_id == "":
                item.owner = None
                changed.append("owner")
            elif owner_id.isdigit():
                from project.utils.workspaces import users_in_workspaces
                new_owner = users_in_workspaces([meeting.workspace_id]).filter(pk=owner_id).first()
                if new_owner:
                    item.owner = new_owner
                    changed.append("owner")
        if "duration_minutes" in request.POST:
            try:
                item.duration_minutes = max(0, int(request.POST.get("duration_minutes") or 0))
                changed.append("duration_minutes")
            except (ValueError, TypeError):
                pass
        if "notes" in request.POST:
            item.notes = (request.POST.get("notes") or "").strip()
            changed.append("notes")
        if "status" in request.POST:
            new_status = (request.POST.get("status") or "").strip().upper()
            valid = {c[0] for c in dm.MeetingAgendaItem.Status.choices}
            if new_status in valid and new_status != item.status:
                # Marque les dates de transition
                if (new_status == dm.MeetingAgendaItem.Status.IN_PROGRESS
                        and not item.started_at):
                    item.started_at = timezone.now()
                    changed.append("started_at")
                if (new_status == dm.MeetingAgendaItem.Status.DONE
                        and not item.completed_at):
                    item.completed_at = timezone.now()
                    changed.append("completed_at")
                item.status = new_status
                changed.append("status")

        if changed:
            changed.append("updated_at")
            item.save(update_fields=changed)
            messages.success(request, "Point mis à jour.")
        else:
            messages.info(request, "Aucune modification.")
        return redirect("meeting_detail", pk=meeting.pk)


class MeetingAgendaItemDeleteView(_AgendaMixin, View):
    """POST /meetings/<pk>/agenda/<item_pk>/delete/."""

    @method_decorator(csrf_protect)
    def post(self, request, meeting_pk, item_pk):
        meeting, item = self._get_item(request, meeting_pk, item_pk)
        item.delete()
        messages.success(request, "Point supprimé.")
        return redirect("meeting_detail", pk=meeting.pk)


class MeetingAgendaReorderView(_AgendaMixin, View):
    """
    POST /meetings/<pk>/agenda/reorder/ — réordonne après drag-drop.

    Format du POST : `order=<id1>,<id2>,<id3>...` (positions 1, 2, 3, ...)
    Retourne JSON.
    """

    @method_decorator(csrf_protect)
    def post(self, request, meeting_pk):
        meeting = self._get_meeting(request, meeting_pk)
        raw = (request.POST.get("order") or "").strip()
        if not raw:
            return JsonResponse({"ok": False, "error": "empty"}, status=400)
        try:
            ids = [int(p) for p in raw.split(",") if p.strip().isdigit()]
        except (ValueError, TypeError):
            return JsonResponse({"ok": False, "error": "bad_format"}, status=400)

        # Filtre aux items qui appartiennent VRAIMENT à ce meeting
        items = {
            i.pk: i for i in meeting.agenda_items.filter(pk__in=ids)
        }
        position = 1
        updated = 0
        for pk in ids:
            item = items.get(pk)
            if item and item.position != position:
                item.position = position
                item.save(update_fields=["position", "updated_at"])
                updated += 1
            position += 1
        return JsonResponse({"ok": True, "updated": updated})


class MeetingMarkAttendanceView(_ParticipationMixin, View):
    """
    POST /meetings/<pk>/attendance/ — l'organisateur marque la présence des participants.

    Format du POST :
      attendance_<user_id> = PRESENT | ABSENT | LATE | LEFT_EARLY | UNKNOWN

    Toute autre clé est ignorée. Les user_id non listés sont laissés inchangés.
    """

    @method_decorator(csrf_protect)
    def post(self, request, meeting_pk):
        meeting = self._get_meeting(request, meeting_pk)
        if not self._user_is_meeting_admin(request.user, meeting):
            messages.error(
                request,
                "Seul l'organisateur ou un administrateur peut modifier la "
                "présence des participants.",
            )
            return redirect("meeting_detail", pk=meeting.pk)

        valid = {c[0] for c in dm.MeetingParticipation.AttendanceStatus.choices}
        now = timezone.now()
        participations = {
            p.user_id: p for p in meeting.participations.all()
        }
        updated = 0
        for key, value in request.POST.items():
            if not key.startswith("attendance_"):
                continue
            try:
                user_id = int(key.removeprefix("attendance_"))
            except (ValueError, TypeError):
                continue
            value = (value or "").strip().upper()
            if value not in valid:
                continue
            p = participations.get(user_id)
            if p is None:
                continue
            if p.attendance_status != value:
                p.attendance_status = value
                p.attendance_marked_by = request.user
                p.attendance_marked_at = now
                p.save(update_fields=[
                    "attendance_status", "attendance_marked_by",
                    "attendance_marked_at", "updated_at",
                ])
                updated += 1
        if updated:
            messages.success(
                request, f"Présence mise à jour pour {updated} participant(s).",
            )
        else:
            messages.info(request, "Aucune modification.")
        return redirect("meeting_detail", pk=meeting.pk)
