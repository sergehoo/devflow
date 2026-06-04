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
        qs = (
            super().get_queryset()
            .select_related("project", "organizer", "sprint", "workspace")
            .prefetch_related("internal_participants")
            .order_by("-scheduled_at")
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
        if skipped:
            messages.info(request, f"{skipped} suggestion(s) acceptée(s) (création manuelle requise).")
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
