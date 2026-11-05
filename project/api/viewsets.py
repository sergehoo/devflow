"""
DevFlow REST API — ViewSets.

Tous les viewsets exposent CRUD + actions IA financières (forecast,
risk-analysis, allocation-advice).

SECURITY (Phase 0) :
  * Tous les viewsets héritent de ``WorkspaceScopedViewSetMixin`` qui
    filtre le queryset aux workspaces du user connecté.
  * Tous déclarent ``permission_classes = [IsAuthenticated, IsWorkspaceMember]``
    pour la défense en profondeur object-level.
  * Les actions IA payantes (forecast, risk-analysis, allocation-advice,
    effort-estimate) ont un ``throttle_classes = [AIActionRateThrottle]``
    pour éviter le spam OpenAI à coût caché.
"""

from __future__ import annotations

from django.db.models import Count, Q
from rest_framework import permissions, viewsets
from project.api.pagination import FlexiblePagination
from rest_framework.decorators import action
from rest_framework.response import Response

from project import models as dm
from project.api.permissions import IsWorkspaceMember, WorkspaceScopedViewSetMixin
from project.services.rbac import HasRBACPermission
from project.api.serializers import (
    AdminCaseSerializer,
    AInsightSerializer,
    BillingRateSerializer,
    BudgetAlertSerializer,
    BudgetOverviewSerializer,
    FieldReportSerializer,
    ProjectAIReportSerializer,
    ProjectBudgetForecastRunSerializer,
    ProjectBudgetSerializer,
    ProjectBudgetSnapshotSerializer,
    ProjectEstimateLineSerializer,
    ProjectExpenseSerializer,
    ProjectMemberSerializer,
    ProjectPhaseSerializer,
    ProjectRevenueSerializer,
    ProjectSerializer,
    ProjectViewPreferenceSerializer,
    RealEstateLotSerializer,
    SprintSerializer,
    TaskSerializer,
    TeamSerializer,
    TimesheetEntrySerializer,
    WorkspaceSerializer,
)
from project.api.throttles import AIActionRateThrottle
from project.services.budget_snapshots import (
    BudgetAlertService,
    BudgetSnapshotService,
)
from project.services.ai.services.allocation_advice import AllocationAdviceService
from project.services.ai.services.budget_forecast import BudgetForecastService
from project.services.ai.services.effort_estimation import EffortEstimationService
from project.services.ai.services.project_intelligence import (
    ProjectRecommendationsService,
    ProjectRoadmapGenerationService,
    ProjectSummaryService,
)
from project.services.ai.services.project_report import ProjectAIReportService
from project.services.ai.services.risk_analysis import RiskAnalysisService
from project.services.budget import ProjectBudgetService


# Permission stack standard pour tous les viewsets (sauf surcharge explicite).
from project.api.mixins import RBACUpdateArchiveMixin  # noqa: E402
from project.api import guards  # noqa: E402

DEFAULT_PERMISSIONS = [permissions.IsAuthenticated, IsWorkspaceMember]
# PR25 — Permissions enrichies RBAC pour viewsets sensibles
RBAC_PERMISSIONS = [permissions.IsAuthenticated, IsWorkspaceMember, HasRBACPermission]


class WorkspaceViewSet(RBACUpdateArchiveMixin, WorkspaceScopedViewSetMixin, viewsets.ModelViewSet):
    """Mêmes règles que les vues Django : modification/archivage ``workspace.manage``,
    suppression ``workspace.delete`` (perform_destroy du mixin)."""

    queryset = dm.Workspace.objects.select_related("owner").order_by("name")
    serializer_class = WorkspaceSerializer
    permission_classes = DEFAULT_PERMISSIONS
    search_fields = ["name", "slug", "description", "quarter_label"]
    update_rbac_action = "workspace.manage"
    archive_rbac_action = "workspace.manage"

    def get_queryset(self):
        qs = super().get_queryset().annotate(
            teams_count=Count("teams", distinct=True),
            projects_count=Count("projects", distinct=True),
            memberships_count=Count("memberships", distinct=True),
        )
        # Compatibilité : les workspaces archivés restent masqués sauf demande explicite.
        if self.action == "list" and self.request.query_params.get("include_archived") != "1":
            qs = qs.filter(is_archived=False)
        return qs

    def perform_create(self, serializer):
        # SECURITY (phase 5) : on ne crée pas un workspace au nom d'un tiers.
        owner = serializer.validated_data.get("owner")
        if owner and owner != self.request.user and not self.request.user.is_superuser:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"owner": "Vous ne pouvez créer un workspace qu'en votre nom."})
        serializer.save(owner=owner or self.request.user)

    def perform_update(self, serializer):
        # SECURITY (phase 5) : le propriétaire ne peut être transmis qu'à un membre du workspace.
        owner = serializer.validated_data.get("owner")
        if owner and owner.pk != serializer.instance.owner_id:
            self._check_new_owner(serializer.instance, owner)
        super().perform_update(serializer)

    @staticmethod
    def _check_new_owner(workspace, user):
        from rest_framework.exceptions import ValidationError
        from project.utils.workspaces import users_in_workspaces

        if not users_in_workspaces([workspace.pk]).filter(pk=user.pk, is_active=True).exists():
            raise ValidationError({"owner": "Le nouveau propriétaire doit être un membre actif du workspace."})

    @action(detail=True, methods=["get"], url_path="members")
    def members(self, request, pk=None):
        """Membres actifs (candidats au transfert de propriété)."""
        from project.utils.workspaces import users_in_workspaces

        ws = self.get_object()
        users = users_in_workspaces([ws.pk]).filter(is_active=True).order_by("first_name", "last_name", "username")
        return Response([
            {"id": u.pk, "name": u.get_full_name() or u.get_username(), "email": u.email, "is_owner": u.pk == ws.owner_id}
            for u in users
        ])

    @action(detail=True, methods=["post"], url_path="transfer-ownership")
    def transfer_ownership(self, request, pk=None):
        """Transfert de propriété : même droit que la modification (``workspace.manage``)."""
        from rest_framework.exceptions import PermissionDenied, ValidationError
        from project.services.rbac import RBACService

        ws = self.get_object()
        if not RBACService.can(request.user, "workspace.manage", target=ws):
            raise PermissionDenied("Transfert réservé aux administrateurs du workspace.")
        from django.contrib.auth import get_user_model
        from project.services.security_audit import SecurityAuditService

        new_owner = get_user_model().objects.filter(pk=request.data.get("user_id") or 0).first()
        if new_owner is None:
            raise ValidationError({"user_id": "Utilisateur introuvable."})
        self._check_new_owner(ws, new_owner)
        previous_id = ws.owner_id
        ws.owner = new_owner
        ws.save(update_fields=["owner", "updated_at"])
        SecurityAuditService.log(
            event_type=dm.SecurityAuditLog.EventType.PERMISSION_CHANGE, action="workspace.transfer_ownership",
            user=request.user, workspace=ws, target=ws, request=request,
            severity=dm.SecurityAuditLog.Severity.WARNING,
            metadata={"previous_owner_id": previous_id, "new_owner_id": new_owner.pk},
        )
        return Response({"owner": new_owner.pk, "owner_name": new_owner.get_full_name() or new_owner.get_username()})

    @action(detail=True, methods=["get"], url_path="overview")
    def overview(self, request, pk=None):
        """Contenu de la fiche Django : 10 équipes, 10 projets, 10 membres."""
        ws = self.get_object()
        teams = ws.teams.filter(is_archived=False).order_by("name")[:10]
        projects = ws.projects.filter(is_archived=False).select_related("team").order_by("name")[:10]
        profiles = ws.user_profiles.select_related("user").order_by("user__username")[:10]
        return Response({
            "teams": [{"id": t.pk, "name": t.name, "team_type": t.get_team_type_display()} for t in teams],
            "projects": [
                {"id": p.pk, "name": p.name, "status_label": p.get_status_display(),
                 "progress_percent": p.progress_percent, "team": p.team.name if p.team_id else ""}
                for p in projects
            ],
            "members": [
                {"id": pr.user_id, "name": pr.user.get_full_name() or pr.user.get_username(),
                 "email": pr.user.email, "job_title": pr.job_title or ""}
                for pr in profiles
            ],
        })

    @action(detail=True, methods=["get"], url_path="portfolio")
    def portfolio(self, request, pk=None):
        workspace = self.get_object()
        projects = workspace.projects.filter(is_archived=False)
        return Response(ProjectBudgetService.build_portfolio_overview(projects))

    @action(
        detail=True,
        methods=["get"],
        url_path="allocation-advice",
        throttle_classes=[AIActionRateThrottle],
    )
    def allocation_advice(self, request, pk=None):
        workspace = self.get_object()
        advice = AllocationAdviceService.advise(workspace, use_ai=True)
        return Response(advice.to_dict())

    # ─── Phase 3 (PR15) — Alertes budget portfolio ──────────────────────
    @action(detail=True, methods=["get"], url_path="budget-alerts")
    def budget_alerts(self, request, pk=None):
        """Liste les projets en alerte budget pour ce workspace."""
        workspace = self.get_object()
        alerts = BudgetAlertService.for_workspace(workspace, only_active=True)
        return Response({
            "workspace_id": workspace.pk,
            "alert_count": len(alerts),
            "alerts": [BudgetAlertSerializer(a.to_dict()).data for a in alerts],
        })


class TeamViewSet(WorkspaceScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = dm.Team.objects.select_related("lead").order_by("name")
    serializer_class = TeamSerializer
    permission_classes = DEFAULT_PERMISSIONS
    filterset_fields = ["workspace", "team_type", "is_active", "is_archived"]
    search_fields = ["name", "description"]

    def get_queryset(self):
        return super().get_queryset().annotate(
            members_count=Count("memberships", distinct=True),
            projects_count=Count("projects", filter=Q(projects__is_archived=False), distinct=True),
        )

    @action(detail=True, methods=["get"], url_path="overview")
    def overview(self, request, pk=None):
        """Membres et projets de l'équipe (fiche React)."""
        team = self.get_object()
        members = team.memberships.select_related("user").order_by("user__first_name", "user__username")
        projects = dm.Project.objects.filter(Q(team=team) | Q(teams=team), is_archived=False).distinct().order_by("name")
        return Response({
            "members": [
                {"id": m.pk, "user_id": m.user_id, "name": m.user.get_full_name() or m.user.get_username(),
                 "role_label": m.get_role_display(), "status_label": m.get_status_display(),
                 "job_title": m.job_title, "current_load_percent": m.current_load_percent}
                for m in members
            ],
            "projects": [
                {"id": p.pk, "name": p.name, "status_label": p.get_status_display(), "progress_percent": p.progress_percent}
                for p in projects
            ],
        })


class ProjectViewSet(RBACUpdateArchiveMixin, WorkspaceScopedViewSetMixin, viewsets.ModelViewSet):
    # Archivage : même règle que ProjectArchiveView (membre du workspace, pas de RBAC dédié).
    queryset = (
        dm.Project.objects
        .select_related("workspace", "team", "owner", "product_manager")
        .filter(is_archived=False)
    )
    serializer_class = ProjectSerializer
    permission_classes = DEFAULT_PERMISSIONS
    filterset_fields = ["workspace", "status", "priority", "owner", "health_status", "team", "methodology"]
    search_fields = ["name", "code", "description", "tech_stack"]
    ordering_fields = ["name", "start_date", "target_date", "created_at", "updated_at", "progress_percent", "priority", "status"]

    @action(detail=True, methods=["get"], url_path="summary")
    def summary(self, request, pk=None):
        """Synthèse de la fiche projet (tâches, heures, membres) pour React."""
        from django.db.models import Count, Q, Sum
        from django.utils import timezone

        project = self.get_object()
        tasks = project.tasks.filter(is_archived=False)
        open_q = ~Q(status__in=[dm.Task.Status.DONE, dm.Task.Status.CANCELLED])
        agg = tasks.aggregate(
            total=Count("id"),
            overdue=Count("id", filter=open_q & Q(due_date__lt=timezone.localdate())),
            estimate=Sum("estimate_hours"),
            spent=Sum("spent_hours"),
        )
        by_status = {row["status"]: row["n"] for row in tasks.values("status").annotate(n=Count("id"))}
        members = project.members.select_related("user", "team").order_by("user__first_name", "user__username")
        return Response({
            "tasks_total": agg["total"],
            "tasks_overdue": agg["overdue"],
            "estimate_hours": float(agg["estimate"] or 0),
            "spent_hours": float(agg["spent"] or 0),
            "tasks_by_status": [
                {"status": value, "label": label, "count": by_status.get(value, 0)}
                for value, label in dm.Task.Status.choices
            ],
            "members": [
                {
                    "id": m.pk, "user_id": m.user_id,
                    "name": m.user.get_full_name() or m.user.get_username(),
                    "role": m.role or "", "team": m.team.name if m.team_id else "",
                    "allocation_percent": m.allocation_percent,
                }
                for m in members
            ],
        })

    def _financial_project(self, request):
        """SECURITY (phase 5) : mêmes droits que les vues budget Django (``can_view_financials``)."""
        from rest_framework.exceptions import PermissionDenied
        from project.views_budget import ProjectFinancialPermissionMixin

        project = self.get_object()
        checker = ProjectFinancialPermissionMixin()
        checker.request = request
        if not checker.can_view_financials(project):
            raise PermissionDenied("Accès aux données financières non autorisé.")
        return project

    @action(detail=True, methods=["get"], url_path="budget-overview")
    def budget_overview(self, request, pk=None):
        project = self._financial_project(request)
        overview = ProjectBudgetService.build_budget_overview(project)
        return Response(BudgetOverviewSerializer(overview).data)

    @action(detail=True, methods=["get"], url_path="budget-panel")
    def budget_panel(self, request, pk=None):
        """Onglet Budget React : synthèse + budget validé (id) — droits financiers Django."""
        project = self._financial_project(request)
        overview = ProjectBudgetService.build_budget_overview(project)
        budget = dm.ProjectBudget.objects.filter(project=project).first()
        return Response({
            "overview": BudgetOverviewSerializer(overview).data,
            "budget_id": budget.pk if budget else None,
        })

    @action(detail=True, methods=["get"], url_path="space")
    def space(self, request, pk=None):
        """Espace méthodologie (Scrum / Kanban / Waterfall) : mêmes données que les vues Django."""
        from project.services.methodology_space import build_space

        return Response(build_space(self.get_object()))

    @action(detail=True, methods=["post"], url_path="refresh-financials")
    def refresh_financials(self, request, pk=None):
        project = self._financial_project(request)
        overview = ProjectBudgetService.refresh_project_financials(
            project=project, user=request.user, rebuild_budget=True
        )
        return Response(BudgetOverviewSerializer(overview).data)

    @action(
        detail=True,
        methods=["get", "post"],
        url_path="ai/forecast",
        throttle_classes=[AIActionRateThrottle],
    )
    def ai_forecast(self, request, pk=None):
        project = self.get_object()
        forecast = BudgetForecastService.forecast(project, use_ai=True)
        return Response(forecast.to_dict())

    @action(
        detail=True,
        methods=["post"],
        url_path="ai/risk-analysis",
        throttle_classes=[AIActionRateThrottle],
    )
    def ai_risk_analysis(self, request, pk=None):
        project = self.get_object()
        signals = RiskAnalysisService.analyze(project, persist=True, use_ai=True)
        return Response(
            {
                "project_id": project.pk,
                "ai_risk_label": project.ai_risk_label,
                "risk_score": project.risk_score,
                "signals": [
                    {
                        "code": s.code,
                        "severity": s.severity,
                        "title": s.title,
                        "description": s.description,
                        "score": s.score,
                    }
                    for s in signals
                ],
            }
        )

    # ─── Phase 4 (PR18) — IA V2 : résumé / recommandations / roadmap ───
    @action(
        detail=True,
        methods=["get"],
        url_path="ai/summary",
        throttle_classes=[AIActionRateThrottle],
    )
    def ai_summary(self, request, pk=None):
        """Résumé projet 3 paragraphes (état, risques, recommandations)."""
        project = self.get_object()
        result = ProjectSummaryService.summarize(project, use_ai=True)
        return Response(result.to_dict())

    @action(
        detail=True,
        methods=["get"],
        url_path="ai/recommendations",
        throttle_classes=[AIActionRateThrottle],
    )
    def ai_recommendations(self, request, pk=None):
        """Top 5 recommandations actionnables (CRITICAL/HIGH/MEDIUM/LOW)."""
        project = self.get_object()
        result = ProjectRecommendationsService.recommend(project, use_ai=True)
        return Response(result.to_dict())

    @action(
        detail=True,
        methods=["post"],
        url_path="ai/generate-roadmap",
        throttle_classes=[AIActionRateThrottle],
    )
    def ai_generate_roadmap(self, request, pk=None):
        """
        Déclenche la génération de la structure complète (roadmap, sprints,
        milestones, tasks). Idempotent : si une proposition pending existe,
        on la retourne sans en créer une nouvelle.
        """
        project = self.get_object()
        result = ProjectRoadmapGenerationService.generate(
            project, actor=request.user, use_ai=True,
        )
        return Response(result.to_dict())

    # ─── Phase 5 (PR22) — Rapport IA hebdomadaire à la demande ─────────
    @action(
        detail=True,
        methods=["post"],
        url_path="ai/report/generate",
        throttle_classes=[AIActionRateThrottle],
    )
    def ai_report_generate(self, request, pk=None):
        """
        Génère un rapport IA pour le projet (semaine N-1 par défaut).
        Idempotent : un rapport déjà prêt pour la même période est retourné.
        """
        project = self.get_object()
        data = request.data or {}
        period = (data.get("period") or "WEEKLY").upper()

        valid = {c[0] for c in dm.ProjectAIReport.ReportPeriod.choices}
        if period not in valid:
            return Response(
                {"detail": "period invalide.", "allowed": sorted(valid)},
                status=400,
            )

        result = ProjectAIReportService.generate(
            project, period=period, actor=request.user, use_ai=True,
        )
        return Response(result.to_dict(), status=201)

    # ─── Phase 3 (PR15) — Budget V2 ─────────────────────────────────────
    @action(detail=True, methods=["post"], url_path="budget/snapshot")
    def budget_snapshot(self, request, pk=None):
        """
        Crée un snapshot du budget courant.

        POST body (tous optionnels) :
            {"label": "Baseline V1", "kind": "BASELINE", "notes": "..."}
        """
        project = self.get_object()
        data = request.data or {}
        label = (data.get("label") or "").strip() or None
        kind = (data.get("kind") or "MANUAL").upper()
        notes = (data.get("notes") or "").strip()

        valid_kinds = {c[0] for c in dm.ProjectBudgetSnapshot.SnapshotKind.choices}
        if kind not in valid_kinds:
            return Response(
                {"detail": "kind invalide.", "allowed": sorted(valid_kinds)},
                status=400,
            )

        snapshot = BudgetSnapshotService.capture(
            project, label=label, kind=kind, actor=request.user, notes=notes,
        )
        return Response(
            ProjectBudgetSnapshotSerializer(snapshot).data, status=201,
        )

    @action(detail=True, methods=["get"], url_path="budget/alerts")
    def budget_alerts(self, request, pk=None):
        """
        Retourne l'alerte budget courante pour ce projet (ou null si aucune).
        """
        project = self.get_object()
        alert = BudgetAlertService.for_project(project)
        if alert is None:
            return Response({"project_id": project.pk, "alert": None})
        return Response({
            "project_id": project.pk,
            "alert": BudgetAlertSerializer(alert.to_dict()).data,
        })


class ProjectMemberViewSet(WorkspaceScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = dm.ProjectMember.objects.select_related("user", "project", "team")
    serializer_class = ProjectMemberSerializer
    permission_classes = DEFAULT_PERMISSIONS
    filterset_fields = ["project", "user", "team"]


class BillingRateViewSet(WorkspaceScopedViewSetMixin, viewsets.ModelViewSet):
    """PR25 — TJM = donnée sensible, restreint via rbac_action_map."""
    queryset = dm.BillingRate.objects.select_related("user", "team").order_by("-valid_from")
    serializer_class = BillingRateSerializer
    permission_classes = RBAC_PERMISSIONS
    filterset_fields = ["user", "team", "unit", "is_internal_cost", "is_billable_rate"]
    rbac_action_map = {
        "list": "billing.view", "retrieve": "billing.view",
        "create": "billing.manage", "update": "billing.manage",
        "partial_update": "billing.manage", "destroy": "billing.manage",
    }


class ProjectBudgetViewSet(WorkspaceScopedViewSetMixin, viewsets.ModelViewSet):
    """PR25 — Budget = sensible, lecture seule pour PM."""
    queryset = dm.ProjectBudget.objects.select_related("project")
    serializer_class = ProjectBudgetSerializer
    permission_classes = RBAC_PERMISSIONS
    filterset_fields = ["project", "status"]
    rbac_action_map = {
        "list": "budget.view", "retrieve": "budget.view",
        "create": "budget.edit", "update": "budget.edit",
        "partial_update": "budget.edit", "destroy": "budget.delete",
    }


class ProjectEstimateLineViewSet(WorkspaceScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = dm.ProjectEstimateLine.objects.select_related("project", "category", "task", "sprint")
    serializer_class = ProjectEstimateLineSerializer
    permission_classes = RBAC_PERMISSIONS
    filterset_fields = ["project", "category", "source_type", "budget_stage", "task", "sprint"]
    rbac_action_map = {
        "list": "budget.view", "retrieve": "budget.view",
        "create": "budget.edit", "update": "budget.edit",
        "partial_update": "budget.edit", "destroy": "budget.edit",
    }


class ProjectRevenueViewSet(WorkspaceScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = dm.ProjectRevenue.objects.select_related("project")
    serializer_class = ProjectRevenueSerializer
    permission_classes = RBAC_PERMISSIONS
    filterset_fields = ["project", "revenue_type", "status", "is_received"]
    rbac_action_map = {
        "list": "budget.view", "retrieve": "budget.view",
        "create": "budget.edit", "update": "budget.edit",
        "partial_update": "budget.edit", "destroy": "budget.edit",
    }


class ProjectExpenseViewSet(WorkspaceScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = dm.ProjectExpense.objects.select_related("project", "category", "created_by")
    serializer_class = ProjectExpenseSerializer
    permission_classes = RBAC_PERMISSIONS
    filterset_fields = ["project", "category", "status", "approval_state", "is_labor_cost", "is_direct_cost"]
    search_fields = ["title", "vendor", "reference"]
    rbac_action_map = {
        "list": "budget.view", "retrieve": "budget.view",
        "create": "budget.edit", "update": "budget.edit",
        "partial_update": "budget.edit", "destroy": "budget.delete",
    }

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"], url_path="approve-level1")
    def approve_level1(self, request, pk=None):
        expense = self.get_object()
        expense.approve_level1(request.user)
        return Response(self.get_serializer(expense).data)

    @action(detail=True, methods=["post"], url_path="approve-level2")
    def approve_level2(self, request, pk=None):
        expense = self.get_object()
        expense.approve_level2(request.user)
        return Response(self.get_serializer(expense).data)

    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        expense = self.get_object()
        reason = request.data.get("reason", "") if hasattr(request, "data") else ""
        expense.reject(request.user, reason=reason)
        return Response(self.get_serializer(expense).data)


class SprintViewSet(WorkspaceScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = dm.Sprint.objects.select_related("project", "team")
    serializer_class = SprintSerializer
    permission_classes = DEFAULT_PERMISSIONS
    filterset_fields = ["workspace", "project", "team", "status"]


class TaskViewSet(WorkspaceScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = dm.Task.objects.select_related("project", "sprint", "assignee", "reporter")
    serializer_class = TaskSerializer
    permission_classes = DEFAULT_PERMISSIONS
    pagination_class = FlexiblePagination
    filterset_fields = ["workspace", "project", "sprint", "status", "priority", "assignee", "is_archived", "is_flagged"]
    # Mêmes champs de recherche que TaskListView (interface classique).
    search_fields = [
        "title", "description", "project__name", "sprint__name",
        "assignee__username", "assignee__first_name", "assignee__last_name",
    ]
    ordering_fields = ["due_date", "priority", "status", "created_at", "title", "project__name", "progress_percent"]
    ordering = ["project__name", "position", "-priority", "-created_at"]

    # SECURITY — mêmes règles métier que l'interface Django (voir project/api/guards.py).
    def perform_create(self, serializer):
        task = serializer.save(**guards.prepare_task_create(self.request.user, serializer.validated_data))
        # TaskCreateView : l'assigné reçoit aussi son TaskAssignment.
        if task.assignee_id and not dm.TaskAssignment.objects.filter(task=task, user_id=task.assignee_id).exists():
            dm.TaskAssignment.objects.create(task=task, user_id=task.assignee_id, assigned_by=self.request.user,
                                             allocation_percent=100)

    def perform_update(self, serializer):
        guards.check_task_update(self.request.user, serializer.instance, serializer.validated_data)
        serializer.instance._updated_by = self.request.user  # auteur transmis aux notifications
        serializer.save()

    def perform_destroy(self, instance):
        guards.check_task_destroy(self.request.user, instance)
        super().perform_destroy(instance)

    @action(detail=True, methods=["get"], url_path="overview")
    def overview(self, request, pk=None):
        """Contenu de la fiche tâche (commentaires, pièces jointes, affectations, checklists, sous-tâches, dépendances)."""
        from project.services.task_permissions import can_delete_task, can_edit_task
        from project.services.task_quick_update import task_state

        task = self.get_object()

        def name(u):
            return (u.get_full_name() or u.get_username()) if u else ""

        comments = task.comments.select_related("author").order_by("-created_at")
        return Response({
            "state": task_state(task, request.user),
            "description": task.description,
            "reporter": name(task.reporter),
            # Miroir UX de TaskExtendView/TaskMarkExpiredView (PM ou owner du projet, staff).
            "can_arbitrate": bool(request.user.is_staff or (task.project_id and request.user.pk in (
                task.project.product_manager_id, task.project.owner_id))),
            # Droits réels (services/task_permissions) : l'UI masque, Django applique.
            "can_edit": can_edit_task(request.user, task),
            "can_delete": can_delete_task(request.user, task),
            "comments": [
                {"id": c.pk, "author": name(c.author), "body": c.body, "is_internal": c.is_internal,
                 "created_at": c.created_at.isoformat()}
                for c in comments
            ],
            "attachments": [
                {"id": a.pk, "name": a.name or a.file.name.rsplit("/", 1)[-1], "url": a.file.url if a.file else None,
                 "size": a.size, "uploaded_by": name(a.uploaded_by), "created_at": a.created_at.isoformat()}
                for a in task.attachments.select_related("uploaded_by").order_by("-created_at")
            ],
            "assignments": [
                {"id": a.pk, "user": name(a.user), "allocation_percent": a.allocation_percent, "is_active": a.is_active}
                for a in task.assignments.select_related("user").order_by("-is_active", "user__username")
            ],
            "checklists": [
                {"id": c.pk, "title": c.title,
                 "items": [{"id": i.pk, "text": i.text, "is_checked": i.is_checked} for i in c.items.order_by("position")]}
                for c in task.checklists.prefetch_related("items").order_by("position")
            ],
            "subtasks": [
                {"id": t.pk, "title": t.title, "status_label": t.get_status_display(), "assignee": name(t.assignee)}
                for t in task.subtasks.filter(is_archived=False).select_related("assignee").order_by("position")
            ],
            # « out » : cette tâche <type> autre ; « in » : autre <type> cette tâche.
            "dependencies": [
                {"id": d.pk, "direction": "out", "type": d.get_dependency_type_display(), "task_id": d.to_task_id,
                 "title": d.to_task.title}
                for d in task.outgoing_dependencies.select_related("to_task")
            ] + [
                {"id": d.pk, "direction": "in", "type": d.get_dependency_type_display(), "task_id": d.from_task_id,
                 "title": d.from_task.title}
                for d in task.incoming_dependencies.select_related("from_task")
            ],
            "labels": [
                {"id": tl.pk, "name": tl.label.name, "color": tl.label.color}
                for tl in task.labels.select_related("label").order_by("label__name")
            ],
        })

    @action(
        detail=True,
        methods=["get"],
        url_path="ai/effort-estimate",
        throttle_classes=[AIActionRateThrottle],
    )
    def ai_effort_estimate(self, request, pk=None):
        task = self.get_object()
        estimate = EffortEstimationService.estimate_task(task, use_ai=True)
        return Response(estimate.__dict__)


class TimesheetEntryViewSet(WorkspaceScopedViewSetMixin, viewsets.ModelViewSet):
    """
    Saisies de temps — mêmes règles que l'interface Django :

    * lecture : soi + subordonnés (N-1, N-2…) via ``visible_user_ids`` ; le
      propriétaire du workspace (``timesheet.*``) et le super-admin voient tout
      le workspace (exports / intégrations) ;
    * écriture : uniquement ses propres saisies, en brouillon ou rejetées, hors
      semaines soumises / validées ; les transitions (soumission, validation,
      rejet, réouverture) passent exclusivement par le workflow N+1.
    """
    queryset = dm.TimesheetEntry.objects.select_related("user", "project", "task", "cost_snapshot")
    serializer_class = TimesheetEntrySerializer
    permission_classes = DEFAULT_PERMISSIONS
    filterset_fields = ["user", "workspace", "project", "task", "approval_status", "is_billable"]

    def get_queryset(self):
        from project.services.rbac import RBACService
        from project.services.timesheet_workflow import visible_user_ids
        from project.utils.workspaces import get_user_workspace_ids

        qs = super().get_queryset()
        user = self.request.user
        if user.is_superuser:
            return qs
        scope = Q(pk__in=[])
        for ws in dm.Workspace.objects.filter(id__in=get_user_workspace_ids(user)):
            if RBACService.can(user, "timesheet.view_all", workspace=ws):
                scope |= Q(workspace_id=ws.pk)
            else:
                scope |= Q(workspace_id=ws.pk, user_id__in=visible_user_ids(user, ws))
        return qs.filter(scope)

    def perform_create(self, serializer):
        from project.services.timesheet_workflow import reopen_rejected_for_correction

        entry = serializer.save(**guards.prepare_entry_create(self.request.user, serializer.validated_data))
        reopen_rejected_for_correction(entry.user, entry.workspace, entry.entry_date)

    def perform_update(self, serializer):
        from project.services.timesheet_workflow import reopen_rejected_for_correction

        forced = guards.check_entry_update(self.request.user, serializer.instance, serializer.validated_data)
        entry = serializer.save(**forced)
        reopen_rejected_for_correction(entry.user, entry.workspace, entry.entry_date)

    def perform_destroy(self, instance):
        guards.check_entry_destroy(self.request.user, instance)
        super().perform_destroy(instance)


class AInsightViewSet(WorkspaceScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = dm.AInsight.objects.select_related("workspace", "project", "sprint", "task")
    serializer_class = AInsightSerializer
    permission_classes = DEFAULT_PERMISSIONS
    filterset_fields = ["workspace", "project", "insight_type", "severity", "is_dismissed"]


# =========================================================================
# Phase 2 — ViewSets multi-modes projet (PR12)
# =========================================================================

class ProjectPhaseViewSet(WorkspaceScopedViewSetMixin, viewsets.ModelViewSet):
    """
    Phases d'un projet Waterfall. Le filtre workspace est automatique
    via WorkspaceScopedViewSetMixin (Phase 0 PR3).
    """
    queryset = dm.ProjectPhase.objects.select_related(
        "workspace", "project", "owner"
    ).filter(is_archived=False)
    serializer_class = ProjectPhaseSerializer
    permission_classes = DEFAULT_PERMISSIONS
    filterset_fields = ["workspace", "project", "status", "gate_required"]
    search_fields = ["name", "description"]
    ordering_fields = ["position", "start_date", "end_date", "created_at"]


class ProjectViewPreferenceViewSet(WorkspaceScopedViewSetMixin, viewsets.ModelViewSet):
    """
    Préférence de vue par (user, project). L'utilisateur ne voit que ses
    propres préférences (filtre sur request.user dans get_queryset).
    """
    queryset = dm.ProjectViewPreference.objects.select_related(
        "user", "project"
    )
    serializer_class = ProjectViewPreferenceSerializer
    permission_classes = DEFAULT_PERMISSIONS
    filterset_fields = ["project", "view_mode"]

    def get_queryset(self):
        # En plus du scope workspace hérité du mixin, on limite à
        # l'utilisateur connecté — pas de raison de voir les préférences
        # de ses collègues.
        qs = super().get_queryset()
        user = getattr(self.request, "user", None)
        if user and user.is_authenticated:
            return qs.filter(user=user)
        return qs.none()

    def perform_create(self, serializer):
        # L'utilisateur ne peut créer que pour lui-même.
        serializer.save(user=self.request.user)


class FieldReportViewSet(WorkspaceScopedViewSetMixin, viewsets.ModelViewSet):
    """Rapports de chantier pour les projets terrain."""
    queryset = dm.FieldReport.objects.select_related(
        "workspace", "project", "reporter"
    ).prefetch_related("photos").filter(is_archived=False)
    serializer_class = FieldReportSerializer
    permission_classes = DEFAULT_PERMISSIONS
    filterset_fields = ["workspace", "project", "reporter", "weather"]
    search_fields = ["location_name", "notes", "incidents"]
    ordering_fields = ["report_date", "created_at"]

    def perform_create(self, serializer):
        # Si le reporter n'est pas fourni, on prend l'utilisateur courant.
        if not serializer.validated_data.get("reporter"):
            serializer.save(reporter=self.request.user)
        else:
            serializer.save()


class RealEstateLotViewSet(WorkspaceScopedViewSetMixin, viewsets.ModelViewSet):
    """Lots d'un projet immobilier."""
    queryset = dm.RealEstateLot.objects.select_related(
        "workspace", "project"
    ).filter(is_archived=False)
    serializer_class = RealEstateLotSerializer
    permission_classes = DEFAULT_PERMISSIONS
    filterset_fields = ["workspace", "project", "status", "currency"]
    search_fields = ["lot_number", "buyer_name", "buyer_email"]
    ordering_fields = ["lot_number", "price", "surface_m2",
                       "reserved_at", "sold_at", "created_at"]


class AdminCaseViewSet(WorkspaceScopedViewSetMixin, viewsets.ModelViewSet):
    """Dossiers administratifs (instruction, SLA, deadlines)."""
    queryset = dm.AdminCase.objects.select_related(
        "workspace", "project", "assignee"
    ).filter(is_archived=False)
    serializer_class = AdminCaseSerializer
    permission_classes = DEFAULT_PERMISSIONS
    filterset_fields = ["workspace", "project", "status",
                        "document_type", "assignee"]
    search_fields = ["reference", "title", "applicant"]
    ordering_fields = ["requested_at", "deadline", "decided_at", "created_at"]


# =========================================================================
# Phase 3 — ViewSets Budget V2 (PR15)
# =========================================================================

class ProjectBudgetSnapshotViewSet(WorkspaceScopedViewSetMixin, viewsets.ModelViewSet):
    """
    Snapshots de budget (BASELINE / FORECAST / MANUAL / AUTO).

    Création : préfère utiliser
    ``POST /api/v1/projects/{id}/budget/snapshot/`` qui appelle
    ``BudgetSnapshotService.capture()`` et garantit le payload figé.
    Ce viewset reste utile pour LIST / GET / DELETE.
    """
    queryset = dm.ProjectBudgetSnapshot.objects.select_related(
        "workspace", "project", "created_by"
    )
    serializer_class = ProjectBudgetSnapshotSerializer
    permission_classes = DEFAULT_PERMISSIONS
    filterset_fields = ["workspace", "project", "kind"]
    ordering_fields = ["snapshot_date", "created_at"]


class ProjectBudgetForecastRunViewSet(WorkspaceScopedViewSetMixin,
                                       viewsets.ReadOnlyModelViewSet):
    """Read-only : ces runs sont créés par le service IA, pas par le client."""
    queryset = dm.ProjectBudgetForecastRun.objects.select_related(
        "workspace", "project", "triggered_by"
    )
    serializer_class = ProjectBudgetForecastRunSerializer
    permission_classes = DEFAULT_PERMISSIONS
    filterset_fields = ["workspace", "project", "used_provider"]
    ordering_fields = ["created_at", "horizon_end"]


# =========================================================================
# Phase 5 — Rapports IA hebdomadaires (PR22)
# =========================================================================
class ProjectAIReportViewSet(WorkspaceScopedViewSetMixin,
                              viewsets.ReadOnlyModelViewSet):
    """
    Rapports projet IA en lecture seule.
    La génération passe par l'action ``ai/report/generate`` sur le projet,
    ou par la tâche Celery hebdomadaire.
    """
    queryset = dm.ProjectAIReport.objects.select_related(
        "workspace", "project", "generated_by",
    ).filter(is_archived=False)
    serializer_class = ProjectAIReportSerializer
    permission_classes = DEFAULT_PERMISSIONS
    filterset_fields = ["workspace", "project", "period", "status"]
    ordering_fields = ["period_end", "generated_at", "created_at"]
