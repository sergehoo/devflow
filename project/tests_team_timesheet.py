"""
Tests ciblés : onboarding employés, hiérarchie N+1/N+2, workflow timesheet,
quota, relances et rapport hebdomadaire.

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_team_timesheet
"""

import json
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from project import models as dm
from project.services import timesheet_reminders as tr
from project.services import timesheet_workflow as tw
from project.services.team_onboarding import onboard_employee

User = get_user_model()
MONDAY = date(2026, 10, 5)  # lundi
FRIDAY = MONDAY + timedelta(days=4)
Status = dm.TimesheetEntry.ApprovalStatus


@override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
class Fixture(TestCase):
    """
    WS A : owner (DG) ← lead ← dev, dev2 ; owner ← lead2 ← ops
    WS B : outsider (autre tenant)
    """

    @classmethod
    def setUpTestData(cls):
        # Users créés avant les workspaces : le signal ne crée aucun profil.
        cls.owner = User.objects.create_user("owner", "owner@a.test", "pw-12345678", first_name="Dana", last_name="DG")
        cls.owner_b = User.objects.create_user("ownerb", "ownerb@b.test", "pw-12345678")
        cls.ws = dm.Workspace.objects.create(name="WS A", owner=cls.owner)
        cls.ws_b = dm.Workspace.objects.create(name="WS B", owner=cls.owner_b)
        cls.dev_team = dm.Team.objects.create(workspace=cls.ws, name="Dev")
        cls.infra_team = dm.Team.objects.create(workspace=cls.ws, name="Infra")
        cls.project = dm.Project.objects.create(workspace=cls.ws, name="Projet A")

        cls.owner_p = cls._member(cls.owner, cls.ws, None, None)
        cls.lead, cls.lead_p = cls._user("lead", cls.ws, cls.dev_team, cls.owner_p, first="Léa", last="Lead")
        cls.dev, cls.dev_p = cls._user("dev", cls.ws, cls.dev_team, cls.lead_p, first="Jean", last="Dev")
        cls.dev2, cls.dev2_p = cls._user("dev2", cls.ws, cls.infra_team, cls.lead_p, first="Luc", last="Dev")
        cls.lead2, cls.lead2_p = cls._user("lead2", cls.ws, cls.infra_team, cls.owner_p, first="Max", last="Lead")
        cls.ops, cls.ops_p = cls._user("ops", cls.ws, cls.infra_team, cls.lead2_p, first="Ops", last="One")
        cls.outsider, cls.outsider_p = cls._user("outsider", cls.ws_b, None, None)

        for user in User.objects.all():
            dm.NotificationPreference.objects.update_or_create(
                user=user, defaults={"quiet_hours_start": 0, "quiet_hours_end": 0},
            )

    @classmethod
    def _member(cls, user, ws, team, manager_profile, capacity=40):
        profile = dm.UserProfile.objects.create(
            user=user, workspace=ws, manager=manager_profile, capacity_hours_per_week=capacity,
        )
        dm.TeamMembership.objects.create(workspace=ws, user=user, team=team)
        return profile

    @classmethod
    def _user(cls, username, ws, team, manager_profile, first="", last=""):
        user = User.objects.create_user(
            username, f"{username}@{'a' if ws.name == 'WS A' else 'b'}.test", "pw-12345678",
            first_name=first, last_name=last,
        )
        return user, cls._member(user, ws, team, manager_profile)

    def entry(self, user, day, hours, status=Status.DRAFT):
        return dm.TimesheetEntry.objects.create(
            user=user, workspace=self.ws, project=self.project, entry_date=day,
            hours=Decimal(str(hours)), description="Dev", approval_status=status,
        )

    def fill_week(self, user, total):
        per_day = Decimal(str(total)) / 5
        for i in range(5):
            self.entry(user, MONDAY + timedelta(days=i), per_day)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Membres / employés
# ─────────────────────────────────────────────────────────────────────────────
class EmployeeOnboardingTests(Fixture):
    url = reverse("team_membership_create")

    def _post(self, **data):
        base = {
            "mode": "new", "role": "DEVELOPER", "weekly_capacity": "35",
            "arrival_date": "2026-10-01", "team": self.dev_team.pk,
        }
        base.update(data)
        return self.client.post(self.url, base)

    @mock.patch("project.tasks.send_invitation_email_task.delay")
    def test_create_new_employee_without_admin(self, delay):
        self.client.force_login(self.owner)
        with self.captureOnCommitCallbacks(execute=True):
            resp = self._post(
                first_name="Awa", last_name="Koné", email="Awa.Kone@a.test",
                job_title="Développeuse", manager=self.lead.pk,
            )
        self.assertEqual(resp.status_code, 302)
        user = User.objects.get(email="awa.kone@a.test")
        self.assertFalse(user.is_active)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(user.profile.workspace, self.ws)
        self.assertEqual(user.profile.manager, self.lead_p)
        self.assertEqual(user.profile.capacity_hours_per_week, Decimal("35"))
        self.assertEqual(user.profile.joined_company_at, date(2026, 10, 1))
        self.assertTrue(dm.TeamMembership.objects.filter(
            workspace=self.ws, team=self.dev_team, user=user, job_title="Développeuse").exists())
        inv = dm.WorkspaceInvitation.objects.get(workspace=self.ws, email=user.email)
        self.assertEqual(inv.status, dm.WorkspaceInvitation.Status.PENDING)
        self.assertGreaterEqual(len(inv.token), 40)
        self.assertLess(inv.expires_at, timezone.now() + timedelta(days=8))
        delay.assert_called_once()

    def test_attach_existing_workspace_user(self):
        self.client.force_login(self.owner)
        resp = self._post(mode="existing", user=self.dev.pk, team=self.infra_team.pk,
                          weekly_capacity="32", manager=self.lead2.pk)
        self.assertEqual(resp.status_code, 302)
        self.dev_p.refresh_from_db()
        self.assertEqual(self.dev_p.manager, self.lead2_p)
        self.assertEqual(self.dev_p.capacity_hours_per_week, Decimal("32"))
        self.assertTrue(dm.TeamMembership.objects.filter(user=self.dev, team=self.infra_team).exists())

    def test_email_must_be_unique(self):
        self.client.force_login(self.owner)
        resp = self._post(first_name="X", last_name="Y", email="DEV@a.test")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("email", resp.context["form"].errors)
        self.assertEqual(User.objects.filter(email__iexact="dev@a.test").count(), 1)

    def test_users_and_managers_limited_to_current_workspace(self):
        self.client.force_login(self.owner)
        resp = self._post(mode="existing", user=self.outsider.pk)
        self.assertIn("user", resp.context["form"].errors)
        resp = self._post(first_name="A", last_name="B", email="new@a.test", manager=self.outsider.pk)
        self.assertIn("manager", resp.context["form"].errors)
        self.assertFalse(User.objects.filter(email="new@a.test").exists())

    def test_self_management_and_cycle_rejected_in_form(self):
        self.client.force_login(self.owner)
        resp = self._post(mode="existing", user=self.lead.pk, team=self.infra_team.pk, manager=self.lead.pk)
        self.assertIn("manager", resp.context["form"].errors)
        # lead ← dev : faire de dev le manager de lead créerait un cycle
        resp = self._post(mode="existing", user=self.lead.pk, team=self.infra_team.pk, manager=self.dev.pk)
        self.assertIn("manager", resp.context["form"].errors)

    def test_member_without_permission_is_forbidden(self):
        self.client.force_login(self.dev)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    @mock.patch("project.tasks.send_invitation_email_task.delay")
    def test_activation_link_activates_account(self, _delay):
        with self.captureOnCommitCallbacks(execute=True):
            _m, inv = onboard_employee(
                workspace=self.ws, actor=self.owner, team=self.dev_team,
                first_name="Nina", last_name="New", email="nina@a.test", manager_user=self.lead,
            )
        url = reverse("workspace_invitation_public_accept", args=[inv.token])
        self.assertEqual(self.client.get(url).context["pending_user"].email, "nina@a.test")
        resp = self.client.post(url, {"first_name": "Nina", "last_name": "New", "password": "s3cret-pass"})
        self.assertEqual(resp.status_code, 302)
        user = User.objects.get(email="nina@a.test")
        self.assertTrue(user.is_active)
        self.assertTrue(user.check_password("s3cret-pass"))
        inv.refresh_from_db()
        self.assertEqual(inv.status, dm.WorkspaceInvitation.Status.ACCEPTED)

    @mock.patch("project.tasks.send_invitation_email_task.delay")
    def test_expired_invitation_cannot_activate(self, _delay):
        with self.captureOnCommitCallbacks(execute=True):
            _m, inv = onboard_employee(
                workspace=self.ws, actor=self.owner, first_name="Old", last_name="Inv", email="old@a.test",
            )
        inv.expires_at = timezone.now() - timedelta(minutes=1)
        inv.save()
        url = reverse("workspace_invitation_public_accept", args=[inv.token])
        self.client.post(url, {"password": "s3cret-pass"})
        self.assertFalse(User.objects.get(email="old@a.test").is_active)


# ─────────────────────────────────────────────────────────────────────────────
# Hiérarchie
# ─────────────────────────────────────────────────────────────────────────────
class HierarchyTests(Fixture):
    def test_chain_n1_n2_derived(self):
        self.assertEqual(self.dev_p.management_chain(), [self.lead_p, self.owner_p])
        self.assertEqual(self.dev_p.manager_at_level(1), self.lead_p)
        self.assertEqual(self.dev_p.manager_at_level(2), self.owner_p)
        self.assertIsNone(self.dev_p.manager_at_level(3))
        reports = {p.pk for p in self.owner_p.all_reports()}
        self.assertEqual(reports, {self.lead_p.pk, self.dev_p.pk, self.dev2_p.pk, self.lead2_p.pk, self.ops_p.pk})

    def test_cycle_forbidden(self):
        self.owner_p.manager = self.dev_p  # dev → lead → owner → dev
        with self.assertRaises(ValidationError):
            self.owner_p.full_clean()

    def test_self_management_forbidden(self):
        self.dev_p.manager = self.dev_p
        with self.assertRaises(ValidationError):
            self.dev_p.full_clean()

    def test_manager_must_be_in_same_workspace(self):
        self.dev_p.manager = self.outsider_p
        with self.assertRaises(ValidationError):
            self.dev_p.full_clean()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Timesheet
# ─────────────────────────────────────────────────────────────────────────────
class TimesheetWorkflowTests(Fixture):
    validate_url = reverse("timesheet_week_validate")

    def setUp(self):
        self.fill_week(self.dev, 40)

    def statuses(self, user=None):
        return set(tw.week_entries(user or self.dev, self.ws, MONDAY).values_list("approval_status", flat=True))

    def _action(self, actor, action, user=None, comment=""):
        self.client.force_login(actor)
        return self.client.post(self.validate_url, {
            "user": (user or self.dev).pk, "monday": MONDAY.isoformat(), "action": action, "comment": comment,
        })

    def test_submit_then_n1_approves_and_week_is_locked(self):
        self._action(self.dev, "submit")
        self.assertEqual(self.statuses(), {Status.SUBMITTED})
        self.assertTrue(dm.Notification.objects.filter(recipient=self.lead, title__icontains="valider").exists())

        self._action(self.lead, "approve")
        self.assertEqual(self.statuses(), {Status.APPROVED})
        actions = list(dm.TimesheetApprovalLog.objects.filter(employee=self.dev).values_list("action", flat=True))
        self.assertEqual(sorted(actions), ["APPROVED", "SUBMITTED"])
        with self.assertRaises(tw.TimesheetWorkflowError):
            tw.assert_week_editable(self.dev, self.ws, MONDAY)

        self.client.force_login(self.dev)
        resp = self.client.post(
            reverse("timesheet_calendar_save"),
            data=json.dumps({"project_id": self.project.pk, "description": "Dev",
                             "date": MONDAY.isoformat(), "hours": "2"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_only_direct_manager_can_validate(self):
        tw.submit_week(self.dev, self.ws, MONDAY)
        for actor in (self.owner, self.dev2, self.lead2, self.dev):  # N+2, pair, autre manager, soi-même
            self._action(actor, "approve")
            self.assertEqual(self.statuses(), {Status.SUBMITTED}, actor.username)
        with self.assertRaises(tw.TimesheetWorkflowError):
            tw.review_week(self.owner, self.dev, self.ws, MONDAY, approve=True)

    def test_other_workspace_cannot_reach_timesheet(self):
        tw.submit_week(self.dev, self.ws, MONDAY)
        resp = self._action(self.outsider, "approve")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(self.statuses(), {Status.SUBMITTED})

    def test_reject_requires_comment_then_correction_and_resubmit(self):
        tw.submit_week(self.dev, self.ws, MONDAY)
        self._action(self.lead, "reject")
        self.assertEqual(self.statuses(), {Status.SUBMITTED})  # commentaire obligatoire
        self._action(self.lead, "reject", comment="Détailler mardi")
        self.assertEqual(self.statuses(), {Status.REJECTED})
        log = dm.TimesheetApprovalLog.objects.filter(employee=self.dev).first()
        self.assertEqual((log.action, log.comment, log.actor), ("REJECTED", "Détailler mardi", self.lead))

        # Correction : une modification remet toute la semaine en brouillon
        self.client.force_login(self.dev)
        resp = self.client.post(
            reverse("timesheet_calendar_save"),
            data=json.dumps({"project_id": self.project.pk, "description": "Dev",
                             "date": (MONDAY + timedelta(days=1)).isoformat(), "hours": "6"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.statuses(), {Status.DRAFT})
        self._action(self.dev, "submit")
        self.assertEqual(self.statuses(), {Status.SUBMITTED})

    def test_list_visibility_self_and_reports_only(self):
        self.fill_week(self.dev2, 10)
        self.client.force_login(self.dev2)
        users = {g["user"].pk for g in self.client.get(reverse("timesheet_entry_list")).context["weekly_groups"]}
        self.assertEqual(users, {self.dev2.pk})
        self.client.force_login(self.lead)
        groups = self.client.get(reverse("timesheet_entry_list")).context["weekly_groups"]
        self.assertEqual({g["user"].pk for g in groups}, {self.dev.pk, self.dev2.pk})
        self.assertTrue(all(g["can_review"] for g in groups))


class QuotaTests(Fixture):
    def test_quota_from_capacity_and_arrival(self):
        self.dev_p.capacity_hours_per_week = Decimal("32")
        self.dev_p.save()
        self.assertEqual(tw.expected_hours(self.dev, self.ws, MONDAY), Decimal("32.00"))
        self.assertEqual(tw.expected_hours(self.dev, self.ws, MONDAY, upto=MONDAY + timedelta(days=1)), Decimal("12.80"))
        self.dev_p.joined_company_at = MONDAY + timedelta(days=2)  # arrivée mercredi
        self.dev_p.save()
        self.assertEqual(tw.expected_hours(self.dev, self.ws, MONDAY), Decimal("19.20"))

    def test_week_summary_totals(self):
        self.entry(self.dev, MONDAY, 8)
        self.entry(self.dev, MONDAY + timedelta(days=1), 6)
        dm.TimesheetEntry.objects.filter(user=self.dev).update(planned_hours=Decimal("8"))
        summary = tw.week_summary(self.dev, self.ws, MONDAY)
        self.assertEqual(summary.total_hours, Decimal("14"))
        self.assertEqual(summary.planned_hours, Decimal("16"))
        self.assertEqual(summary.day_totals[MONDAY], Decimal("8"))
        self.assertEqual(summary.completion_percent, 35)
        self.assertEqual(summary.missing_hours, Decimal("26"))


# ─────────────────────────────────────────────────────────────────────────────
# 3. Relances
# ─────────────────────────────────────────────────────────────────────────────
class ReminderTests(Fixture):
    def _mails_to(self, user):
        return [m for m in mail.outbox if user.email in m.to]

    def test_daily_reminder_only_for_missing_and_no_duplicates(self):
        for user in (self.owner, self.lead, self.dev2, self.lead2, self.ops):
            self.entry(user, MONDAY, 8)
        mail.outbox = []
        tr.send_daily_reminders(MONDAY)
        self.assertEqual(len(self._mails_to(self.dev)), 1)
        self.assertEqual(len(self._mails_to(self.dev2)), 0)
        tr.send_daily_reminders(MONDAY)
        self.assertEqual(len(self._mails_to(self.dev)), 1)
        self.assertEqual(dm.TimesheetReminderLog.objects.filter(user=self.dev).count(), 1)
        self.assertEqual(tr.send_daily_reminders(MONDAY + timedelta(days=5)), {"skipped": "weekend"})

    def test_daily_reminder_respects_preferences(self):
        dm.NotificationPreference.objects.filter(user=self.dev).update(channel_email=False)
        mail.outbox = []
        tr.send_daily_reminders(MONDAY)
        self.assertEqual(self._mails_to(self.dev), [])
        self.assertTrue(dm.Notification.objects.filter(recipient=self.dev, title__icontains="non renseigné").exists())

    def test_weekly_incomplete_and_critical_alerts(self):
        for user in (self.owner, self.lead, self.lead2, self.ops):
            self.fill_week(user, 40)
        self.fill_week(self.dev, 20)
        mail.outbox = []
        tr.send_weekly_checks(FRIDAY)
        logs = dm.TimesheetReminderLog.objects.filter(workspace=self.ws)
        self.assertEqual(set(logs.values_list("user__username", "kind")),
                         {("dev", "WEEKLY_INCOMPLETE"), ("dev2", "WEEKLY_MISSING")})
        self.assertIn("incomplet", self._mails_to(self.dev)[0].subject)
        self.assertIn("CRITIQUE", self._mails_to(self.dev2)[0].subject)
        lead_subjects = [m.subject for m in self._mails_to(self.lead)]
        self.assertTrue(any("Jean Dev" in s for s in lead_subjects))
        self.assertTrue(any("CRITIQUE" in s and "Luc Dev" in s for s in lead_subjects))
        count = len(mail.outbox)
        tr.send_weekly_checks(FRIDAY)
        self.assertEqual(len(mail.outbox), count)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Rapport managers
# ─────────────────────────────────────────────────────────────────────────────
class WeeklyReportTests(Fixture):
    def setUp(self):
        self.fill_week(self.lead, 40)
        self.fill_week(self.dev, 35)
        self.fill_week(self.dev2, 28)
        self.fill_week(self.lead2, 40)
        self.fill_week(self.owner, 40)
        tw.submit_week(self.lead, self.ws, MONDAY)
        tw.review_week(self.owner, self.lead, self.ws, MONDAY, approve=True)
        self.late_task = dm.Task.objects.create(
            workspace=self.ws, project=self.project, title="API paiement",
            assignee=self.dev, due_date=MONDAY + timedelta(days=2),
        )

    def test_consolidated_report_for_top_manager(self):
        mail.outbox = []
        tr.send_weekly_reports(FRIDAY)
        body = [m for m in mail.outbox if self.owner.email in m.to and "consolidé" in m.subject][0].body
        self.assertIn("Dev : 94%", body)       # (40 + 35) / 80
        self.assertIn("Infra : 57%", body)     # (28 + 40 + 0) / 120
        self.assertIn("Jean Dev : 35h/40h", body)
        self.assertIn("Luc Dev : 28h/40h", body)
        self.assertIn("Ops One", body)          # absent
        self.assertIn("API paiement", body)

    def test_n1_receives_only_his_team_and_no_duplicates(self):
        mail.outbox = []
        tr.send_weekly_reports(FRIDAY)
        body = [m for m in mail.outbox if self.lead.email in m.to][0].body
        self.assertIn("Jean Dev : 35h/40h", body)
        self.assertIn("Luc Dev : 28h/40h", body)
        self.assertNotIn("Ops One", body)
        self.assertIn("API paiement", body)
        logs = dm.TimesheetReminderLog.objects.filter(workspace=self.ws)
        self.assertEqual(set(logs.values_list("user__username", "kind")), {
            ("owner", "WEEKLY_REPORT_TOP"),
            ("lead", "WEEKLY_REPORT_MANAGER"),
            ("lead2", "WEEKLY_REPORT_MANAGER"),
        })
        count = len(mail.outbox)
        tr.send_weekly_reports(FRIDAY)
        self.assertEqual(len(mail.outbox), count)
