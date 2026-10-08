"""
Mise à jour rapide des tâches (fiche, liste, kanban).

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_task_quick_update
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from project import models as dm

User = get_user_model()


@override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
class TaskQuickUpdateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("owner", "owner@a.test", "pw")
        cls.dev = User.objects.create_user("dev", "dev@a.test", "pw", first_name="Jean")
        cls.pm = User.objects.create_user("pm", "pm@a.test", "pw")
        cls.outsider = User.objects.create_user("bob", "bob@b.test", "pw")
        cls.ws = dm.Workspace.objects.create(name="A", owner=cls.owner)
        cls.ws_b = dm.Workspace.objects.create(name="B", owner=cls.outsider)
        for user in (cls.owner, cls.dev, cls.pm):
            dm.UserProfile.objects.create(user=user, workspace=cls.ws)
            dm.TeamMembership.objects.create(user=user, workspace=cls.ws)
        dm.UserProfile.objects.create(user=cls.outsider, workspace=cls.ws_b)
        cls.project = dm.Project.objects.create(workspace=cls.ws, name="AFFLUX", product_manager=cls.pm)

    def setUp(self):
        self.task = dm.Task.objects.create(
            workspace=self.ws, project=self.project, title="Logique métier centrale",
            assignee=self.dev, estimate_hours=Decimal("32"),
        )
        self.url = f"/api/v1/tasks/{self.task.pk}/quick-update/"

    def api(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def test_state_for_assignee(self):
        data = self.api(self.dev).get(self.url).json()
        self.assertTrue(data["can_update"])
        self.assertEqual(data["status"], "TODO")
        self.assertIn("BLOCKED", [s["value"] for s in data["statuses"]])

    def test_start_progress_time_and_comment_in_one_call(self):
        resp = self.api(self.dev).post(self.url, {
            "status": "IN_PROGRESS", "progress_percent": 40, "spent_hours": "1.5", "comment": "API branchée",
        }, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.task.refresh_from_db()
        self.assertEqual((self.task.status, self.task.progress_percent), ("IN_PROGRESS", 40))
        self.assertIsNotNone(self.task.started_at)
        self.assertEqual(self.task.spent_hours, Decimal("1.5"))
        entry = dm.TimesheetEntry.objects.get(task=self.task)
        self.assertEqual((entry.user, entry.hours, entry.entry_date), (self.dev, Decimal("1.5"), timezone.localdate()))
        self.assertTrue(dm.TaskComment.objects.filter(task=self.task, body="API branchée").exists())

    def test_done_forces_full_progress(self):
        self.api(self.dev).post(self.url, {"status": "DONE"}, format="json")
        self.task.refresh_from_db()
        self.assertEqual((self.task.status, self.task.progress_percent), ("DONE", 100))
        self.assertIsNotNone(self.task.completed_at)

    def test_blocked_requires_reason(self):
        self.assertEqual(self.api(self.dev).post(self.url, {"status": "BLOCKED"}, format="json").status_code, 400)
        resp = self.api(self.dev).post(self.url, {"status": "BLOCKED", "comment": "En attente des accès"}, format="json")
        self.assertEqual(resp.status_code, 200)

    def test_invalid_input_rolls_back_everything(self):
        resp = self.api(self.dev).post(self.url, {"status": "IN_PROGRESS", "spent_hours": "30"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "TODO")
        self.assertEqual(self.api(self.dev).post(self.url, {"progress_percent": 150}, format="json").status_code, 400)
        self.assertEqual(self.api(self.dev).post(self.url, {}, format="json").status_code, 400)

    def test_only_assignee_and_tenant_isolation(self):
        self.assertFalse(self.api(self.pm).get(self.url).json()["can_update"])
        self.assertEqual(self.api(self.pm).post(self.url, {"status": "DONE"}, format="json").status_code, 403)
        self.assertEqual(self.api(self.outsider).get(self.url).status_code, 404)
        self.assertEqual(self.api(self.outsider).post(self.url, {"status": "DONE"}, format="json").status_code, 404)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "TODO")

    def test_buttons_rendered(self):
        self.client.force_login(self.dev)
        detail = self.client.get(reverse("task_detail", args=[self.task.pk]))
        self.assertContains(detail, "Mise à jour rapide")
        self.assertContains(detail, f"devflowTaskQuickUpdate({{ taskId: {self.task.pk}")
        listing = self.client.get(reverse("task_list"))
        self.assertContains(listing, f"devflowQuickUpdate({self.task.pk}")
        project_page = self.client.get(reverse("project_detail", args=[self.project.pk]))
        self.assertContains(project_page, f"devflowQuickUpdate({self.task.pk}")
