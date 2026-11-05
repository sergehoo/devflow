"""
API tableau de bord (React, Phase 3) : mêmes données que la vue Django,
limitées au workspace courant.

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_api_dashboard
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from project import models as dm

User = get_user_model()


class DashboardSummaryApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@a.test", "pw", first_name="Alice")
        cls.bob = User.objects.create_user("bob", "bob@b.test", "pw")
        cls.ws_a = dm.Workspace.objects.create(name="Alpha", owner=cls.alice)
        cls.ws_b = dm.Workspace.objects.create(name="Beta", owner=cls.bob)
        for user, ws in ((cls.alice, cls.ws_a), (cls.bob, cls.ws_b)):
            dm.UserProfile.objects.update_or_create(user=user, defaults={"workspace": ws})
            dm.TeamMembership.objects.get_or_create(user=user, workspace=ws)
        cls.project_a = dm.Project.objects.create(workspace=cls.ws_a, name="Portail A")
        cls.project_b = dm.Project.objects.create(workspace=cls.ws_b, name="Secret B")
        dm.Task.objects.create(
            workspace=cls.ws_a, project=cls.project_a, title="Livrer A", assignee=cls.alice,
            due_date=timezone.localdate() + timedelta(days=2),
        )
        dm.Task.objects.create(
            workspace=cls.ws_b, project=cls.project_b, title="Tâche B",
            due_date=timezone.localdate() + timedelta(days=2),
        )

    def test_requires_authentication(self):
        self.assertIn(self.client.get(reverse("api-dashboard-summary")).status_code, (401, 403))

    def test_summary_is_scoped_to_current_workspace(self):
        self.client.force_login(self.alice)
        res = self.client.get(reverse("api-dashboard-summary"))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["workspace"]["id"], self.ws_a.pk)
        self.assertEqual([p["name"] for p in data["projects"]], ["Portail A"])
        self.assertEqual([t["title"] for t in data["due_soon_tasks"]], ["Livrer A"])
        self.assertEqual(data["stats"]["projects_total"], 1)
        self.assertIn("approved_budget_total", data["finance"])
        self.assertNotIn("Secret B", res.content.decode())
        self.assertNotIn("Tâche B", res.content.decode())
