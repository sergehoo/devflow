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
            .select_related("project", "sprint", "organizer", "created_by", "updated_by")
            .prefetch_related("internal_participants", "action_items__owner", "attachments")
        )


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
        meeting = get_object_or_404(dm.ProjectMeeting, pk=meeting_pk)
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
        item = get_object_or_404(
            dm.MeetingActionItem.objects.select_related("meeting", "meeting__project", "owner"),
            pk=item_pk,
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
        meeting = get_object_or_404(dm.ProjectMeeting, pk=meeting_pk)
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
