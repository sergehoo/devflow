"""
Relances de tâches : jamais pour une tâche close / finie / en pause ;
board des tâches non tronqué à 25.

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_task_reminder_scope
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from project import models as dm
from project.services.task_reminder import TaskReminderService

User = get_user_model()


@override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
class ReminderScopeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dev = User.objects.create_user("dev", "dev@a.test", "pw", first_name="Serge")
        cls.ws = dm.Workspace.objects.create(name="A", owner=cls.dev)
        dm.UserProfile.objects.create(user=cls.dev, workspace=cls.ws)
        dm.TeamMembership.objects.create(user=cls.dev, workspace=cls.ws)
        cls.project = dm.Project.objects.create(workspace=cls.ws, name="KAYDAN SHIELD v1", status="IN_PROGRESS")

    def task(self, title, **extra):
        return dm.Task.objects.create(
            workspace=self.ws, project=self.project, assignee=self.dev, title=title,
            due_date=timezone.localdate() - timedelta(days=10), **extra,
        )

    def test_closed_finished_or_snoozed_tasks_never_reminded(self):
        open_task = self.task("Monitoring et alerting")
        self.task("Terminée", status="DONE")
        self.task("Expirée", status="EXPIRED")
        self.task("Finie à 100 %", progress_percent=100)
        self.task("En pause", snoozed_until=timezone.now() + timedelta(days=2))
        mail.outbox = []
        TaskReminderService.run()
        reminded = set(dm.TaskReminder.objects.values_list("task__title", flat=True))
        self.assertEqual(reminded, {open_task.title})

    def test_board_shows_all_tasks(self):
        for i in range(30):
            dm.Task.objects.create(workspace=self.ws, project=self.project, assignee=self.dev, title=f"T{i}")
        self.client.force_login(self.dev)
        resp = self.client.get(reverse("task_list"))
        self.assertEqual(len(resp.context["object_list"]), 30)
        self.assertContains(resp, "T29")
