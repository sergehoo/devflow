"""
Liens des emails : toujours absolus (un lien relatif ne fonctionne pas dans
un client mail — bug du bouton « Mettre à jour la tâche »).

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_email_links
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from project import models as dm
from project.services.task_reminder import TaskReminderService
from project.tasks import send_task_assignment_email_task
from project.utils.urls import absolute_url, site_base_url

User = get_user_model()
SITE = "https://flow.datarium-dev.com"


class SiteUrlTests(TestCase):
    @override_settings(SITE_URL=SITE + "/")
    def test_site_url_has_priority(self):
        self.assertEqual(absolute_url("/tasks/42/"), f"{SITE}/tasks/42/")

    @override_settings(SITE_URL="", CSRF_TRUSTED_ORIGINS=["http://flow.datarium-dev.com", SITE])
    def test_fallback_on_https_trusted_origin(self):
        self.assertEqual(site_base_url(), SITE)

    @override_settings(SITE_URL="", CSRF_TRUSTED_ORIGINS=[], ALLOWED_HOSTS=["localhost", "flow.datarium-dev.com"])
    def test_fallback_on_public_allowed_host(self):
        self.assertEqual(site_base_url(), SITE)

    def test_absolute_urls_untouched(self):
        self.assertEqual(absolute_url("https://x.test/a/"), "https://x.test/a/")


@override_settings(SITE_URL=SITE)
class TaskEmailLinkTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("serge", "serge@a.test", "pw", first_name="Serge")
        cls.ws = dm.Workspace.objects.create(name="KAYDAN", owner=cls.user)
        cls.project = dm.Project.objects.create(workspace=cls.ws, name="KAYDAN SHIELD v1")
        cls.task = dm.Task.objects.create(
            workspace=cls.ws, project=cls.project, title="Monitoring et alerting", assignee=cls.user,
            due_date=timezone.localdate() - timedelta(days=3),
        )

    def test_reminder_button_links_to_task(self):
        mail.outbox = []
        TaskReminderService._send_assignee_reminder(self.task, dm.TaskReminder.Reason.OVERDUE, 3)
        email = mail.outbox[-1]
        html = email.alternatives[0][0]
        self.assertIn(f'href="{SITE}/tasks/{self.task.pk}/"', html)
        self.assertIn(f"{SITE}/tasks/{self.task.pk}/", email.body)

    def test_assignment_email_links_to_task(self):
        mail.outbox = []
        send_task_assignment_email_task(self.task.pk, self.user.pk)
        email = mail.outbox[-1]
        self.assertIn(f'href="{SITE}/tasks/{self.task.pk}/"', email.alternatives[0][0])
        self.assertIn(f"{SITE}/tasks/{self.task.pk}/", email.body)
