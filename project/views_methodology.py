"""
DevFlow — Vues du moteur multi-méthodologies (PR5-PR8 + PR18 Copilote).

  * ProjectMethodologyDashboardView — dashboard dynamique adaptatif aux KPIs
  * ProjectScrumWorkspaceView — workspace Scrum (Backlog + Sprint + Burndown)
  * ProjectKanbanWorkspaceView — workspace Kanban (WIP + Cycle/Lead time)
  * ProjectWaterfallWorkspaceView — workspace Waterfall (Phases + Gantt)
  * ProjectCopilotAPIView — endpoint API JSON pour le copilote IA

Toutes les vues filtrent par workspace (sécurité multi-tenant).
"""

from __future__ import annotations

import json
import logging
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from project import models as dm
from project.utils.workspaces import get_user_workspace_ids
from project.views import DevflowBaseMixin, WorkspaceSecurityMixin

logger = logging.getLogger(__name__)


def _resolve_methodology(project):
    """
    Retourne le ``Methodology`` lié au projet.

    Mappe ``Project.methodology`` (CharField legacy) → ``Methodology.code``.
    Retourne None si aucun match (projets historiques sans méthodologie typée).
    """
    code = (getattr(project, "methodology", None) or "").lower()
    if not code:
        return None
    return dm.Methodology.objects.filter(code=code).first()


class ProjectMethodologyDashboardView(WorkspaceSecurityMixin, DevflowBaseMixin, View):
    """Dashboard dynamique adaptatif à la méthodologie du projet."""
    template_name = "project/methodology/dashboard.html"

    def get(self, request, pk):
        ws_ids = get_user_workspace_ids(request.user)
        project = get_object_or_404(
            dm.Project.objects.select_related("workspace"),
            pk=pk, workspace_id__in=ws_ids,
        )
        methodology = _resolve_methodology(project)

        from project.services.methodology.kpis import compute_kpi
        computed_kpis = []
        if methodology:
            for kpi in methodology.kpis.order_by("-is_pinned", "position"):
                result = compute_kpi(project, kpi.compute_strategy)
                computed_kpis.append({
                    "kpi": kpi,
                    "result": result,
                })

        return render(request, self.template_name, {
            "project": project,
            "methodology": methodology,
            "computed_kpis": computed_kpis,
            "section": "project",
            "page_title": f"Dashboard {methodology.name if methodology else ''}".strip(),
            "breadcrumb": f"Projets · {project.name} · Dashboard",
        })


class ProjectScrumWorkspaceView(WorkspaceSecurityMixin, DevflowBaseMixin, View):
    """Workspace Scrum : Backlog + Sprint actif + Burndown + Velocity + Retro."""
    template_name = "project/methodology/scrum_workspace.html"

    def get(self, request, pk):
        ws_ids = get_user_workspace_ids(request.user)
        project = get_object_or_404(
            dm.Project.objects.select_related("workspace"),
            pk=pk, workspace_id__in=ws_ids,
        )
        methodology = _resolve_methodology(project)

        # Sprint actif (priorité PLANNED puis ACTIVE)
        active_sprint = (
            project.sprints
            .filter(status__in=["ACTIVE", "PLANNED"])
            .order_by("status", "-start_date")
            .first()
        )
        backlog_items = (
            project.backlog_items
            .exclude(status__in=["DONE", "CLOSED", "CANCELLED"])
            .order_by("rank", "-created_at")[:50]
        )
        sprint_items = []
        if active_sprint:
            sprint_items = list(
                active_sprint.tasks.select_related("assignee").order_by("priority")
                if hasattr(active_sprint, "tasks")
                else []
            )

        # KPIs Scrum critiques
        from project.services.methodology.kpis import compute_kpi
        velocity = compute_kpi(project, "velocity")
        burndown = compute_kpi(project, "burndown_sprint")
        success_rate = compute_kpi(project, "sprint_success_rate")

        return render(request, self.template_name, {
            "project": project,
            "methodology": methodology,
            "active_sprint": active_sprint,
            "backlog_items": backlog_items,
            "sprint_items": sprint_items,
            "kpi_velocity": velocity,
            "kpi_burndown": burndown,
            "kpi_success_rate": success_rate,
            "all_sprints": project.sprints.order_by("-number")[:5],
            "section": "project",
            "page_title": f"Scrum · {project.name}",
            "breadcrumb": f"Projets · {project.name} · Scrum",
        })


class ProjectKanbanWorkspaceView(WorkspaceSecurityMixin, DevflowBaseMixin, View):
    """Workspace Kanban : Board + WIP limits + Cycle/Lead time + Throughput."""
    template_name = "project/methodology/kanban_workspace.html"

    def get(self, request, pk):
        ws_ids = get_user_workspace_ids(request.user)
        project = get_object_or_404(
            dm.Project.objects.select_related("workspace"),
            pk=pk, workspace_id__in=ws_ids,
        )
        methodology = _resolve_methodology(project)

        # Construit les colonnes depuis MethodologyStatus
        columns = []
        if methodology:
            for status in methodology.statuses.order_by("position"):
                status_code = status.code.upper()
                tasks = project.tasks.filter(status=status_code)
                columns.append({
                    "status": status,
                    "tasks": list(tasks.select_related("assignee")[:30]),
                    "count": tasks.count(),
                    "over_wip": (
                        status.wip_limit is not None
                        and tasks.count() > status.wip_limit
                    ),
                })

        # KPIs Kanban
        from project.services.methodology.kpis import compute_kpi
        wip = compute_kpi(project, "wip_count")
        cycle_t = compute_kpi(project, "cycle_time")
        lead_t = compute_kpi(project, "lead_time")
        throughput = compute_kpi(project, "throughput_weekly")
        cfd = compute_kpi(project, "cumulative_flow")

        return render(request, self.template_name, {
            "project": project,
            "methodology": methodology,
            "columns": columns,
            "kpi_wip": wip, "kpi_cycle_time": cycle_t,
            "kpi_lead_time": lead_t, "kpi_throughput": throughput,
            "kpi_cfd": cfd,
            "section": "project",
            "page_title": f"Kanban · {project.name}",
            "breadcrumb": f"Projets · {project.name} · Kanban",
        })


class ProjectWaterfallWorkspaceView(WorkspaceSecurityMixin, DevflowBaseMixin, View):
    """Workspace Waterfall : Phases + Gantt + Chemin critique + % avancement."""
    template_name = "project/methodology/waterfall_workspace.html"

    def get(self, request, pk):
        ws_ids = get_user_workspace_ids(request.user)
        project = get_object_or_404(
            dm.Project.objects.select_related("workspace"),
            pk=pk, workspace_id__in=ws_ids,
        )
        methodology = _resolve_methodology(project)

        phases = (
            project.phases.select_related("owner").order_by("position", "id")
            if hasattr(project, "phases") else []
        )
        milestones = (
            project.milestones.order_by("due_date")[:10]
            if hasattr(project, "milestones") else []
        )

        from project.services.methodology.kpis import compute_kpi
        advancement = compute_kpi(project, "advancement_global")
        schedule = compute_kpi(project, "schedule_adherence")
        budget = compute_kpi(project, "budget_consumption")
        critical = compute_kpi(project, "critical_path_length")
        gantt = compute_kpi(project, "gantt_data")

        return render(request, self.template_name, {
            "project": project,
            "methodology": methodology,
            "phases": phases,
            "milestones": milestones,
            "kpi_advancement": advancement,
            "kpi_schedule": schedule,
            "kpi_budget": budget,
            "kpi_critical_path": critical,
            "kpi_gantt": gantt,
            "section": "project",
            "page_title": f"Waterfall · {project.name}",
            "breadcrumb": f"Projets · {project.name} · Waterfall",
        })


class ProjectCopilotAPIView(WorkspaceSecurityMixin, DevflowBaseMixin, View):
    """
    Endpoint API JSON pour le copilote IA projet (PR18-METHODO).

    POST /projects/<pk>/copilot/chat/
    Body : { "message": "...", "history": [{"role": "user|assistant", "content": "..."}] }

    Réponse : { "type": "reply|tool_result|tool_error|error",
                "message": "...",
                "actions_executed": [...] }
    """

    @method_decorator(csrf_protect)
    def post(self, request, pk):
        ws_ids = get_user_workspace_ids(request.user)
        project = get_object_or_404(
            dm.Project.objects.select_related("workspace"),
            pk=pk, workspace_id__in=ws_ids,
        )

        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except Exception:
            payload = {}

        message = (payload.get("message") or "").strip()
        if not message:
            return JsonResponse({"error": "Message vide."}, status=400)
        history_raw = payload.get("history") or []
        history = [
            (h.get("role"), h.get("content"))
            for h in history_raw if isinstance(h, dict)
        ][-10:]

        from project.services.methodology.copilot import chat
        result = chat(project, request.user, message, history=history)
        return JsonResponse(result, status=200)


class ProjectCopilotLogView(WorkspaceSecurityMixin, DevflowBaseMixin, View):
    """
    GET /projects/<pk>/copilot/logs/ — liste des dernières actions IA.

    Permet l'audit utilisateur des actions exécutées par le copilote.
    """
    template_name = "project/methodology/copilot_logs.html"

    def get(self, request, pk):
        ws_ids = get_user_workspace_ids(request.user)
        project = get_object_or_404(
            dm.Project.objects.select_related("workspace"),
            pk=pk, workspace_id__in=ws_ids,
        )
        logs = (
            project.ai_action_logs
            .select_related("user")
            .order_by("-created_at")[:50]
        )
        return render(request, self.template_name, {
            "project": project,
            "logs": logs,
            "section": "project",
            "page_title": "Journal d'actions IA",
            "breadcrumb": f"Projets · {project.name} · Audit IA",
        })
