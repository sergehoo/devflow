"""
Déclenchement de la proposition IA : jamais d'erreur 500, bascule sur
l'heuristique si la sortie de l'IA est inexploitable.

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_ai_proposal_trigger
"""

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from project import models as dm
from project.services.ai.services.project_structure import ProjectAIStructureService

User = get_user_model()


@override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
class AIProposalTriggerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("o", "o@a.test", "pw")
        cls.ws = dm.Workspace.objects.create(name="A", owner=cls.owner)
        dm.UserProfile.objects.create(user=cls.owner, workspace=cls.ws)
        dm.TeamMembership.objects.create(user=cls.owner, workspace=cls.ws)
        cls.project = dm.Project.objects.create(workspace=cls.ws, name="G-stock", methodology="SCRUM")

    def test_malformed_ai_output_falls_back_to_heuristic(self):
        bad = {"summary": {"objectif": "stock"}, "risks": ["rupture"], "recommendations": "faire X",
               "phases": "pas une liste", "milestones": [1, None], "tasks": "oops"}
        real = ProjectAIStructureService._instantiate_items
        calls = {"n": 0}

        def flaky(proposal, payload, project):
            calls["n"] += 1
            if calls["n"] == 1:
                raise TypeError("string indices must be integers")
            return real(proposal, payload, project)

        with mock.patch.object(ProjectAIStructureService, "_call_ai", return_value=(bad, "deepseek")), \
                mock.patch.object(ProjectAIStructureService, "_instantiate_items", side_effect=flaky):
            result = ProjectAIStructureService.generate_for_project(project=self.project, triggered_by=self.owner)
        self.assertEqual(result.used_provider, "heuristic")
        self.assertEqual(result.proposal.status, dm.ProjectAIProposal.Status.READY)
        self.assertIn("inexploitable", result.proposal.error_message)

    def test_text_fields_coerced(self):
        self.assertEqual(ProjectAIStructureService._as_text(["a", {"title": "b"}]), "- a\n- b")
        self.assertEqual(ProjectAIStructureService._as_text({"k": "v"}), "k : v")

    def test_unexpected_error_redirects_instead_of_500(self):
        self.client.force_login(self.owner)
        with mock.patch.object(ProjectAIStructureService, "generate_for_project", side_effect=RuntimeError("boom")):
            resp = self.client.post(reverse("project_ai_proposal_trigger", args=[self.project.pk]))
        self.assertRedirects(resp, reverse("project_detail", args=[self.project.pk]), fetch_redirect_response=False)

    def test_form_trigger_ok(self):
        self.client.force_login(self.owner)
        resp = self.client.post(reverse("project_ai_proposal_trigger", args=[self.project.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/ai-proposals/", resp["Location"])
