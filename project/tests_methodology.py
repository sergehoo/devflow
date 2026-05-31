"""
Tests Phase 2 — Post-processing par méthodologie (PR13).

Vérifie que ``MethodologyPostProcessor.run(project)`` génère bien les
artefacts attendus selon ``project.methodology`` :

    WATERFALL       → 4 ProjectPhase séquentielles
    FIELD           → 1 FieldReport vierge
    REAL_ESTATE     → 3 RealEstateLot template
    ADMINISTRATIVE  → 1 AdminCase template (avec deadline auto)
    SCRUM/AGILE/KANBAN/MILESTONE → no-op (count=0)

Pas d'appel IA réel — on teste juste le post-processor en isolation.

Lance avec :
    python manage.py test project.tests_methodology
"""

from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase

from project import models as dm
from project.services.ai.services.methodology_postprocess import (
    MethodologyPostProcessor,
)

User = get_user_model()


class MethodologyPostProcessorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="postproc", email="pp@example.com", password="x",
        )
        cls.workspace = dm.Workspace.objects.create(
            name="WS PostProc", owner=cls.user,
        )

    def _make_project(self, methodology, *, days=120):
        return dm.Project.objects.create(
            workspace=self.workspace,
            name=f"Projet {methodology}",
            owner=self.user,
            start_date=date(2026, 1, 1),
            target_date=date(2026, 1, 1) + timedelta(days=days),
            methodology=methodology,
        )

    # --- WATERFALL -------------------------------------------------------
    def test_waterfall_creates_four_sequential_phases(self):
        project = self._make_project(dm.Project.Methodology.WATERFALL)
        result = MethodologyPostProcessor.run(project, actor=self.user)
        self.assertEqual(result["items_created"], 4)
        phases = list(project.phases.order_by("position"))
        self.assertEqual(len(phases), 4)
        self.assertEqual(
            [p.name for p in phases],
            ["Études", "Conception", "Réalisation", "Recette"],
        )
        # Phases séquentielles : start_date croissante, dernière finit à target_date.
        for i in range(1, 4):
            self.assertGreaterEqual(phases[i].start_date, phases[i - 1].start_date)
        self.assertEqual(phases[-1].end_date, project.target_date)

    def test_waterfall_is_idempotent(self):
        project = self._make_project(dm.Project.Methodology.WATERFALL)
        MethodologyPostProcessor.run(project, actor=self.user)
        # Second run : ne doit pas créer de doublons.
        result = MethodologyPostProcessor.run(project, actor=self.user)
        self.assertEqual(result["items_created"], 0)
        self.assertEqual(project.phases.count(), 4)

    # --- FIELD -----------------------------------------------------------
    def test_field_creates_one_initial_report(self):
        project = self._make_project(dm.Project.Methodology.FIELD)
        result = MethodologyPostProcessor.run(project, actor=self.user)
        self.assertEqual(result["items_created"], 1)
        reports = list(project.field_reports.all())
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].report_date, project.start_date)

    def test_field_is_idempotent(self):
        project = self._make_project(dm.Project.Methodology.FIELD)
        MethodologyPostProcessor.run(project, actor=self.user)
        result = MethodologyPostProcessor.run(project, actor=self.user)
        self.assertEqual(result["items_created"], 0)

    # --- REAL_ESTATE -----------------------------------------------------
    def test_real_estate_creates_three_template_lots(self):
        project = self._make_project(dm.Project.Methodology.REAL_ESTATE)
        result = MethodologyPostProcessor.run(project, actor=self.user)
        self.assertEqual(result["items_created"], 3)
        lots = list(project.real_estate_lots.order_by("lot_number"))
        self.assertEqual(len(lots), 3)
        self.assertEqual({l.status for l in lots},
                         {dm.RealEstateLot.LotStatus.AVAILABLE})

    def test_real_estate_is_idempotent(self):
        project = self._make_project(dm.Project.Methodology.REAL_ESTATE)
        MethodologyPostProcessor.run(project, actor=self.user)
        result = MethodologyPostProcessor.run(project, actor=self.user)
        self.assertEqual(result["items_created"], 0)

    # --- ADMINISTRATIVE --------------------------------------------------
    def test_administrative_creates_template_case(self):
        project = self._make_project(dm.Project.Methodology.ADMINISTRATIVE)
        result = MethodologyPostProcessor.run(project, actor=self.user)
        self.assertEqual(result["items_created"], 1)
        cases = list(project.admin_cases.all())
        self.assertEqual(len(cases), 1)
        case = cases[0]
        self.assertEqual(case.status, dm.AdminCase.CaseStatus.DRAFT)
        # deadline = requested_at + sla_days (30 par défaut)
        self.assertIsNotNone(case.requested_at)
        self.assertEqual(case.deadline,
                         case.requested_at + timedelta(days=case.sla_days))

    def test_administrative_is_idempotent(self):
        project = self._make_project(dm.Project.Methodology.ADMINISTRATIVE)
        MethodologyPostProcessor.run(project, actor=self.user)
        result = MethodologyPostProcessor.run(project, actor=self.user)
        self.assertEqual(result["items_created"], 0)

    # --- Modes sans post-processing -------------------------------------
    def test_agile_is_noop(self):
        project = self._make_project(dm.Project.Methodology.AGILE)
        result = MethodologyPostProcessor.run(project, actor=self.user)
        self.assertEqual(result.get("items_created", 0), 0)
        self.assertEqual(project.phases.count(), 0)
        self.assertEqual(project.field_reports.count(), 0)
        self.assertEqual(project.real_estate_lots.count(), 0)
        self.assertEqual(project.admin_cases.count(), 0)

    def test_scrum_is_noop(self):
        project = self._make_project(dm.Project.Methodology.SCRUM)
        result = MethodologyPostProcessor.run(project, actor=self.user)
        self.assertEqual(result.get("items_created", 0), 0)

    def test_kanban_is_noop(self):
        project = self._make_project(dm.Project.Methodology.KANBAN)
        result = MethodologyPostProcessor.run(project, actor=self.user)
        self.assertEqual(result.get("items_created", 0), 0)

    def test_milestone_is_noop(self):
        project = self._make_project(dm.Project.Methodology.MILESTONE)
        result = MethodologyPostProcessor.run(project, actor=self.user)
        self.assertEqual(result.get("items_created", 0), 0)
