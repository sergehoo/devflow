"""
Tests Phase 5 PR22 — Rapports IA hebdomadaires.

Couvre :
    * Génération heuristique (AI_BACKEND="none")
    * Idempotence : 2× generate sur même (project, period, period_start)
                    retourne le même rapport, ne crée pas de doublon
    * Persistance du status READY, used_provider, generated_at
    * Endpoint cross-tenant bloqué (404)
    * ViewSet read-only liste les rapports du workspace user uniquement

Lance avec :
    python manage.py test project.tests_ai_reports
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from project import models as dm
from project.services.ai.services.project_report import ProjectAIReportService

User = get_user_model()


@override_settings(AI_BACKEND="none")
class ProjectAIReportServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="reporter", email="r@example.com", password="x",
        )
        cls.workspace = dm.Workspace.objects.create(
            name="WS Reports", owner=cls.user,
        )
        cls.project = dm.Project.objects.create(
            workspace=cls.workspace, name="Projet Report",
            owner=cls.user,
            start_date=date.today(),
            target_date=date.today() + timedelta(days=30),
        )

    def test_generate_default_period_creates_ready_report(self):
        result = ProjectAIReportService.generate(self.project, use_ai=True)
        self.assertIsNotNone(result.report_id)
        self.assertEqual(result.used_provider, "heuristic")

        report = dm.ProjectAIReport.objects.get(pk=result.report_id)
        self.assertEqual(report.status, "READY")
        self.assertIn("Rapport semaine", report.title)
        # Markdown contient les 5 sections
        for section in ["Résumé exécutif", "Avancement", "Risques",
                        "Recommandations", "KPIs"]:
            self.assertIn(section, report.content_markdown)
        self.assertIsNotNone(report.generated_at)
        self.assertEqual(report.workspace_id, self.workspace.pk)

    def test_generate_is_idempotent(self):
        r1 = ProjectAIReportService.generate(self.project, use_ai=True)
        r2 = ProjectAIReportService.generate(self.project, use_ai=True)
        self.assertEqual(r1.report_id, r2.report_id)
        # Une seule ligne en base sur la même période
        self.assertEqual(
            dm.ProjectAIReport.objects.filter(project=self.project).count(),
            1,
        )

    def test_generate_with_explicit_period(self):
        start = date(2026, 1, 5)   # lundi
        end = date(2026, 1, 11)    # dimanche
        result = ProjectAIReportService.generate(
            self.project, period="WEEKLY",
            period_start=start, period_end=end, use_ai=True,
        )
        report = dm.ProjectAIReport.objects.get(pk=result.report_id)
        self.assertEqual(report.period_start, start)
        self.assertEqual(report.period_end, end)

    def test_summary_extracted_from_markdown(self):
        result = ProjectAIReportService.generate(self.project, use_ai=True)
        self.assertTrue(result.summary)
        # La 1re phrase non-vide hors titre doit être présente
        report = dm.ProjectAIReport.objects.get(pk=result.report_id)
        self.assertTrue(report.summary)


# ---------------------------------------------------------------------------
# Endpoints DRF + cross-tenant
# ---------------------------------------------------------------------------
@override_settings(AI_BACKEND="none")
class ProjectAIReportEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user_a = User.objects.create_user(
            username="alice_rep", email="ar@example.com", password="pw-a-r",
        )
        cls.workspace_a = dm.Workspace.objects.create(
            name="WS A R", owner=cls.user_a,
        )
        dm.UserProfile.objects.create(user=cls.user_a, workspace=cls.workspace_a)
        cls.project_a = dm.Project.objects.create(
            workspace=cls.workspace_a, name="Projet A Report",
            owner=cls.user_a,
            start_date=date.today(),
            target_date=date.today() + timedelta(days=30),
        )

        cls.user_b = User.objects.create_user(
            username="bob_rep", email="br@example.com", password="pw-b-r",
        )
        cls.workspace_b = dm.Workspace.objects.create(
            name="WS B R", owner=cls.user_b,
        )
        dm.UserProfile.objects.create(user=cls.user_b, workspace=cls.workspace_b)
        cls.project_b = dm.Project.objects.create(
            workspace=cls.workspace_b, name="Projet B Report",
            owner=cls.user_b,
            start_date=date.today(),
            target_date=date.today() + timedelta(days=30),
        )

    def _login(self, username, password):
        client = Client()
        self.assertTrue(client.login(username=username, password=password))
        return client

    def test_generate_action_creates_report(self):
        client = self._login("alice_rep", "pw-a-r")
        resp = client.post(
            f"/api/v1/projects/{self.project_a.pk}/ai/report/generate/",
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertIsNotNone(data["report_id"])
        self.assertIn("content_markdown", data)

    def test_generate_action_cross_tenant_blocked(self):
        client = self._login("alice_rep", "pw-a-r")
        resp = client.post(
            f"/api/v1/projects/{self.project_b.pk}/ai/report/generate/",
        )
        self.assertIn(resp.status_code, (403, 404))

    def test_list_endpoint_scoped_workspace(self):
        # Génère un rapport pour chaque projet
        ProjectAIReportService.generate(self.project_a, use_ai=True)
        ProjectAIReportService.generate(self.project_b, use_ai=True)

        client = self._login("alice_rep", "pw-a-r")
        resp = client.get("/api/v1/project-ai-reports/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        project_ids = [r["project"] for r in data.get("results", data)]
        self.assertIn(self.project_a.pk, project_ids)
        self.assertNotIn(self.project_b.pk, project_ids)
