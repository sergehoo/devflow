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
class TeamPagesFixture(TestCase):
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



class TeamPagesTests(TeamPagesFixture):
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


class TeamDescriptionFormattingTests(TeamPagesFixture):
    """Descriptions saisies en texte riche (HTML + entités) : jamais affichées en HTML brut."""

    def api(self, user):
        from rest_framework.test import APIClient

        client = APIClient()
        client.force_authenticate(user)
        return client

    def test_plain_text_filter(self):
        from project.templatetags.devflow_extras import has_markup, plain_text

        self.assertEqual(plain_text('<p class="p1">&Eacute;quipe charg&eacute;e</p><p>R&amp;D</p>'), "Équipe chargée\nR&D")
        self.assertEqual(plain_text("<p><br>Intro</p><ul><li>Un</li><li>Deux</li></ul>"), "Intro\n\n• Un\n• Deux")
        self.assertEqual(plain_text("&lt;p&gt;Double &amp;eacute;&lt;/p&gt;"), "Double é")  # HTML doublement encodé
        self.assertEqual(plain_text("<p>ok</p><script>alert(1)</script><style>p{}</style>"), "ok")
        self.assertEqual(plain_text("a < b et c > d"), "a < b et c > d")
        self.assertEqual(plain_text("Texte\nsur deux lignes"), "Texte\nsur deux lignes")
        self.assertEqual(plain_text(None), "")
        self.assertTrue(has_markup("&Eacute;quipe"))
        self.assertFalse(has_markup("R&D sans balise"))

    def test_api_returns_sanitized_html_and_plain_text(self):
        data = self.api(self.peer).get(f"/api/v1/teams/{self.team.pk}/").json()
        self.assertIn("Équipe chargée du backend.", data["description_html"])
        self.assertIn("<p", data["description_html"])
        self.assertNotIn("<script", data["description_html"])
        self.assertEqual(data["description_text"], "Équipe chargée du backend.")
        listing = self.api(self.peer).get("/api/v1/teams/").json()
        rows = listing.get("results", listing)
        self.assertEqual(next(t for t in rows if t["id"] == self.team.pk)["description_text"], "Équipe chargée du backend.")

    def test_react_form_shows_readable_description(self):
        response = self.api(self.owner).get(f"/api/v1/forms/team/{self.team.pk}/")
        self.assertEqual(response.status_code, 200, response.content)
        fields = {f["name"]: f for f in response.json()["fields"]}
        self.assertEqual(fields["description"]["value"], "Équipe chargée du backend.")

    def test_django_team_list_shows_plain_excerpt(self):
        self.client.force_login(self.owner)
        html = self.client.get(reverse("team_list")).content.decode()
        self.assertIn("Équipe chargée du backend.", html)
        self.assertNotIn("&lt;p", html)
        self.assertNotIn("&amp;Eacute;", html)

    def test_archive_is_reserved_to_team_administration(self):
        response = self.api(self.peer).post(f"/api/v1/actions/team-archive/{self.team.pk}/")
        self.assertEqual(response.status_code, 403)
        self.client.force_login(self.lead)
        self.assertEqual(self.client.post(reverse("team_archive", args=[self.team.pk])).status_code, 403)
        self.team.refresh_from_db()
        self.assertFalse(self.team.is_archived)
        self.assertEqual(self.api(self.owner).post(f"/api/v1/actions/team-archive/{self.team.pk}/").status_code, 200)
        self.team.refresh_from_db()
        self.assertTrue(self.team.is_archived)
        # Hors workspace : introuvable.
        self.assertEqual(self.api(self.outsider).post(f"/api/v1/actions/team-archive/{self.team.pk}/").status_code, 404)

    def test_react_form_never_turns_an_empty_color_black(self):
        dm.Team.objects.filter(pk=self.team.pk).update(color="")
        fields = {f["name"]: f for f in self.api(self.owner).get(f"/api/v1/forms/team/{self.team.pk}/").json()["fields"]}
        self.assertEqual((fields["color"]["type"], fields["color"]["value"]), ("color", "#7C6FF7"))
        dm.Team.objects.filter(pk=self.team.pk).update(color="#0EA5E9")
        fields = {f["name"]: f for f in self.api(self.owner).get(f"/api/v1/forms/team/{self.team.pk}/").json()["fields"]}
        self.assertEqual(fields["color"]["value"], "#0EA5E9")
