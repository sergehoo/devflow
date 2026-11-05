"""
API équipes & membres (React, Phase 3) : périmètre Django, droits, isolation.

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_api_teams
"""

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from project import models as dm

User = get_user_model()


@override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
class TeamApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("owner", "owner@a.test", "pw", first_name="Olive")
        cls.dev = User.objects.create_user("dev", "dev@a.test", "pw", first_name="Dan")
        cls.bob = User.objects.create_user("bob", "bob@b.test", "pw")
        cls.ws = dm.Workspace.objects.create(name="Alpha", owner=cls.owner)
        cls.other = dm.Workspace.objects.create(name="Beta", owner=cls.bob)
        cls.team = dm.Team.objects.create(workspace=cls.ws, name="Core", lead=cls.owner)
        cls.foreign_team = dm.Team.objects.create(workspace=cls.other, name="Secret")
        owner_p = dm.UserProfile.objects.create(user=cls.owner, workspace=cls.ws)
        dm.UserProfile.objects.create(user=cls.dev, workspace=cls.ws, manager=owner_p, capacity_hours_per_week=35)
        dm.UserProfile.objects.create(user=cls.bob, workspace=cls.other)
        dm.TeamMembership.objects.create(user=cls.owner, workspace=cls.ws, team=cls.team, role="ADMIN")
        cls.dev_m = dm.TeamMembership.objects.create(user=cls.dev, workspace=cls.ws, team=cls.team)
        cls.bob_m = dm.TeamMembership.objects.create(user=cls.bob, workspace=cls.other, team=cls.foreign_team)
        dm.Project.objects.create(workspace=cls.ws, name="Portail", team=cls.team)

    def test_members_scope_filters_and_profile(self):
        self.client.force_login(self.dev)
        data = self.client.get("/api/v1/team-members/").json()
        self.assertEqual({r["user"]["id"] for r in data["results"]}, {self.owner.pk, self.dev.pk})
        dev = next(r for r in data["results"] if r["user"]["id"] == self.dev.pk)
        self.assertEqual((dev["manager"], dev["capacity_hours_per_week"]), ("Olive", 35.0))
        self.assertFalse(data["permissions"]["can_manage_passwords"])
        self.assertEqual(self.client.get("/api/v1/team-members/", {"q": "Olive"}).json()["count"], 1)
        self.assertEqual([t["label"] for t in data["filters"]["teams"]], ["Core"])

    def test_teams_list_overview_and_isolation(self):
        self.client.force_login(self.dev)
        rows = self.client.get("/api/v1/teams/").json()["results"]
        self.assertEqual([(r["name"], r["members_count"], r["projects_count"], r["lead_name"]) for r in rows], [("Core", 2, 1, "Olive")])
        overview = self.client.get(f"/api/v1/teams/{self.team.pk}/overview/").json()
        self.assertEqual([p["name"] for p in overview["projects"]], ["Portail"])
        self.assertEqual(self.client.get(f"/api/v1/teams/{self.foreign_team.pk}/overview/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/v1/forms/team/{self.foreign_team.pk}/").status_code, 404)
        self.assertEqual(self.client.post(f"/api/v1/actions/member-delete/{self.bob_m.pk}/").status_code, 404)
        self.assertEqual(self.client.post(f"/api/v1/actions/member-password-reset/{self.bob_m.pk}/").status_code, 404)

    def test_team_form_create(self):
        self.client.force_login(self.owner)
        schema = {f["name"]: f for f in self.client.get("/api/v1/forms/team/").json()["fields"]}
        payload = {k: ("" if f["value"] is None else f["value"]) for k, f in schema.items() if f["type"] not in ("checkbox", "multiselect", "file")}
        payload.update({"name": "Mobile", "team_type": schema["team_type"]["choices"][-1]["value"]})
        res = self.client.post("/api/v1/forms/team/", payload)
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(dm.Team.objects.get(pk=res.json()["id"]).workspace, self.ws)

    def test_onboarding_form_requires_rights(self):
        self.client.force_login(self.dev)
        self.assertEqual(self.client.get("/api/v1/forms/member/").status_code, 403)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get("/api/v1/forms/member/").status_code, 200)
