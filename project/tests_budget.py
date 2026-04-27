"""
Tests unitaires DevFlow — Module financier (TJM, marges, forecast).

Lance avec :
    python manage.py test project.tests_budget
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from project import models as dm
from project.services.ai.services.budget_forecast import BudgetForecastService
from project.services.ai.services.effort_estimation import EffortEstimationService
from project.services.ai.services.risk_analysis import RiskAnalysisService
from project.services.budget import ProjectBudgetService

User = get_user_model()


class BudgetServiceTestCase(TestCase):
    """Couvre les calculs TJM, marges, forecast, risques."""

    def setUp(self):
        self.workspace = dm.Workspace.objects.create(name="WS Test")

        self.user = User.objects.create_user(
            username="alice", email="alice@example.com", password="x"
        )
        dm.UserProfile.objects.create(
            user=self.user,
            workspace=self.workspace,
            cost_per_day=Decimal("400"),
            billable_rate_per_day=Decimal("700"),
            capacity_hours_per_day=Decimal("8"),
            availability_percent=100,
        )

        # Tarif actif (DAILY)
        dm.BillingRate.objects.create(
            user=self.user,
            unit=dm.BillingRate.RateUnit.DAILY,
            cost_rate_amount=Decimal("400"),
            sale_rate_amount=Decimal("700"),
            valid_from=date.today() - timedelta(days=10),
            is_internal_cost=True,
            is_billable_rate=True,
        )

        self.project = dm.Project.objects.create(
            workspace=self.workspace,
            name="Projet Demo",
            start_date=date.today(),
            target_date=date.today() + timedelta(days=20),
            owner=self.user,
        )

        dm.ProjectMember.objects.create(
            project=self.project,
            user=self.user,
            allocation_percent=100,
        )

        self.labor_cat = dm.CostCategory.objects.create(
            name="RH", category_type=dm.CostCategory.CategoryType.HUMAN
        )
        self.infra_cat = dm.CostCategory.objects.create(
            name="Infra", category_type=dm.CostCategory.CategoryType.INFRA
        )

    # ---------------------------------------------------------------------
    # TJM
    # ---------------------------------------------------------------------
    def test_user_daily_cost_uses_billing_rate(self):
        cost = ProjectBudgetService.get_member_daily_cost(self.user)
        self.assertEqual(cost, Decimal("400"))

    def test_user_daily_sale_uses_billing_rate(self):
        sale = ProjectBudgetService.get_member_daily_sale_rate(self.user)
        self.assertEqual(sale, Decimal("700"))

    def test_member_period_cost_respects_allocation(self):
        cost, sale = ProjectBudgetService.estimate_member_period_cost(
            user=self.user,
            start=date.today(),
            end=date.today() + timedelta(days=6),
            allocation_percent=50,
        )
        # 7 jours calendaires → ~5 jours ouvrés × 50% × TJM
        self.assertGreater(cost, Decimal("0"))
        self.assertGreater(sale, cost)

    def test_working_days_between(self):
        days = ProjectBudgetService.working_days_between(
            date(2026, 1, 5), date(2026, 1, 11)
        )
        # 7 jours calendaires → ~5 jours ouvrés
        self.assertGreaterEqual(days, Decimal("4"))
        self.assertLessEqual(days, Decimal("6"))

    # ---------------------------------------------------------------------
    # Tâches
    # ---------------------------------------------------------------------
    def test_estimate_task_costs(self):
        task = dm.Task.objects.create(
            workspace=self.workspace,
            project=self.project,
            title="Dev module X",
            estimate_hours=Decimal("16"),
            assignee=self.user,
            reporter=self.user,
        )
        cost, sale = ProjectBudgetService.estimate_task_costs(task)
        # 16h / 8 = 2 jours
        self.assertEqual(cost, Decimal("800"))   # 2 × 400
        self.assertEqual(sale, Decimal("1400"))  # 2 × 700

    def test_estimate_task_remaining(self):
        task = dm.Task.objects.create(
            workspace=self.workspace,
            project=self.project,
            title="Dev module Y",
            estimate_hours=Decimal("16"),
            spent_hours=Decimal("8"),
            assignee=self.user,
            reporter=self.user,
        )
        cost, sale = ProjectBudgetService.estimate_task_remaining_costs(task)
        # 8h restant / 8 = 1 jour
        self.assertEqual(cost, Decimal("400"))
        self.assertEqual(sale, Decimal("700"))

    # ---------------------------------------------------------------------
    # Revenus / dépenses
    # ---------------------------------------------------------------------
    def test_summarize_revenues_uses_actual_amounts(self):
        dm.ProjectRevenue.objects.create(
            project=self.project,
            title="Acompte",
            amount=Decimal("1000"),
            invoiced_amount=Decimal("500"),
            received_amount=Decimal("250"),
        )
        summary = ProjectBudgetService.summarize_revenues(self.project)
        self.assertEqual(summary["planned"], Decimal("1000"))
        self.assertEqual(summary["invoiced"], Decimal("500"))
        self.assertEqual(summary["received"], Decimal("250"))
        self.assertEqual(summary["remaining_to_invoice"], Decimal("500"))
        self.assertEqual(summary["remaining_to_collect"], Decimal("250"))

    def test_summarize_expenses_uses_real_statuses(self):
        dm.ProjectExpense.objects.create(
            project=self.project,
            category=self.infra_cat,
            title="Cloud",
            amount=Decimal("100"),
            status=dm.ProjectExpense.ExpenseStatus.COMMITTED,
        )
        dm.ProjectExpense.objects.create(
            project=self.project,
            category=self.infra_cat,
            title="Cloud paid",
            amount=Decimal("200"),
            status=dm.ProjectExpense.ExpenseStatus.PAID,
        )
        summary = ProjectBudgetService.summarize_expenses(self.project)
        self.assertEqual(summary["committed"], Decimal("100"))
        self.assertEqual(summary["paid"], Decimal("200"))
        self.assertEqual(summary["direct_cost"], Decimal("300"))

    # ---------------------------------------------------------------------
    # Overview
    # ---------------------------------------------------------------------
    def test_build_budget_overview_keys_present(self):
        dm.ProjectBudget.objects.create(
            project=self.project,
            currency="XOF",
            approved_budget=Decimal("5000"),
            planned_revenue=Decimal("8000"),
        )
        ov = ProjectBudgetService.build_budget_overview(self.project)
        for key in [
            "approved_budget", "estimated_cost", "actual_cost",
            "planned_revenue", "received_revenue", "total_received",
            "forecast_margin", "real_margin", "expense_ratio_percent",
            "forecast_consumption_percent", "currency",
        ]:
            self.assertIn(key, ov, f"{key} manquant dans build_budget_overview")

    # ---------------------------------------------------------------------
    # Forecast IA (heuristique sans IA)
    # ---------------------------------------------------------------------
    def test_budget_forecast_heuristic_runs(self):
        forecast = BudgetForecastService.forecast(self.project, use_ai=False)
        self.assertEqual(forecast.project_id, self.project.pk)
        self.assertGreaterEqual(forecast.base_cost, Decimal("0"))
        self.assertEqual(forecast.used_provider, "heuristic")

    def test_risk_analysis_heuristic_runs(self):
        # Force un signal en mettant une date cible passée
        self.project.target_date = date.today() - timedelta(days=5)
        self.project.status = dm.Project.Status.IN_PROGRESS
        self.project.save()
        signals = RiskAnalysisService.analyze(self.project, persist=False, use_ai=False)
        codes = {s.code for s in signals}
        self.assertIn("DEADLINE_PASSED", codes)

    def test_effort_estimation_heuristic(self):
        task = dm.Task.objects.create(
            workspace=self.workspace,
            project=self.project,
            title="Tâche test",
            estimate_hours=Decimal("0"),
            assignee=self.user,
            reporter=self.user,
        )
        estimate = EffortEstimationService.estimate_task(task, use_ai=False)
        self.assertGreater(estimate.estimate_hours, 0)
        self.assertEqual(estimate.used_provider, "heuristic")
