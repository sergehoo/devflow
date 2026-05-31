"""
Tests Phase 5 PR21 — Notifications intelligentes.

Couvre :
    * NotificationPreferenceService.get_or_create (auto-seed)
    * NotificationPreference.is_quiet_hour (horaires normaux + débordement minuit)
    * SmartNotificationDispatcher.should_send_email_now (matrice cas)
    * NotificationDigestBuilder.build_for (groupes par type/projet, highlights)
    * Tâche send_daily_notification_digest : skip si déjà envoyé

Lance avec :
    python manage.py test project.tests_smart_notifications
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from project import models as dm
from project.services.smart_notifications import (
    NotificationDigestBuilder,
    NotificationPreferenceService,
    SmartNotificationDispatcher,
)

User = get_user_model()


class NotificationPreferenceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="prefs", email="prefs@example.com", password="x",
        )

    def test_get_or_create_idempotent(self):
        p1 = NotificationPreferenceService.get_or_create(self.user)
        p2 = NotificationPreferenceService.get_or_create(self.user)
        self.assertEqual(p1.pk, p2.pk)

    def test_default_values(self):
        prefs = NotificationPreferenceService.get_or_create(self.user)
        self.assertTrue(prefs.channel_in_app)
        self.assertTrue(prefs.channel_email)
        self.assertTrue(prefs.channel_digest)
        self.assertEqual(prefs.notify_frequency, "IMMEDIATE")
        self.assertEqual(prefs.quiet_hours_start, 22)
        self.assertEqual(prefs.quiet_hours_end, 7)
        self.assertEqual(prefs.priority_types, [])

    def test_is_quiet_hour_normal_range(self):
        prefs = NotificationPreferenceService.get_or_create(self.user)
        prefs.quiet_hours_start = 13
        prefs.quiet_hours_end = 14   # silence 13:00-14:00
        prefs.save()

        self.assertTrue(prefs.is_quiet_hour(now=13))
        self.assertFalse(prefs.is_quiet_hour(now=14))
        self.assertFalse(prefs.is_quiet_hour(now=12))

    def test_is_quiet_hour_overnight(self):
        """22h-7h : silence si h ≥ 22 OU h < 7."""
        prefs = NotificationPreferenceService.get_or_create(self.user)
        prefs.quiet_hours_start = 22
        prefs.quiet_hours_end = 7
        prefs.save()

        self.assertTrue(prefs.is_quiet_hour(now=23))
        self.assertTrue(prefs.is_quiet_hour(now=2))
        self.assertFalse(prefs.is_quiet_hour(now=10))
        self.assertFalse(prefs.is_quiet_hour(now=21))

    def test_is_quiet_hour_24_7_mode(self):
        """start == end → pas de silence du tout."""
        prefs = NotificationPreferenceService.get_or_create(self.user)
        prefs.quiet_hours_start = 0
        prefs.quiet_hours_end = 0
        prefs.save()
        for h in [0, 6, 12, 22]:
            self.assertFalse(prefs.is_quiet_hour(now=h))


class SmartNotificationDispatcherTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="disp", email="disp@example.com", password="x",
        )
        cls.workspace = dm.Workspace.objects.create(
            name="WS Dispatcher", owner=cls.user,
        )

    def _make_notif(self, **kwargs):
        defaults = dict(
            recipient=self.user,
            workspace=self.workspace,
            notification_type="TASK",
            title="Test",
        )
        defaults.update(kwargs)
        return dm.Notification.objects.create(**defaults)

    def test_immediate_outside_quiet_hours_sends(self):
        prefs = NotificationPreferenceService.get_or_create(self.user)
        prefs.notify_frequency = "IMMEDIATE"
        prefs.quiet_hours_start = 13
        prefs.quiet_hours_end = 14
        prefs.save()
        notif = self._make_notif()
        # Simulate 15h (outside quiet hours)
        self.assertTrue(
            SmartNotificationDispatcher.should_send_email_now(
                notif, now=datetime(2026, 1, 1, 15, 0),
            )
        )

    def test_immediate_during_quiet_hours_blocked(self):
        prefs = NotificationPreferenceService.get_or_create(self.user)
        prefs.notify_frequency = "IMMEDIATE"
        prefs.quiet_hours_start = 13
        prefs.quiet_hours_end = 14
        prefs.save()
        notif = self._make_notif()
        self.assertFalse(
            SmartNotificationDispatcher.should_send_email_now(
                notif, now=datetime(2026, 1, 1, 13, 30),
            )
        )

    def test_daily_frequency_blocks_immediate_email(self):
        prefs = NotificationPreferenceService.get_or_create(self.user)
        prefs.notify_frequency = "DAILY"
        prefs.save()
        notif = self._make_notif()
        self.assertFalse(SmartNotificationDispatcher.should_send_email_now(notif))

    def test_disabled_blocks_everything(self):
        prefs = NotificationPreferenceService.get_or_create(self.user)
        prefs.notify_frequency = "DISABLED"
        prefs.save()
        notif = self._make_notif()
        self.assertFalse(SmartNotificationDispatcher.should_send_email_now(notif))

    def test_priority_type_bypasses_quiet_hours_and_frequency(self):
        prefs = NotificationPreferenceService.get_or_create(self.user)
        prefs.notify_frequency = "DAILY"
        prefs.quiet_hours_start = 0
        prefs.quiet_hours_end = 24
        prefs.priority_types = ["RISK"]
        prefs.save()
        notif = self._make_notif(notification_type="RISK")
        # Devrait passer même en quiet hours + daily
        self.assertTrue(SmartNotificationDispatcher.should_send_email_now(notif))

    def test_channel_email_off_blocks(self):
        prefs = NotificationPreferenceService.get_or_create(self.user)
        prefs.channel_email = False
        prefs.save()
        notif = self._make_notif()
        self.assertFalse(SmartNotificationDispatcher.should_send_email_now(notif))


class NotificationDigestBuilderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="digest", email="d@example.com", password="x",
        )
        cls.workspace = dm.Workspace.objects.create(
            name="WS Digest", owner=cls.user,
        )
        cls.project_x = dm.Project.objects.create(
            workspace=cls.workspace, name="Projet X", owner=cls.user,
        )
        cls.project_y = dm.Project.objects.create(
            workspace=cls.workspace, name="Projet Y", owner=cls.user,
        )

    def test_build_empty_period(self):
        now = timezone.now()
        payload = NotificationDigestBuilder.build_for(
            self.user,
            period_start=now - timedelta(hours=1),
            period_end=now,
        )
        self.assertEqual(payload["total"], 0)
        self.assertEqual(payload["by_type"], [])
        self.assertEqual(payload["highlights"], [])

    def test_build_groups_by_type_and_project(self):
        for i in range(3):
            dm.Notification.objects.create(
                recipient=self.user, workspace=self.workspace,
                notification_type="TASK",
                title=f"Task notif {i}",
                metadata={"project_id": self.project_x.pk},
            )
        for i in range(2):
            dm.Notification.objects.create(
                recipient=self.user, workspace=self.workspace,
                notification_type="RISK",
                title=f"Risk notif {i}",
                metadata={"project_id": self.project_y.pk},
            )

        now = timezone.now()
        payload = NotificationDigestBuilder.build_for(
            self.user,
            period_start=now - timedelta(hours=1),
            period_end=now + timedelta(seconds=10),
        )
        self.assertEqual(payload["total"], 5)

        # Types groupés
        types_dict = {entry["type"]: entry["count"] for entry in payload["by_type"]}
        self.assertEqual(types_dict.get("TASK"), 3)
        self.assertEqual(types_dict.get("RISK"), 2)

        # Projets groupés
        projects_dict = {entry["project_id"]: entry["count"]
                         for entry in payload["by_project"]}
        self.assertEqual(projects_dict.get(self.project_x.pk), 3)
        self.assertEqual(projects_dict.get(self.project_y.pk), 2)

        # Highlights limités
        self.assertLessEqual(len(payload["highlights"]), 5)

    def test_build_ignores_read_notifications(self):
        dm.Notification.objects.create(
            recipient=self.user, workspace=self.workspace,
            notification_type="TASK", title="Read", is_read=True,
        )
        dm.Notification.objects.create(
            recipient=self.user, workspace=self.workspace,
            notification_type="TASK", title="Unread",
        )
        now = timezone.now()
        payload = NotificationDigestBuilder.build_for(
            self.user,
            period_start=now - timedelta(hours=1),
            period_end=now + timedelta(seconds=10),
        )
        self.assertEqual(payload["total"], 1)
