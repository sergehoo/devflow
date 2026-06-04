"""
Vues du module Réunions DevFlow.
Architecture alignée sur les vues génériques DevFlow.
"""

from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
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
