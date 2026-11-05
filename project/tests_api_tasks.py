"""
API tâches (React, Phase 3) : formulaire Django, ponts d'actions, fiche, isolation.

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_api_tasks
"""

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from project import models as dm

User = get_user_model()


@override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
class TaskApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pm = User.objects.create_user("pm", "pm@a.test", "pw", first_name="Paul")
        cls.dev = User.objects.create_user("dev", "dev@a.test", "pw", first_name="Dana")
        cls.bob = User.objects.create_user("bob", "bob@b.test", "pw")
        cls.ws = dm.Workspace.objects.create(name="Alpha", owner=cls.pm)
        cls.other = dm.Workspace.objects.create(name="Beta", owner=cls.bob)
        for user, ws in ((cls.pm, cls.ws), (cls.dev, cls.ws), (cls.bob, cls.other)):
            dm.UserProfile.objects.update_or_create(user=user, defaults={"workspace": ws})
            dm.TeamMembership.objects.get_or_create(user=user, workspace=ws)
        cls.project = dm.Project.objects.create(workspace=cls.ws, name="Portail", product_manager=cls.pm)
        cls.foreign = dm.Task.objects.create(
            workspace=cls.other, project=dm.Project.objects.create(workspace=cls.other, name="B"), title="Secret",
        )

    def setUp(self):
        self.task = dm.Task.objects.create(workspace=self.ws, project=self.project, title="Écran login", assignee=self.dev)

    def test_list_search_labels_and_isolation(self):
        self.client.force_login(self.dev)
        rows = self.client.get("/api/v1/tasks/", {"search": "Portail", "is_archived": "false"}).json()["results"]
        self.assertEqual([r["title"] for r in rows], ["Écran login"])
        self.assertEqual((rows[0]["project_name"], rows[0]["assignee_name"]), ("Portail", "Dana"))
        self.assertEqual(self.client.get(f"/api/v1/tasks/{self.foreign.pk}/overview/").status_code, 404)

    def test_overview(self):
        dm.TaskComment.objects.create(task=self.task, author=self.pm, body="Bien reçu")
        self.client.force_login(self.dev)
        data = self.client.get(f"/api/v1/tasks/{self.task.pk}/overview/").json()
        self.assertEqual(data["comments"][0]["body"], "Bien reçu")
        self.assertTrue(data["state"]["can_update"])
        self.assertFalse(data["can_arbitrate"])

    def test_task_form_create_and_update(self):
        self.client.force_login(self.pm)
        schema = self.client.get("/api/v1/forms/task/", {"project": self.project.pk}).json()
        fields = {f["name"]: f for f in schema["fields"]}
        self.assertEqual(str(fields["project"]["value"]), str(self.project.pk))
        payload = {f["name"]: "" if f["value"] is None else f["value"] for f in schema["fields"]
                   if f["type"] not in ("checkbox", "multiselect", "file")}
        payload.update({"title": "Nouvelle tâche", "assignee": self.dev.pk})
        res = self.client.post("/api/v1/forms/task/", payload)
        self.assertEqual(res.status_code, 201, res.content)
        created = dm.Task.objects.get(pk=res.json()["id"])
        self.assertEqual((created.workspace, created.project, created.assignee), (self.ws, self.project, self.dev))
        self.assertEqual(self.client.get(f"/api/v1/forms/task/{self.foreign.pk}/").status_code, 404)

    def test_comment_action_is_assignee_only(self):
        self.client.force_login(self.pm)
        res = self.client.post(f"/api/v1/actions/task-comment/{self.task.pk}/", {"body": "Je commente"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("assignée à un autre", res.json()["detail"])
        self.client.force_login(self.dev)
        res = self.client.post(f"/api/v1/actions/task-comment/{self.task.pk}/", {"body": "Fait"})
        self.assertEqual(res.status_code, 200, res.content)
        self.assertTrue(dm.TaskComment.objects.filter(task=self.task, body="Fait").exists())

    def test_actions_isolation_and_arbitration(self):
        self.client.force_login(self.dev)
        self.assertEqual(self.client.post(f"/api/v1/actions/task-flag/{self.foreign.pk}/").status_code, 404)
        res = self.client.post(f"/api/v1/actions/task-extend/{self.task.pk}/", {"due_date": "2030-01-01"})
        self.assertIn(res.status_code, (400, 403))
        self.task.refresh_from_db()
        self.assertIsNone(self.task.due_date)
        self.assertEqual(self.client.post("/api/v1/actions/unknown/1/").status_code, 404)
