"""
Tests Phase 4 — IA V2 (PR18-19-20).

Couvre :
    * AIQuotaService : get_or_create, can_consume, record_usage, reset
    * AIPromptLibrary : get_prompt (workspace > default), render safe
    * Endpoints ai/summary, ai/recommendations, ai/generate-roadmap
      (heuristique uniquement — pas d'appel IA réel via AI_BACKEND="none")
    * Cross-tenant : un user ne peut pas appeler ces endpoints sur W2

Lance avec :
    python manage.py test project.tests_ai_v2
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from project import models as dm
from project.services.ai.quota import (
    AIPromptLibrary,
    AIQuotaService,
)

User = get_user_model()


class AIQuotaServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="quotauser", email="q@example.com", password="x",
        )
        cls.workspace = dm.Workspace.objects.create(
            name="WS Quota", owner=cls.user,
        )

    def test_get_or_create_quota_is_idempotent(self):
        q1 = AIQuotaService.get_or_create_quota(self.workspace)
        q2 = AIQuotaService.get_or_create_quota(self.workspace)
        self.assertEqual(q1.pk, q2.pk)

    def test_can_consume_allowed_under_limit(self):
        result = AIQuotaService.can_consume(self.workspace, estimated_tokens=100)
        self.assertTrue(result.allowed)
        self.assertGreater(result.remaining, 0)

    def test_can_consume_refused_above_limit(self):
        quota = AIQuotaService.get_or_create_quota(self.workspace)
        quota.monthly_token_limit = 100
        quota.monthly_tokens_used = 95
        quota.save()
        result = AIQuotaService.can_consume(self.workspace, estimated_tokens=50)
        self.assertFalse(result.allowed)

    def test_record_usage_increments_counter(self):
        AIQuotaService.record_usage(self.workspace, 250)
        AIQuotaService.record_usage(self.workspace, 350)
        quota = AIQuotaService.get_or_create_quota(self.workspace)
        self.assertEqual(quota.monthly_tokens_used, 600)
        self.assertIsNotNone(quota.last_call_at)

    def test_unlimited_quota(self):
        quota = AIQuotaService.get_or_create_quota(self.workspace)
        quota.monthly_token_limit = 0
        quota.save()
        result = AIQuotaService.can_consume(self.workspace, estimated_tokens=10**8)
        self.assertTrue(result.allowed)

    def test_period_reset_when_expired(self):
        quota = AIQuotaService.get_or_create_quota(self.workspace)
        quota.monthly_tokens_used = 999_999
        quota.period_start = date.today() - timedelta(days=31)
        quota.save()
        AIQuotaService.reset_if_period_expired(quota)
        quota.refresh_from_db()
        self.assertEqual(quota.monthly_tokens_used, 0)
        self.assertEqual(quota.period_start, date.today())


class AIPromptLibraryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="prompts", email="p@example.com", password="x",
        )
        cls.workspace = dm.Workspace.objects.create(
            name="WS Prompts", owner=cls.user,
        )

    def test_default_used_when_no_template(self):
        result = AIPromptLibrary.get_prompt(
            "project_summary", self.workspace, default="DEFAULT-PROMPT",
        )
        self.assertEqual(result, "DEFAULT-PROMPT")

    def test_workspace_template_overrides_default(self):
        dm.AIPromptTemplate.objects.create(
            workspace=self.workspace,
            name="Custom summary",
            intent="project_summary",
            template="CUSTOM {project_name}",
            is_default=True,
        )
        result = AIPromptLibrary.get_prompt(
            "project_summary", self.workspace, default="DEFAULT",
        )
        self.assertEqual(result, "CUSTOM {project_name}")

    def test_is_default_wins_over_most_recent(self):
        dm.AIPromptTemplate.objects.create(
            workspace=self.workspace, name="Old default",
            intent="project_summary", template="A", is_default=True,
        )
        dm.AIPromptTemplate.objects.create(
            workspace=self.workspace, name="Newer non-default",
            intent="project_summary", template="B", is_default=False,
        )
        result = AIPromptLibrary.get_prompt(
            "project_summary", self.workspace, default="DEFAULT",
        )
        self.assertEqual(result, "A")

    def test_render_substitutes_variables(self):
        out = AIPromptLibrary.render(
            "Hello {name}, project {project} is {status}.",
            name="Alice", project="DevFlow", status="OK",
        )
        self.assertEqual(out, "Hello Alice, project DevFlow is OK.")

    def test_render_safe_on_missing_variable(self):
        """Variable manquante = on laisse le placeholder brut, pas d'erreur."""
        out = AIPromptLibrary.render(
            "Hello {name}, missing {ghost}.",
            name="Alice",
        )
        self.assertEqual(out, "Hello Alice, missing {ghost}.")


# ---------------------------------------------------------------------------
# Endpoints DRF (heuristique uniquement — AI_BACKEND="none")
# ---------------------------------------------------------------------------
@override_settings(AI_BACKEND="none")
class PhaseFourEndpointsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # User + workspace + projet pour user A
        cls.user_a = User.objects.create_user(
            username="alice4", email="a4@example.com", password="pw-a-4",
        )
        cls.workspace_a = dm.Workspace.objects.create(
            name="WS A", owner=cls.user_a,
        )
        dm.UserProfile.objects.create(user=cls.user_a, workspace=cls.workspace_a)
        cls.project_a = dm.Project.objects.create(
            workspace=cls.workspace_a, name="Projet A4",
            owner=cls.user_a,
            start_date=date.today(),
            target_date=date.today() + timedelta(days=30),
        )

        # User B + workspace B isolé pour les tests cross-tenant
        cls.user_b = User.objects.create_user(
            username="bob4", email="b4@example.com", password="pw-b-4",
        )
        cls.workspace_b = dm.Workspace.objects.create(
            name="WS B", owner=cls.user_b,
        )
        dm.UserProfile.objects.create(user=cls.user_b, workspace=cls.workspace_b)
        cls.project_b = dm.Project.objects.create(
            workspace=cls.workspace_b, name="Projet B4",
            owner=cls.user_b,
            start_date=date.today(),
            target_date=date.today() + timedelta(days=30),
        )

    def _login(self, username, password):
        from django.test import Client
        client = Client()
        ok = client.login(username=username, password=password)
        self.assertTrue(ok)
        return client

    def test_summary_endpoint_returns_payload(self):
        client = self._login("alice4", "pw-a-4")
        resp = client.get(f"/api/v1/projects/{self.project_a.pk}/ai/summary/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["project_id"], self.project_a.pk)
        self.assertIn("summary", data)
        # AI_BACKEND=none → fallback heuristique
        self.assertEqual(data["used_provider"], "heuristic")

    def test_summary_cross_tenant_blocked(self):
        client = self._login("alice4", "pw-a-4")
        resp = client.get(f"/api/v1/projects/{self.project_b.pk}/ai/summary/")
        self.assertIn(resp.status_code, (403, 404))

    def test_recommendations_endpoint_returns_list(self):
        client = self._login("alice4", "pw-a-4")
        resp = client.get(f"/api/v1/projects/{self.project_a.pk}/ai/recommendations/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("recommendations", data)
        self.assertIsInstance(data["recommendations"], list)
        # Au moins 1 reco heuristique
        self.assertGreaterEqual(len(data["recommendations"]), 1)

    def test_recommendations_cross_tenant_blocked(self):
        client = self._login("alice4", "pw-a-4")
        resp = client.get(f"/api/v1/projects/{self.project_b.pk}/ai/recommendations/")
        self.assertIn(resp.status_code, (403, 404))

    def test_generate_roadmap_cross_tenant_blocked(self):
        client = self._login("alice4", "pw-a-4")
        resp = client.post(f"/api/v1/projects/{self.project_b.pk}/ai/generate-roadmap/")
        self.assertIn(resp.status_code, (403, 404))
