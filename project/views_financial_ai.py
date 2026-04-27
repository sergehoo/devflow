"""
Vues IA financières DevFlow.

Routes :
- GET  /projects/<id>/financial-ai/forecast/   → BudgetForecast (HTML)
- POST /projects/<id>/financial-ai/forecast/   → idem en JSON (htmx)
- POST /projects/<id>/financial-ai/risks/      → analyse risques + persist AInsight
- GET  /workspaces/<id>/financial-ai/allocation/ → recommandations d'allocation
- GET  /workspaces/<id>/financial-ai/portfolio/  → cockpit budget portefeuille
"""

from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views import View
from django.views.generic import TemplateView

from project import models as dm
from project.services.ai.services.allocation_advice import AllocationAdviceService
from project.services.ai.services.budget_forecast import BudgetForecastService
from project.services.ai.services.risk_analysis import RiskAnalysisService
from project.services.budget import ProjectBudgetService
from project.views_budget import ProjectFinancialPermissionMixin


class ProjectBudgetForecastView(ProjectFinancialPermissionMixin, LoginRequiredMixin, View):
    template_name = "project/budget/forecast.html"

    def get(self, request, project_id, *args, **kwargs):
        project = get_object_or_404(
            dm.Project.objects.select_related("workspace"), pk=project_id
        )
        if not self.can_view_financials(project):
            return JsonResponse({"error": "permission denied"}, status=403)

        forecast = BudgetForecastService.forecast(project, use_ai=True)
        return JsonResponse(forecast.to_dict())

    def post(self, request, project_id, *args, **kwargs):
        return self.get(request, project_id, *args, **kwargs)


class ProjectRiskAnalysisView(ProjectFinancialPermissionMixin, LoginRequiredMixin, View):
    def post(self, request, project_id, *args, **kwargs):
        project = get_object_or_404(
            dm.Project.objects.select_related("workspace"), pk=project_id
        )
        if not self.can_view_financials(project):
            return JsonResponse({"error": "permission denied"}, status=403)

        signals = RiskAnalysisService.analyze(project, persist=True, use_ai=True)
        return JsonResponse(
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


class WorkspaceAllocationAdviceView(LoginRequiredMixin, View):
    def get(self, request, workspace_id, *args, **kwargs):
        workspace = get_object_or_404(dm.Workspace, pk=workspace_id)
        advice = AllocationAdviceService.advise(workspace, use_ai=True)
        return JsonResponse(advice.to_dict())


class WorkspaceFinancialPortfolioView(LoginRequiredMixin, TemplateView):
    template_name = "project/budget/portfolio.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        workspace_id = self.kwargs.get("workspace_id")
        workspace = get_object_or_404(dm.Workspace, pk=workspace_id)

        projects = (
            workspace.projects
            .select_related("owner", "product_manager")
            .filter(is_archived=False)
        )
        ctx["workspace"] = workspace
        ctx["portfolio"] = ProjectBudgetService.build_portfolio_overview(projects)
        return ctx
