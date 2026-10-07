"""
Fiches « Membre d'équipe » et « Équipe ».

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_team_pages
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from project import models as dm
from project.services import timesheet_workflow as tw

User = get_user_model()


@override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
class TeamPagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("owner", "owner@a.test", "pw", first_name="Olga", last_name="Owner")
        cls.lead = User.objects.create_user("lead", "lead@a.test", "pw", first_name="Léa", last_name="Lead")
        cls.dev = User.objects.create_user("dev", "dev@a.test", "pw", first_name="Jean-Blaise", last_name="Anoble")
        cls.peer = User.objects.create_user("peer", "peer@a.test", "pw", first_name="Paul", last_name="Peer")
        cls.outsider = User.objects.create_user("bob", "bob@b.test", "pw")
        cls.ws = dm.Workspace.objects.create(name="DATARIUM", owner=cls.owner)
        cls.ws_b = dm.Workspace.objects.create(name="Autre", owner=cls.outsider)
        cls.team = dm.Team.objects.create(
            workspace=cls.ws, name="Backend-Developer Team", lead=cls.lead,
            description='<p class="p1">&Eacute;quipe charg&eacute;e du backend.</p><script>alert(1)</script>',
        )
        owner_p = dm.UserProfile.objects.create(user=cls.owner, workspace=cls.ws)
        lead_p = dm.UserProfile.objects.create(user=cls.lead, workspace=cls.ws, manager=owner_p)
        dm.UserProfile.objects.create(user=cls.dev, workspace=cls.ws, manager=lead_p, capacity_hours_per_week=40)
        dm.UserProfile.objects.create(user=cls.peer, workspace=cls.ws)
        dm.UserProfile.objects.create(user=cls.outsider, workspace=cls.ws_b)
        dm.TeamMembership.objects.create(workspace=cls.ws, user=cls.owner)
        dm.TeamMembership.objects.create(workspace=cls.ws, user=cls.lead, team=cls.team, role="TECH_LEAD")
        cls.dev_m = dm.TeamMembership.objects.create(
            workspace=cls.ws, user=cls.dev, team=cls.team, job_title="Développeur backend", current_load_percent=65,
        )
        dm.TeamMembership.objects.create(workspace=cls.ws, user=cls.peer, team=cls.team)
        dm.TeamMembership.objects.create(workspace=cls.ws_b, user=cls.outsider)

        cls.project = dm.Project.objects.create(workspace=cls.ws, name="Portail RH", team=cls.team, progress_percent=40)
        dm.ProjectMember.objects.create(project=cls.project, user=cls.dev, role="Back-end", allocation_percent=80)
        dm.Task.objects.create(
            workspace=cls.ws, project=cls.project, title="API congés", assignee=cls.dev,
            due_date=timezone.localdate() - timedelta(days=1),
        )
        monday, _ = tw.week_bounds(timezone.localdate())
        dm.TimesheetEntry.objects.create(
            user=cls.dev, workspace=cls.ws, project=cls.project, entry_date=monday, hours=Decimal("8"),
        )

    def test_member_page_for_manager(self):
        self.client.force_login(self.owner)
        resp = self.client.get(reverse("team_membership_detail", args=[self.dev_m.pk]))
        self.assertEqual(resp.status_code, 200)
        for text in ("Jean-Blaise Anoble", "Développeur backend", "Backend-Developer Team", "API congés",
                     "1 en retard", "Portail RH", "80 % alloué", "Léa Lead", "N+1", "Olga Owner", "N+2",
                     "8 h", "65 %", "/chat/?user=%d" % self.dev.pk):
            self.assertContains(resp, text)
        self.assertContains(resp, reverse("team_membership_password_reset", args=[self.dev_m.pk]))

    def test_member_page_hides_timesheet_and_admin_actions_from_peers(self):
        self.client.force_login(self.peer)
        resp = self.client.get(reverse("team_membership_detail", args=[self.dev_m.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context["week"])
        self.assertContains(resp, "Réservé à la ligne hiérarchique")
        self.assertNotContains(resp, "password-reset")

    def test_member_page_cross_tenant_404(self):
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(reverse("team_membership_detail", args=[self.dev_m.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("team_detail", args=[self.team.pk])).status_code, 404)

    def test_team_page_renders_sanitized_description_and_dashboard(self):
        self.client.force_login(self.owner)
        resp = self.client.get(reverse("team_detail", args=[self.team.pk]))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertNotIn("&lt;p", html)              # plus de HTML échappé affiché
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("Équipe chargée du backend", html)
        for text in ("Jean-Blaise Anoble", "Léa Lead", "Portail RH", "40%", "Membres actifs", "Occupation semaine"):
            self.assertContains(resp, text)
        self.assertEqual(resp.context["open_tasks"], 1)
        self.assertEqual(resp.context["overdue_tasks"], 1)
        self.assertEqual(resp.context["active_count"], 3)
