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


@override_settings(SITE_URL=SITE)
class DigestEmailDesignTests(TestCase):
    def test_digest_uses_devflow_design_and_absolute_links(self):
        from project.services.smart_notifications import send_digest_email_sync

        user = User.objects.create_user("serge2", "serge2@a.test", "pw", first_name="Serge")
        now = timezone.now()
        digest = dm.NotificationDigest.objects.create(
            user=user, period_start=now - timedelta(days=1), period_end=now, notifications_count=125,
            payload={
                "frequency": "DAILY", "total": 125,
                "period_start": (now - timedelta(days=1)).isoformat(), "period_end": now.isoformat(),
                "by_type": [{"type": "TASK", "label": "Tâche", "count": 120}],
                "by_project": [{"project_id": 1, "name": "KAYDAN SHIELD v1", "count": 90}],
                "highlights": [{"title": "Tâche mise à jour — Setup frontend & routing", "body": "", "url": "/tasks/7/"}],
            },
        )
        mail.outbox = []
        self.assertTrue(send_digest_email_sync(user, digest))
        email = mail.outbox[-1]
        html = email.alternatives[0][0]
        self.assertEqual(email.subject, "[DevFlow] Récapitulatif — 125 notifications")
        self.assertIn("DevFlow · Récapitulatif", html)
        self.assertIn("#FF4E00", html)                       # même charte que les autres emails
        self.assertIn(f'href="{SITE}/tasks/7/"', html)
        self.assertIn(f'href="{SITE}/notifications/"', html)
        self.assertIn("124 autres notifications", html)
        self.assertIn("KAYDAN SHIELD v1", html)

    def test_timesheet_daily_reminder_uses_devflow_design(self):
        from datetime import date
        from project.services.timesheet_reminders import send_daily_reminders

        user = User.objects.create_user("serge3", "serge3@a.test", "pw", first_name="Serge")
        ws = dm.Workspace.objects.create(name="DATARIUM", owner=user)
        dm.TeamMembership.objects.create(workspace=ws, user=user)
        dm.NotificationPreference.objects.update_or_create(
            user=user, defaults={"quiet_hours_start": 0, "quiet_hours_end": 0},
        )
        mail.outbox = []
        send_daily_reminders(date(2026, 10, 7))
        email = [m for m in mail.outbox if user.email in m.to][0]
        html = email.alternatives[0][0]
        self.assertIn("DevFlow · Timesheets", html)
        self.assertIn("Saisie attendue", html)
        self.assertIn(f'href="{SITE}/timesheets/?date=2026-10-07"', html)
        self.assertIn("Ouvrir mon timesheet", html)


@override_settings(SITE_URL=SITE)
class PMUpdateEmailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pm = User.objects.create_user("pm", "serge.pm@a.test", "pw", first_name="Serge", last_name="OGAH")
        cls.dev = User.objects.create_user("dev", "fabien@a.test", "pw", first_name="Fabien", last_name="OUREGA")
        cls.ws = dm.Workspace.objects.create(name="KAYDAN", owner=cls.pm)
        for u in (cls.pm, cls.dev):
            dm.UserProfile.objects.create(user=u, workspace=cls.ws)
            dm.TeamMembership.objects.create(user=u, workspace=cls.ws)
            dm.NotificationPreference.objects.update_or_create(
                user=u, defaults={"quiet_hours_start": 0, "quiet_hours_end": 0},
            )
        cls.project = dm.Project.objects.create(workspace=cls.ws, name="G-stock", product_manager=cls.pm)

    def setUp(self):
        self.task = dm.Task.objects.create(
            workspace=self.ws, project=self.project, assignee=self.dev,
            title="Notification GeStock lors création depuis Contrat",
        )

    def complete_as_assignee(self):
        from unittest import mock
        from project.services.task_quick_update import apply_quick_update

        with mock.patch("project.tasks.send_task_pm_update_email_task.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                apply_quick_update(self.task, self.dev, {"status": "DONE"})
        return delay

    def test_pm_notified_with_readable_changes_and_actor(self):
        delay = self.complete_as_assignee()
        delay.assert_called_once()
        task_id, pm_id, changes, actor_name = delay.call_args.args
        self.assertEqual((task_id, pm_id, actor_name), (self.task.pk, self.pm.pk, "Fabien OUREGA"))
        self.assertIn({"label": "Statut", "before": "À faire", "after": "Terminé"}, changes)
        self.assertIn({"label": "Progression", "before": "0 %", "after": "100 %"}, changes)
        notif = dm.Notification.objects.get(recipient=self.pm)
        self.assertEqual(notif.url, f"/tasks/{self.task.pk}/")

    def test_email_design_and_absolute_link(self):
        from project.tasks import send_task_pm_update_email_task

        self.task.status, self.task.progress_percent = "DONE", 100
        self.task.save()
        mail.outbox = []
        send_task_pm_update_email_task.run(
            self.task.pk, self.pm.pk,
            [{"label": "Statut", "before": "À faire", "after": "Terminé"}], "Fabien OUREGA",
        )
        email = mail.outbox[-1]
        html = email.alternatives[0][0]
        self.assertIn("DevFlow · Mise à jour de tâche", html)
        self.assertIn("<strong>Fabien OUREGA</strong> a mis à jour", html)
        self.assertIn(f'href="{SITE}/tasks/{self.task.pk}/"', html)
        self.assertIn("Fabien OUREGA", html)        # responsable affiché par son nom, pas son email
        self.assertNotIn("TODO", html + email.body)
        self.assertIn(f"{SITE}/tasks/{self.task.pk}/", email.body)

    def test_digest_preference_skips_immediate_email(self):
        dm.NotificationPreference.objects.filter(user=self.pm).update(notify_frequency="DAILY")
        delay = self.complete_as_assignee()
        delay.assert_not_called()
        self.assertTrue(dm.Notification.objects.filter(recipient=self.pm).exists())


@override_settings(SITE_URL=SITE)
class MeetingEmailDesignTests(TestCase):
    def test_meeting_reminder_and_minutes_prompt_use_devflow_design(self):
        from project.tasks import send_meeting_reminders_sweep

        org = User.objects.create_user("org", "org@a.test", "pw", first_name="Awa")
        guest = User.objects.create_user("guest", "guest@a.test", "pw")
        ws = dm.Workspace.objects.create(name="KAYDAN", owner=org)
        tomorrow = dm.ProjectMeeting.objects.create(
            workspace=ws, title="Comité hebdo", organizer=org,
            scheduled_at=timezone.now() + timedelta(hours=24), meeting_link="https://meet.example/abc",
        )
        tomorrow.internal_participants.add(guest)
        done = dm.ProjectMeeting.objects.create(
            workspace=ws, title="Revue sprint", organizer=org, scheduled_at=timezone.now() - timedelta(hours=2),
        )
        mail.outbox = []
        send_meeting_reminders_sweep()
        reminder = [m for m in mail.outbox if "guest@a.test" in m.bcc][0]
        html = reminder.alternatives[0][0]
        self.assertIn("DevFlow · Réunions", html)
        self.assertIn('href="https://meet.example/abc"', html)
        prompt = [m for m in mail.outbox if "org@a.test" in m.to][0]
        self.assertIn(f'href="{SITE}/meetings/{done.pk}/"', prompt.alternatives[0][0])
        self.assertIn("Rédiger le compte-rendu", prompt.alternatives[0][0])
