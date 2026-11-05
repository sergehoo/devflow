"""
API workspaces (React, Phase 3) : isolation et mêmes droits que les vues Django.

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_api_workspaces
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from project import models as dm

User = get_user_model()


class WorkspaceApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("owner", "owner@a.test", "pw")
        cls.member = User.objects.create_user("member", "member@a.test", "pw")
        cls.stranger = User.objects.create_user("stranger", "s@b.test", "pw")
        cls.ws = dm.Workspace.objects.create(name="Alpha", owner=cls.owner)
        cls.other = dm.Workspace.objects.create(name="Beta", owner=cls.stranger)
        for user, ws in ((cls.owner, cls.ws), (cls.member, cls.ws), (cls.stranger, cls.other)):
            dm.UserProfile.objects.update_or_create(user=user, defaults={"workspace": ws})
            dm.TeamMembership.objects.get_or_create(user=user, workspace=ws)
        dm.Project.objects.create(workspace=cls.ws, name="Portail")

    def url(self, ws=None, suffix=""):
        return f"/api/v1/workspaces/{ws.pk}/{suffix}" if ws else "/api/v1/workspaces/"

    def test_list_is_scoped_and_annotated(self):
        self.client.force_login(self.member)
        data = self.client.get(self.url()).json()
        rows = data["results"] if isinstance(data, dict) else data
        self.assertEqual([r["name"] for r in rows], ["Alpha"])
        self.assertEqual(rows[0]["projects_count"], 1)
        self.assertEqual(rows[0]["memberships_count"], 2)
        self.assertFalse(rows[0]["can_manage"])

    def test_foreign_workspace_is_404(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(self.url(self.other)).status_code, 404)
        self.assertEqual(self.client.get(self.url(self.other, "overview/")).status_code, 404)
        res = self.client.patch(self.url(self.other), {"name": "Pwned"}, content_type="application/json")
        self.assertEqual(res.status_code, 404)

    def test_member_cannot_update_archive_or_delete(self):
        self.client.force_login(self.member)
        res = self.client.patch(self.url(self.ws), {"name": "Renommé"}, content_type="application/json")
        self.assertEqual(res.status_code, 403)
        self.assertEqual(self.client.post(self.url(self.ws, "archive/")).status_code, 403)
        self.assertEqual(self.client.delete(self.url(self.ws)).status_code, 403)
        self.ws.refresh_from_db()
        self.assertEqual((self.ws.name, self.ws.is_archived), ("Alpha", False))

    def test_owner_updates_and_archives(self):
        self.client.force_login(self.owner)
        res = self.client.patch(self.url(self.ws), {"quarter_label": "T4 2026"}, content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertTrue(res.json()["can_manage"])
        overview = self.client.get(self.url(self.ws, "overview/")).json()
        self.assertEqual([p["name"] for p in overview["projects"]], ["Portail"])
        self.assertEqual(self.client.post(self.url(self.ws, "archive/")).status_code, 204)
        self.ws.refresh_from_db()
        self.assertTrue(self.ws.is_archived)

    def test_create_sets_owner(self):
        self.client.force_login(self.member)
        res = self.client.post(self.url(), {"name": "Gamma"}, content_type="application/json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(dm.Workspace.objects.get(name="Gamma").owner, self.member)
