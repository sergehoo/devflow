"""
API projets (React, Phase 3) : pont formulaires Django + synthèse + isolation.

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_api_projects
"""

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from project import models as dm

User = get_user_model()
STATIC = "django.contrib.staticfiles.storage.StaticFilesStorage"


@override_settings(STATICFILES_STORAGE=STATIC)
class ProjectApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@a.test", "pw", first_name="Alice")
        cls.bob = User.objects.create_user("bob", "bob@b.test", "pw")
        cls.ws = dm.Workspace.objects.create(name="Alpha", owner=cls.alice)
        cls.other = dm.Workspace.objects.create(name="Beta", owner=cls.bob)
        for user, ws in ((cls.alice, cls.ws), (cls.bob, cls.other)):
            dm.UserProfile.objects.update_or_create(user=user, defaults={"workspace": ws})
            dm.TeamMembership.objects.get_or_create(user=user, workspace=ws)
        cls.team = dm.Team.objects.create(workspace=cls.ws, name="Core")
        cls.foreign_team = dm.Team.objects.create(workspace=cls.other, name="Secret")
        cls.project = dm.Project.objects.create(workspace=cls.ws, name="Portail", owner=cls.alice)
        cls.foreign = dm.Project.objects.create(workspace=cls.other, name="Projet B")
        dm.Task.objects.create(workspace=cls.ws, project=cls.project, title="T1", estimate_hours=4)

    def setUp(self):
        self.client.force_login(self.alice)

    def payload(self, **extra):
        data = {"name": "Nouveau CRM", "methodology": dm.Project.Methodology.choices[0][0],
                "status": dm.Project.Status.PLANNED, "priority": dm.Project.Priority.MEDIUM,
                "health_status": dm.Project.HealthStatus.GRAY, "progress_percent": "0", "team": self.team.pk}
        data.update(extra)
        return data

    def test_form_schema_choices_are_scoped(self):
        res = self.client.get("/api/v1/forms/project/")
        self.assertEqual(res.status_code, 200)
        fields = {f["name"]: f for f in res.json()["fields"]}
        self.assertTrue(fields["name"]["required"])
        team_values = [c["value"] for c in fields["team"]["choices"]]
        self.assertIn(str(self.team.pk), team_values)
        self.assertNotIn(str(self.foreign_team.pk), team_values)

    @mock.patch("project.services.ai.services.methodology_postprocess.MethodologyPostProcessor.run", return_value={})
    def test_create_through_django_form(self, _run):
        res = self.client.post("/api/v1/forms/project/", self.payload())
        self.assertEqual(res.status_code, 201, res.content)
        project = dm.Project.objects.get(pk=res.json()["id"])
        self.assertEqual((project.workspace, project.owner, project.team), (self.ws, self.alice, self.team))
        self.assertTrue(dm.ProjectBudget.objects.filter(project=project).exists())

    def test_create_validation_errors_and_foreign_team_refused(self):
        res = self.client.post("/api/v1/forms/project/", self.payload(name="", team=self.foreign_team.pk))
        self.assertEqual(res.status_code, 400)
        self.assertIn("name", res.json())
        self.assertIn("team", res.json())

    def test_update_and_foreign_project_404(self):
        res = self.client.get(f"/api/v1/forms/project/{self.project.pk}/")
        self.assertEqual({f["name"]: f["value"] for f in res.json()["fields"]}["name"], "Portail")
        res = self.client.post(f"/api/v1/forms/project/{self.project.pk}/", self.payload(name="Portail v2"))
        self.assertEqual(res.status_code, 200, res.content)
        self.project.refresh_from_db()
        self.assertEqual(self.project.name, "Portail v2")
        self.assertEqual(self.client.get(f"/api/v1/forms/project/{self.foreign.pk}/").status_code, 404)
        self.assertEqual(self.client.post(f"/api/v1/forms/project/{self.foreign.pk}/", self.payload()).status_code, 404)

    def test_csrf_enforced_on_form_post(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        client.force_login(self.alice)
        self.assertEqual(client.post("/api/v1/forms/project/", self.payload()).status_code, 403)

    def test_list_labels_summary_and_archive(self):
        rows = self.client.get("/api/v1/projects/", {"search": "Port"}).json()["results"]
        self.assertEqual([r["name"] for r in rows], ["Portail"])
        self.assertTrue(rows[0]["status_label"])
        summary = self.client.get(f"/api/v1/projects/{self.project.pk}/summary/").json()
        self.assertEqual((summary["tasks_total"], summary["estimate_hours"]), (1, 4.0))
        self.assertEqual(self.client.get(f"/api/v1/projects/{self.foreign.pk}/summary/").status_code, 404)
        self.assertEqual(self.client.post(f"/api/v1/projects/{self.foreign.pk}/archive/").status_code, 404)
        self.assertEqual(self.client.post(f"/api/v1/projects/{self.project.pk}/archive/").status_code, 204)
        self.project.refresh_from_db()
        self.assertTrue(self.project.is_archived)
