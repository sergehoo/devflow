"""Régressions : temps rapide et actions limitées à l'assigné courant."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from project import models as dm


User = get_user_model()


@override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
class TaskQuickTimeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("owner-time", "owner-time@example.test", "pw")
        cls.assignee = User.objects.create_user("assignee-time", "assignee-time@example.test", "pw")
        cls.peer = User.objects.create_user("peer-time", "peer-time@example.test", "pw")
        cls.workspace = dm.Workspace.objects.create(name="Temps", owner=cls.owner)
        for user in (cls.owner, cls.assignee, cls.peer):
            dm.UserProfile.objects.create(user=user, workspace=cls.workspace)
            dm.TeamMembership.objects.create(user=user, workspace=cls.workspace)
        cls.project = dm.Project.objects.create(workspace=cls.workspace, name="Projet temps")

    def setUp(self):
        self.task = dm.Task.objects.create(
            workspace=self.workspace,
            project=self.project,
            title="Préparer la livraison",
            assignee=self.assignee,
        )

    def api(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def test_kanban_move_records_time_in_assignee_timesheet(self):
        response = self.api(self.assignee).post(
            f"/api/v1/tasks/{self.task.pk}/move-kanban/",
            {"status": dm.Task.Status.IN_PROGRESS, "position": 1, "spent_hours": "1.5"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        entry = dm.TimesheetEntry.objects.get(task=self.task, user=self.assignee)
        self.assertEqual((entry.hours, entry.entry_date), (Decimal("1.5"), timezone.localdate()))
        self.task.refresh_from_db()
        self.assertEqual((self.task.status, self.task.spent_hours), (dm.Task.Status.IN_PROGRESS, Decimal("1.5")))

    def test_other_workspace_member_cannot_update_or_log_time_for_task(self):
        response = self.api(self.peer).post(
            f"/api/v1/tasks/{self.task.pk}/move-kanban/",
            {"status": dm.Task.Status.DONE, "position": 0, "spent_hours": "2"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, dm.Task.Status.TODO)
        self.assertFalse(dm.TimesheetEntry.objects.filter(task=self.task).exists())

    def test_main_kanban_move_records_time(self):
        self.client.force_login(self.assignee)
        response = self.client.post(
            reverse("task_kanban_move", args=[self.task.pk]),
            {"status": dm.Task.Status.REVIEW, "position": "0", "spent_hours": "0.75"},
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            dm.TimesheetEntry.objects.get(task=self.task, user=self.assignee).hours,
            Decimal("0.75"),
        )

    def test_toggle_complete_adds_time_without_creating_a_duplicate_entry(self):
        dm.TimesheetEntry.objects.create(
            user=self.assignee,
            workspace=self.workspace,
            project=self.project,
            task=self.task,
            entry_date=timezone.localdate(),
            hours=Decimal("2"),
        )

        response = self.api(self.assignee).post(
            f"/api/v1/tasks/{self.task.pk}/toggle-complete/",
            {"spent_hours": "0.5"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        entries = dm.TimesheetEntry.objects.filter(task=self.task, user=self.assignee)
        self.assertEqual(entries.count(), 1)
        self.assertEqual(entries.get().hours, Decimal("2.5"))
        self.task.refresh_from_db()
        self.assertEqual((self.task.status, self.task.spent_hours), (dm.Task.Status.DONE, Decimal("2.5")))

    def test_completion_does_not_duplicate_time_logged_before_reassignment(self):
        dm.TimesheetEntry.objects.create(
            user=self.peer,
            workspace=self.workspace,
            project=self.project,
            task=self.task,
            entry_date=timezone.localdate(),
            hours=Decimal("2"),
        )

        response = self.api(self.assignee).post(
            f"/api/v1/tasks/{self.task.pk}/toggle-complete/",
            {"spent_hours": "1"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            dm.TimesheetEntry.objects.filter(task=self.task).aggregate(total=Sum("hours"))["total"],
            Decimal("3"),
        )
