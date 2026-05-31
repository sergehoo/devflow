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

from rest_framework import permissions, viewsets
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
DEFAULT_PERMISSIONS = [permissions.IsAuthenticated, IsWorkspaceMember]
# PR25 — Permissions enrichies RBAC pour viewsets sensibles
RBAC_PERMISSIONS = [permissions.IsAuthenticated, IsWorkspaceMember, HasRBACPermission]


class WorkspaceViewSet(WorkspaceScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = dm.Workspace.objects.filter(is_archived=False).order_by("name")
    serializer_class = WorkspaceSerializer
    permission_classes = DEFAULT_PERMISSIONS

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
    queryset = dm.Team.objects.all().order_by("name")
    serializer_class = TeamSerializer
    permission_classes = DEFAULT_PERMISSIONS
    filterset_fields = ["workspace", "team_type"]


class ProjectViewSet(WorkspaceScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = (
        dm.Project.objects
        .select_related("workspace", "team", "owner", "product_manager")
        .filter(is_archived=False)
    )
    serializer_class = ProjectSerializer
    permission_classes = DEFAULT_PERMISSIONS
    filterset_fields = ["workspace", "status", "priority", "owner"]
    search_fields = ["name", "code", "description"]
    ordering_fields = ["name", "start_date", "target_date", "created_at"]

    @action(detail=True, methods=["get"], url_path="budget-overview")
    def budget_overview(self, request, pk=None):
        project = self.get_object()
        overview = ProjectBudgetService.build_budget_overview(project)
        return Response(BudgetOverviewSerializer(overview).data)

    @action(detail=True, methods=["post"], url_path="refresh-financials")
    def refresh_financials(self, request, pk=None):
        project = self.get_object()
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
    filterset_fields = ["workspace", "project", "sprint", "status", "priority", "assignee", "is_archived"]
    search_fields = ["title", "description"]

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
    """PR25 — Timesheets : un MEMBER ne voit que les siennes (filtre dans get_queryset)."""
    queryset = dm.TimesheetEntry.objects.select_related("user", "project", "task", "cost_snapshot")
    serializer_class = TimesheetEntrySerializer
    permission_classes = DEFAULT_PERMISSIONS
    filterset_fields = ["user", "workspace", "project", "task", "approval_status", "is_billable"]

    def get_queryset(self):
        qs = super().get_queryset()
        user = getattr(self.request, "user", None)
        if user and user.is_authenticated and not user.is_superuser:
            # Filtrage par rôle : MEMBER ne voit que les siennes
            from project.services.rbac import RBACService, MEMBER
            from project.utils.workspaces import get_default_workspace_for_user
            ws = get_default_workspace_for_user(user)
            role = RBACService.get_role_for(user, ws) if ws else None
            if role == MEMBER:
                qs = qs.filter(user=user)
        return qs


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
