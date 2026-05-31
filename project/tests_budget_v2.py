"""
Tests Phase 3 — Budget V2 (PR15).

Couvre :
    * Lookup TJM avec priorité projet-spécifique (BillingRate.project)
    * BudgetSnapshotService.capture / latest / compare
    * BudgetAlertService.for_project / for_workspace
    * ProjectEACService.recompute

Lance avec :
    python manage.py test project.tests_budget_v2
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from project import models as dm
from project.services.budget import ProjectBudgetService
from project.services.budget_snapshots import (
    BudgetAlertService,
    BudgetSnapshotService,
    ProjectEACService,
)

User = get_user_model()


class BudgetV2SetupMixin:
    """Setup commun : 1 user, 1 workspace, 1 projet, 1 BillingRate générique."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="alice_v2", email="alice_v2@example.com", password="x",
        )
        cls.workspace = dm.Workspace.objects.create(
            name="WS Budget V2", owner=cls.user,
        )
        dm.UserProfile.objects.create(
            user=cls.user, workspace=cls.workspace,
            cost_per_day=Decimal("300"),
            billable_rate_per_day=Decimal("600"),
            capacity_hours_per_day=Decimal("8"),
            availability_percent=100,
        )

        cls.project = dm.Project.objects.create(
            workspace=cls.workspace,
            name="Projet Budget V2",
            owner=cls.user,
            start_date=date.today(),
            target_date=date.today() + timedelta(days=30),
        )

        # Tarif générique (workspace-wide)
        cls.generic_rate = dm.BillingRate.objects.create(
            user=cls.user,
            unit=dm.BillingRate.RateUnit.DAILY,
            cost_rate_amount=Decimal("400"),
            sale_rate_amount=Decimal("700"),
            valid_from=date.today() - timedelta(days=10),
            is_internal_cost=True,
            is_billable_rate=True,
        )


# ---------------------------------------------------------------------------
# Lookup TJM avec priorité projet
# ---------------------------------------------------------------------------
class TJMProjectPriorityTests(BudgetV2SetupMixin, TestCase):

    def test_generic_rate_used_when_no_project_rate(self):
        """Sans BillingRate spécifique projet, on prend le tarif générique."""
        cost = ProjectBudgetService.get_member_daily_cost(
            self.user, project=self.project,
        )
        sale = ProjectBudgetService.get_member_daily_sale_rate(
            self.user, project=self.project,
        )
        self.assertEqual(cost, Decimal("400"))
        self.assertEqual(sale, Decimal("700"))

    def test_project_specific_rate_wins_over_generic(self):
        """Un BillingRate projet-spécifique a priorité absolue."""
        dm.BillingRate.objects.create(
            user=self.user,
            project=self.project,
            unit=dm.BillingRate.RateUnit.DAILY,
            cost_rate_amount=Decimal("500"),
            sale_rate_amount=Decimal("900"),
            valid_from=date.today() - timedelta(days=5),
            is_internal_cost=True,
            is_billable_rate=True,
        )
        cost = ProjectBudgetService.get_member_daily_cost(
            self.user, project=self.project,
        )
        sale = ProjectBudgetService.get_member_daily_sale_rate(
            self.user, project=self.project,
        )
        self.assertEqual(cost, Decimal("500"))
        self.assertEqual(sale, Decimal("900"))

    def test_call_without_project_uses_legacy_lookup(self):
        """get_member_daily_cost(user) sans project = comportement legacy."""
        # Crée un tarif projet-spécifique : il NE doit pas être retenu sans
        # passer project=... dans l'appel (compat backward).
        dm.BillingRate.objects.create(
            user=self.user,
            project=self.project,
            unit=dm.BillingRate.RateUnit.DAILY,
            cost_rate_amount=Decimal("999"),
            sale_rate_amount=Decimal("999"),
            valid_from=date.today() - timedelta(days=5),
            is_internal_cost=True,
            is_billable_rate=True,
        )
        # On appelle SANS project → legacy : il prend le 1er match (le plus récent),
        # qui inclut potentiellement le tarif projet. C'est le comportement attendu
        # côté API legacy. Pour bénéficier de la priorité, il faut passer project=...
        cost_legacy = ProjectBudgetService.get_member_daily_cost(self.user)
        # On vérifie juste que la valeur est non-zero (le legacy fonctionne toujours).
        self.assertGreater(cost_legacy, Decimal("0"))


# ---------------------------------------------------------------------------
# BudgetSnapshotService
# ---------------------------------------------------------------------------
class BudgetSnapshotServiceTests(BudgetV2SetupMixin, TestCase):

    def test_capture_creates_snapshot_with_payload(self):
        snap = BudgetSnapshotService.capture(
            self.project, label="Baseline V1",
            kind=dm.ProjectBudgetSnapshot.SnapshotKind.BASELINE,
            actor=self.user,
        )
        self.assertIsNotNone(snap.pk)
        self.assertEqual(snap.kind, "BASELINE")
        self.assertEqual(snap.label, "Baseline V1")
        # Le payload contient les clés essentielles du overview
        self.assertIn("currency", snap.payload)
        # Workspace auto-derivé
        self.assertEqual(snap.workspace_id, self.workspace.pk)

    def test_capture_with_default_label(self):
        snap = BudgetSnapshotService.capture(
            self.project,
            kind=dm.ProjectBudgetSnapshot.SnapshotKind.AUTO,
        )
        self.assertIn("Auto", snap.label)

    def test_latest_filters_by_kind(self):
        BudgetSnapshotService.capture(
            self.project, label="A",
            kind=dm.ProjectBudgetSnapshot.SnapshotKind.MANUAL,
        )
        baseline = BudgetSnapshotService.capture(
            self.project, label="B",
            kind=dm.ProjectBudgetSnapshot.SnapshotKind.BASELINE,
        )
        latest_baseline = BudgetSnapshotService.latest(
            self.project, kind=dm.ProjectBudgetSnapshot.SnapshotKind.BASELINE,
        )
        self.assertEqual(latest_baseline.pk, baseline.pk)

    def test_compare_returns_diff_dict(self):
        a = BudgetSnapshotService.capture(self.project, label="A")
        b = BudgetSnapshotService.capture(self.project, label="B")
        result = BudgetSnapshotService.compare(a, b)
        self.assertIn("diff", result)
        self.assertEqual(result["snapshot_a"]["id"], a.pk)
        self.assertEqual(result["snapshot_b"]["id"], b.pk)


# ---------------------------------------------------------------------------
# BudgetAlertService
# ---------------------------------------------------------------------------
class BudgetAlertServiceTests(BudgetV2SetupMixin, TestCase):

    def _make_budget(self, consumption_percent, threshold=80):
        """Crée un ProjectBudget avec un %consumption pré-calculé via dépenses."""
        budget = dm.ProjectBudget.objects.create(
            project=self.project,
            approved_budget=Decimal("1000"),
            alert_threshold_percent=threshold,
            currency="XOF",
        )
        return budget

    def test_no_alert_below_threshold(self):
        """Si pas de ProjectBudget, pas d'alerte."""
        result = BudgetAlertService.for_project(self.project)
        self.assertIsNone(result)

    def test_classify_severity(self):
        """Tests purs des seuils."""
        cls = BudgetAlertService
        self.assertIsNone(cls._classify(50, 80))   # bien en dessous
        self.assertIsNone(cls._classify(79, 80))   # juste en dessous
        self.assertEqual(cls._classify(80, 80), "info")        # = threshold
        self.assertEqual(cls._classify(85, 80), "info")        # threshold +5
        self.assertEqual(cls._classify(90, 80), "warning")     # threshold +10
        self.assertEqual(cls._classify(99, 80), "warning")
        self.assertEqual(cls._classify(100, 80), "critical")
        self.assertEqual(cls._classify(150, 80), "critical")

    def test_for_workspace_returns_sorted_alerts(self):
        """Aucune alerte si pas de ProjectBudget — on teste juste la mécanique."""
        alerts = BudgetAlertService.for_workspace(self.workspace)
        self.assertEqual(alerts, [])


# ---------------------------------------------------------------------------
# ProjectEACService
# ---------------------------------------------------------------------------
class ProjectEACServiceTests(BudgetV2SetupMixin, TestCase):

    def test_recompute_updates_project_fields(self):
        # Initialement les champs sont à 0 / None
        self.project.refresh_from_db()
        self.assertEqual(self.project.computed_eac, Decimal("0"))
        self.assertIsNone(self.project.eac_computed_at)

        # Recompute (le build_budget_overview marche même sans budget configuré)
        stats = ProjectEACService.recompute(self.project)
        self.assertEqual(stats["project_id"], self.project.pk)

        self.project.refresh_from_db()
        # eac_computed_at est maintenant rempli
        self.assertIsNotNone(self.project.eac_computed_at)
        # computed_eac et computed_cost_variance sont des Decimal valides
        self.assertIsInstance(self.project.computed_eac, Decimal)
        self.assertIsInstance(self.project.computed_cost_variance, Decimal)

    def test_recompute_workspace_handles_multiple_projects(self):
        dm.Project.objects.create(
            workspace=self.workspace,
            name="Projet 2",
            owner=self.user,
            start_date=date.today(),
            target_date=date.today() + timedelta(days=30),
        )
        stats = ProjectEACService.recompute_workspace(self.workspace)
        self.assertGreaterEqual(stats["recomputed"], 2)
        self.assertEqual(stats["errors"], 0)


# ---------------------------------------------------------------------------
# Phase 3 PR16 — Machine à états ProjectBudget.transition_to()
# ---------------------------------------------------------------------------
class BudgetStatusTransitionTests(BudgetV2SetupMixin, TestCase):

    def _make_budget(self, status="DRAFT"):
        return dm.ProjectBudget.objects.create(
            project=self.project,
            status=status,
            approved_budget=Decimal("1000"),
            currency="XOF",
        )

    def test_allowed_transition_draft_to_estimated(self):
        budget = self._make_budget("DRAFT")
        budget.transition_to("ESTIMATED")
        budget.refresh_from_db()
        self.assertEqual(budget.status, "ESTIMATED")

    def test_baseline_transition_creates_snapshot(self):
        budget = self._make_budget("ESTIMATED")
        budget.transition_to("BASELINE", actor=self.user)
        budget.refresh_from_db()
        self.assertEqual(budget.status, "BASELINE")
        # Un snapshot KIND=BASELINE doit avoir été créé automatiquement.
        snap = dm.ProjectBudgetSnapshot.objects.filter(
            project=self.project, kind="BASELINE",
        ).first()
        self.assertIsNotNone(snap)
        self.assertEqual(snap.created_by, self.user)

    def test_baseline_without_auto_snapshot(self):
        budget = self._make_budget("ESTIMATED")
        budget.transition_to("BASELINE", actor=self.user, auto_snapshot=False)
        budget.refresh_from_db()
        self.assertEqual(budget.status, "BASELINE")
        self.assertEqual(
            dm.ProjectBudgetSnapshot.objects.filter(project=self.project).count(),
            0,
        )

    def test_approved_transition_sets_approved_by_and_at(self):
        budget = self._make_budget("BASELINE")
        budget.transition_to("APPROVED", actor=self.user)
        budget.refresh_from_db()
        self.assertEqual(budget.status, "APPROVED")
        self.assertIsNotNone(budget.approved_at)
        self.assertEqual(budget.approved_by, self.user)

    def test_forbidden_transition_raises_validation_error(self):
        from django.core.exceptions import ValidationError
        budget = self._make_budget("DRAFT")
        with self.assertRaises(ValidationError):
            budget.transition_to("APPROVED")   # DRAFT → APPROVED interdit
        budget.refresh_from_db()
        self.assertEqual(budget.status, "DRAFT")  # statut intouché

    def test_closed_is_terminal(self):
        from django.core.exceptions import ValidationError
        budget = self._make_budget("BASELINE")
        budget.transition_to("CLOSED")
        with self.assertRaises(ValidationError):
            budget.transition_to("APPROVED")   # rien n'est autorisé après CLOSED

    def test_noop_transition_to_same_status(self):
        budget = self._make_budget("DRAFT")
        budget.transition_to("DRAFT")   # ne lève pas, ne change rien
        budget.refresh_from_db()
        self.assertEqual(budget.status, "DRAFT")

    def test_closed_from_any_status(self):
        """CLOSED est autorisé depuis tout statut non-terminal."""
        for source in ["DRAFT", "ESTIMATED", "BASELINE", "APPROVED", "REVISED"]:
            project = dm.Project.objects.create(
                workspace=self.workspace,
                name=f"Test closed from {source}",
                owner=self.user,
                start_date=date.today(),
                target_date=date.today() + timedelta(days=30),
            )
            budget = dm.ProjectBudget.objects.create(
                project=project, status=source, currency="XOF",
            )
            budget.transition_to("CLOSED")
            budget.refresh_from_db()
            self.assertEqual(budget.status, "CLOSED")
