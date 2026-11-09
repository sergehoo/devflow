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


class DashboardInsightsApiTests(TestCase):
    """GET /api/v1/dashboard/insights/ : agrégats réels du workspace courant uniquement."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.alice = User.objects.create_user("alice", "alice@a.test", "pw", first_name="Alice")
        cls.carl = User.objects.create_user("carl", "carl@a.test", "pw")
        cls.bob = User.objects.create_user("bob", "bob@b.test", "pw")
        cls.ws_a = dm.Workspace.objects.create(name="Alpha", owner=cls.alice)
        cls.ws_b = dm.Workspace.objects.create(name="Beta", owner=cls.bob)
        for user, ws in ((cls.alice, cls.ws_a), (cls.carl, cls.ws_a), (cls.bob, cls.ws_b)):
            dm.UserProfile.objects.update_or_create(user=user, defaults={"workspace": ws})
            dm.TeamMembership.objects.get_or_create(user=user, workspace=ws)
        S = dm.Project.Status
        mkp = lambda ws, name, status, risk=0: dm.Project.objects.filter(  # noqa: E731
            pk=dm.Project.objects.create(workspace=ws, name=name, status=status).pk)
        for name, status, risk in (("Portail", S.IN_PROGRESS, 10), ("Risqué", S.IN_PROGRESS, 80), ("Bloqué", S.BLOCKED, 0),
                                   ("En retard", S.DELAYED, 90), ("Fini", S.DONE, 0)):
            mkp(cls.ws_a, name, status).update(risk_score=risk)  # risk_score est recalculé à l'enregistrement
        mkp(cls.ws_b, "Secret", S.DELAYED).update(risk_score=0)
        cls.ok = dm.Project.objects.get(name="Portail")
        cls.foreign = dm.Project.objects.get(name="Secret")
        dm.ProjectMember.objects.create(project=cls.ok, user=cls.alice)
        today = timezone.localdate()
        T, P = dm.Task.Status, dm.Task.Priority
        mk = lambda **kw: dm.Task.objects.create(workspace=cls.ws_a, project=cls.ok, **kw)  # noqa: E731
        cls.low = mk(title="Basse", assignee=cls.alice, priority=P.LOW, due_date=today + timedelta(days=2))
        mk(title="Du jour faite", assignee=cls.alice, status=T.DONE, due_date=today)
        mk(title="Du jour", assignee=cls.alice, due_date=today, priority=P.HIGH)
        cls.crit = mk(title="Critique", assignee=cls.alice, priority=P.CRITICAL, due_date=today - timedelta(days=1))
        mk(title="De Carl", assignee=cls.carl, priority=P.CRITICAL)
        done = mk(title="Faite", assignee=cls.alice, status=T.DONE)
        dm.Task.objects.filter(pk=done.pk).update(completed_at=timezone.now() - timedelta(days=3))
        dm.Task.objects.create(workspace=cls.ws_b, project=cls.foreign, title="Bob", assignee=cls.bob, status=T.DONE,
                               completed_at=timezone.now())
        soon = timezone.now() + timedelta(days=1)
        mine = dm.ProjectMeeting.objects.create(workspace=cls.ws_a, project=cls.ok, title="Comité", scheduled_at=soon, organizer=cls.alice)
        dm.ProjectMeeting.objects.create(workspace=cls.ws_a, title="Réunion de Carl", scheduled_at=soon, organizer=cls.carl)
        dm.Milestone.objects.create(project=cls.ok, name="Recette", due_date=today + timedelta(days=3))
        cls.mine = mine

    def get(self, user, **params):
        self.client.force_login(user)
        return self.client.get("/api/v1/dashboard/insights/", params)

    def test_requires_authentication(self):
        self.assertIn(self.client.get("/api/v1/dashboard/insights/").status_code, (401, 403))

    def test_health_focus_upcoming_and_heatmap_use_real_scoped_data(self):
        data = self.get(self.alice).json()
        self.assertEqual(data["health"], {"active": 4, "on_track": 1, "at_risk": 2, "delayed": 1, "healthy_percent": 25})
        self.assertEqual([t["title"] for t in data["focus"]], ["Critique", "Du jour", "Basse"])  # priorité puis échéance, mes tâches
        self.assertTrue(data["focus"][0]["overdue"])
        self.assertEqual(data["overdue_tasks"], 1)
        self.assertEqual(data["day"], {"planned": 2, "done": 1, "completed_today": 1})
        kinds = {(u["kind"], u["title"]) for u in data["upcoming"]}
        self.assertIn(("meeting", "Comité"), kinds)
        self.assertIn(("milestone", "Recette"), kinds)
        self.assertIn(("task", "Basse"), kinds)
        self.assertNotIn(("meeting", "Réunion de Carl"), kinds)
        self.assertEqual(len(data["heatmap"]), 15 * 7)
        self.assertEqual(data["completed_in_period"], 2)  # la tâche de Beta n'est pas comptée
        portail = next(p for p in data["projects"] if p["name"] == "Portail")
        self.assertEqual((portail["health"], portail["members_count"]), ("on_track", 1))
        self.assertNotIn("Secret", [p["name"] for p in data["projects"]])

    def test_weeks_parameter_is_bounded(self):
        self.assertEqual(len(self.get(self.alice, weeks=99).json()["heatmap"]), 52 * 7)
        self.assertEqual(len(self.get(self.alice, weeks="abc").json()["heatmap"]), 15 * 7)

    def test_other_tenant_sees_only_its_workspace(self):
        data = self.get(self.bob).json()
        self.assertEqual(data["health"]["active"], 1)
        self.assertEqual(data["completed_in_period"], 1)
        self.assertEqual(data["focus"], [])
        self.assertEqual(data["upcoming"], [])
