"""
DevFlow REST API — ViewSets.

Tous les viewsets exposent CRUD + actions IA financières (forecast,
risk-analysis, allocation-advice).
"""

from __future__ import annotations

from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from project import models as dm
from project.api.serializers import (
    AInsightSerializer,
    BillingRateSerializer,
    BudgetOverviewSerializer,
    ProjectBudgetSerializer,
    ProjectEstimateLineSerializer,
    ProjectExpenseSerializer,
    ProjectMemberSerializer,
    ProjectRevenueSerializer,
    ProjectSerializer,
    SprintSerializer,
    TaskSerializer,
    TeamSerializer,
    TimesheetEntrySerializer,
    WorkspaceSerializer,
)
from project.services.ai.services.allocation_advice import AllocationAdviceService
from project.services.ai.services.budget_forecast import BudgetForecastService
from project.services.ai.services.effort_estimation import EffortEstimationService
from project.services.ai.services.risk_analysis import RiskAnalysisService
from project.services.budget import ProjectBudgetService


class WorkspaceViewSet(viewsets.ModelViewSet):
    queryset = dm.Workspace.objects.filter(is_archived=False).order_by("name")
    serializer_class = WorkspaceSerializer
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=True, methods=["get"], url_path="portfolio")
    def portfolio(self, request, pk=None):
        workspace = self.get_object()
        projects = workspace.projects.filter(is_archived=False)
        return Response(ProjectBudgetService.build_portfolio_overview(projects))

    @action(detail=True, methods=["get"], url_path="allocation-advice")
    def allocation_advice(self, request, pk=None):
        workspace = self.get_object()
        advice = AllocationAdviceService.advise(workspace, use_ai=True)
        return Response(advice.to_dict())


class TeamViewSet(viewsets.ModelViewSet):
    queryset = dm.Team.objects.all().order_by("name")
    serializer_class = TeamSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ["workspace", "team_type"]


class ProjectViewSet(viewsets.ModelViewSet):
    queryset = (
        dm.Project.objects
        .select_related("workspace", "team", "owner", "product_manager")
        .filter(is_archived=False)
    )
    serializer_class = ProjectSerializer
    permission_classes = [permissions.IsAuthenticated]
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

    @action(detail=True, methods=["get", "post"], url_path="ai/forecast")
    def ai_forecast(self, request, pk=None):
        project = self.get_object()
        forecast = BudgetForecastService.forecast(project, use_ai=True)
        return Response(forecast.to_dict())

    @action(detail=True, methods=["post"], url_path="ai/risk-analysis")
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


class ProjectMemberViewSet(viewsets.ModelViewSet):
    queryset = dm.ProjectMember.objects.select_related("user", "project", "team")
    serializer_class = ProjectMemberSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ["project", "user", "team"]


class BillingRateViewSet(viewsets.ModelViewSet):
    queryset = dm.BillingRate.objects.select_related("user", "team").order_by("-valid_from")
    serializer_class = BillingRateSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ["user", "team", "unit", "is_internal_cost", "is_billable_rate"]


class ProjectBudgetViewSet(viewsets.ModelViewSet):
    queryset = dm.ProjectBudget.objects.select_related("project")
    serializer_class = ProjectBudgetSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ["project", "status"]


class ProjectEstimateLineViewSet(viewsets.ModelViewSet):
    queryset = dm.ProjectEstimateLine.objects.select_related("project", "category", "task", "sprint")
    serializer_class = ProjectEstimateLineSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ["project", "category", "source_type", "budget_stage", "task", "sprint"]


class ProjectRevenueViewSet(viewsets.ModelViewSet):
    queryset = dm.ProjectRevenue.objects.select_related("project")
    serializer_class = ProjectRevenueSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ["project", "revenue_type", "status", "is_received"]


class ProjectExpenseViewSet(viewsets.ModelViewSet):
    queryset = dm.ProjectExpense.objects.select_related("project", "category", "created_by")
    serializer_class = ProjectExpenseSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ["project", "category", "status", "approval_state", "is_labor_cost", "is_direct_cost"]
    search_fields = ["title", "vendor", "reference"]

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


class SprintViewSet(viewsets.ModelViewSet):
    queryset = dm.Sprint.objects.select_related("project", "team")
    serializer_class = SprintSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ["workspace", "project", "team", "status"]


class TaskViewSet(viewsets.ModelViewSet):
    queryset = dm.Task.objects.select_related("project", "sprint", "assignee", "reporter")
    serializer_class = TaskSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ["workspace", "project", "sprint", "status", "priority", "assignee", "is_archived"]
    search_fields = ["title", "description"]

    @action(detail=True, methods=["get"], url_path="ai/effort-estimate")
    def ai_effort_estimate(self, request, pk=None):
        task = self.get_object()
        estimate = EffortEstimationService.estimate_task(task, use_ai=True)
        return Response(estimate.__dict__)


class TimesheetEntryViewSet(viewsets.ModelViewSet):
    queryset = dm.TimesheetEntry.objects.select_related("user", "project", "task", "cost_snapshot")
    serializer_class = TimesheetEntrySerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ["user", "workspace", "project", "task", "approval_status", "is_billable"]


class AInsightViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = dm.AInsight.objects.select_related("workspace", "project", "sprint", "task")
    serializer_class = AInsightSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ["workspace", "project", "insight_type", "severity", "is_dismissed"]
