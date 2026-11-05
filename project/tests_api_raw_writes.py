"""
SECURITY — écritures directes sur les API brutes ``/api/v1/tasks/`` et
``/api/v1/timesheets/`` : contournements, IDOR et non-régression.

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_api_raw_writes
"""

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from project import models as dm

User = get_user_model()
MONDAY = date(2026, 10, 5)
S = dm.TimesheetEntry.ApprovalStatus


class RawApiFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        mk = lambda name: User.objects.create_user(name, f"{name}@x.test", "pw")  # noqa: E731
        cls.owner, cls.pm, cls.lead, cls.dev, cls.peer, cls.outsider, cls.bob = (
            mk(n) for n in ("owner", "pm", "lead", "dev", "peer", "outsider", "bob"))
        cls.ws = dm.Workspace.objects.create(name="Alpha", owner=cls.owner)
        cls.other = dm.Workspace.objects.create(name="Beta", owner=cls.bob)
        cls.team = dm.Team.objects.create(workspace=cls.ws, name="Core", lead=cls.lead)
        cls.team2 = dm.Team.objects.create(workspace=cls.ws, name="Ops")
        owner_p = dm.UserProfile.objects.create(user=cls.owner, workspace=cls.ws)
        lead_p = dm.UserProfile.objects.create(user=cls.lead, workspace=cls.ws, manager=owner_p)
        dm.UserProfile.objects.create(user=cls.dev, workspace=cls.ws, manager=lead_p)
        for u in (cls.pm, cls.peer, cls.outsider):
            dm.UserProfile.objects.create(user=u, workspace=cls.ws)
        dm.UserProfile.objects.create(user=cls.bob, workspace=cls.other)
        for u, team in ((cls.owner, None), (cls.pm, None), (cls.lead, cls.team), (cls.dev, cls.team),
                        (cls.peer, cls.team2), (cls.outsider, cls.team2)):
            dm.TeamMembership.objects.create(user=u, workspace=cls.ws, team=team)
        dm.TeamMembership.objects.create(user=cls.bob, workspace=cls.other)
        dm.WorkspaceRoleAssignment.objects.create(user=cls.pm, workspace=cls.ws, role="PROJECT_MANAGER")
        dm.WorkspaceRoleAssignment.objects.create(user=cls.lead, workspace=cls.ws, role="TEAM_LEAD")
        cls.project = dm.Project.objects.create(workspace=cls.ws, name="Portail", team=cls.team)
        cls.project2 = dm.Project.objects.create(workspace=cls.ws, name="Interne", team=cls.team2, product_manager=cls.outsider)
        cls.foreign_project = dm.Project.objects.create(workspace=cls.other, name="Secret")
        cls.sprint2 = dm.Sprint.objects.create(workspace=cls.ws, project=cls.project2, name="S2",
                                               start_date=MONDAY, end_date=MONDAY + timedelta(days=13))

    def setUp(self):
        self.task = dm.Task.objects.create(workspace=self.ws, project=self.project, title="API", assignee=self.dev,
                                           reporter=self.owner)
        self.task2 = dm.Task.objects.create(workspace=self.ws, project=self.project2, title="Doc", assignee=self.peer)
        self.foreign_task = dm.Task.objects.create(workspace=self.other, project=self.foreign_project, title="Bob")

    def api(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client


class TaskRawWriteTests(RawApiFixture):
    def patch(self, user, task, payload):
        return self.api(user).patch(f"/api/v1/tasks/{task.pk}/", payload, format="json")

    def test_member_cannot_edit_colleague_task(self):
        res = self.patch(self.peer, self.task, {"title": "pirate"})
        self.assertEqual(res.status_code, 403)
        self.task.refresh_from_db()
        self.assertEqual(self.task.title, "API")

    def test_assignee_can_edit_own_task(self):
        self.assertEqual(self.patch(self.dev, self.task, {"title": "API v2"}).status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.title, "API v2")

    def test_pm_role_and_project_lead_can_edit(self):
        self.assertEqual(self.patch(self.pm, self.task, {"priority": "HIGH"}).status_code, 200)
        # outsider : MEMBER mais product manager du projet 2.
        self.assertEqual(self.patch(self.outsider, self.task2, {"title": "Doc v2"}).status_code, 200)
        self.assertEqual(self.patch(self.outsider, self.task, {"title": "x"}).status_code, 403)

    def test_team_lead_scope(self):
        self.assertEqual(self.patch(self.lead, self.task, {"title": "Équipe Core"}).status_code, 200)
        self.assertEqual(self.patch(self.lead, self.task2, {"title": "x"}).status_code, 403)

    def test_cross_tenant_idor_returns_404(self):
        self.assertEqual(self.patch(self.bob, self.task, {"title": "x"}).status_code, 404)
        self.assertEqual(self.patch(self.dev, self.foreign_task, {"title": "x"}).status_code, 404)
        self.assertEqual(self.api(self.bob).delete(f"/api/v1/tasks/{self.task.pk}/").status_code, 404)
        self.assertTrue(dm.Task.objects.filter(pk=self.task.pk).exists())

    def test_forged_fields_are_rejected(self):
        self.assertEqual(self.patch(self.pm, self.task, {"workspace": self.other.pk}).status_code, 400)
        self.assertEqual(self.patch(self.pm, self.task, {"reporter": self.pm.pk}).status_code, 400)
        self.assertEqual(self.patch(self.pm, self.task, {"project": self.foreign_project.pk}).status_code, 400)
        self.assertEqual(self.patch(self.pm, self.task, {"sprint": self.sprint2.pk}).status_code, 400)
        self.assertEqual(self.patch(self.pm, self.task, {"assignee": self.bob.pk}).status_code, 400)
        self.task.refresh_from_db()
        self.assertEqual((self.task.workspace_id, self.task.reporter_id, self.task.sprint_id), (self.ws.pk, self.owner.pk, None))

    def test_reassign_requires_can_reassign(self):
        # Le team lead peut éditer (task.edit_team) et réaffecter (task.assign).
        self.assertEqual(self.patch(self.lead, self.task, {"assignee": self.peer.pk}).status_code, 200)
        # L'assigné (MEMBER) peut se dessaisir — règle existante de can_reassign.
        self.assertEqual(self.patch(self.peer, self.task, {"assignee": self.dev.pk}).status_code, 200)

    def test_delete_requires_rbac(self):
        self.assertEqual(self.api(self.dev).delete(f"/api/v1/tasks/{self.task.pk}/").status_code, 403)
        self.assertEqual(self.api(self.lead).delete(f"/api/v1/tasks/{self.task.pk}/").status_code, 403)
        self.assertEqual(self.api(self.owner).delete(f"/api/v1/tasks/{self.task.pk}/").status_code, 204)

    def test_create_forces_reporter_and_workspace(self):
        res = self.api(self.dev).post("/api/v1/tasks/", {"project": self.project.pk, "title": "Nouvelle",
                                                         "reporter": self.owner.pk, "assignee": self.dev.pk}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        task = dm.Task.objects.get(pk=res.json()["id"])
        self.assertEqual((task.workspace_id, task.reporter_id), (self.ws.pk, self.dev.pk))
        self.assertTrue(dm.TaskAssignment.objects.filter(task=task, user=self.dev).exists())

    def test_create_in_foreign_project_or_mismatched_workspace_rejected(self):
        client = self.api(self.dev)
        self.assertEqual(client.post("/api/v1/tasks/", {"project": self.foreign_project.pk, "title": "x"}, format="json").status_code, 400)
        self.bob_in_alpha = dm.TeamMembership.objects.create(user=self.bob, workspace=self.ws)
        res = self.api(self.bob).post("/api/v1/tasks/", {"project": self.project.pk, "workspace": self.other.pk, "title": "x"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertFalse(dm.Task.objects.filter(title="x").exists())

    def test_legitimate_integration_flow_still_works(self):
        """Non-régression : lecture + mise à jour par le chef de projet via jeton/API."""
        client = self.api(self.pm)
        self.assertEqual(client.get(f"/api/v1/tasks/{self.task.pk}/").status_code, 200)
        res = client.put(f"/api/v1/tasks/{self.task.pk}/", {"project": self.project.pk, "title": "Complet", "status": "IN_PROGRESS",
                                                           "priority": "LOW", "assignee": self.dev.pk}, format="json")
        self.assertEqual(res.status_code, 200, res.content)


class TimesheetRawWriteTests(RawApiFixture):
    def entry(self, user=None, day=MONDAY, status=S.DRAFT, hours="2"):
        return dm.TimesheetEntry.objects.create(user=user or self.dev, workspace=self.ws, project=self.project,
                                                entry_date=day, hours=hours, approval_status=status)

    def post(self, user, payload):
        return self.api(user).post("/api/v1/timesheets/", payload, format="json")

    def test_visibility_follows_hierarchy(self):
        mine, peer = self.entry(), self.entry(user=self.peer)
        ids = lambda u: {r["id"] for r in self.api(u).get("/api/v1/timesheets/").json()["results"]}  # noqa: E731
        self.assertEqual(ids(self.dev), {mine.pk})
        self.assertEqual(ids(self.lead), {mine.pk})                 # N+1 voit son N-1
        self.assertEqual(ids(self.pm), set())                       # PM sans subordonné : rien
        self.assertEqual(ids(self.owner), {mine.pk, peer.pk})       # propriétaire : tout le workspace
        self.assertEqual(ids(self.bob), set())                      # autre tenant
        self.assertEqual(self.api(self.peer).get(f"/api/v1/timesheets/{mine.pk}/").status_code, 404)

    def test_create_forces_owner_and_draft(self):
        res = self.post(self.dev, {"project": self.project.pk, "entry_date": MONDAY.isoformat(), "hours": "3",
                                   "approval_status": "APPROVED"})
        self.assertEqual(res.status_code, 201, res.content)
        e = dm.TimesheetEntry.objects.get(pk=res.json()["id"])
        self.assertEqual((e.user_id, e.workspace_id, e.approval_status, e.approved_by_id), (self.dev.pk, self.ws.pk, S.DRAFT, None))

    def test_cannot_create_for_someone_else(self):
        res = self.post(self.lead, {"user": self.dev.pk, "project": self.project.pk, "entry_date": MONDAY.isoformat(), "hours": "8"})
        self.assertEqual(res.status_code, 403)
        self.assertFalse(dm.TimesheetEntry.objects.exists())

    def test_cannot_create_in_foreign_workspace_or_project(self):
        self.assertEqual(self.post(self.dev, {"workspace": self.other.pk, "entry_date": MONDAY.isoformat(), "hours": "1"}).status_code, 400)
        self.assertEqual(self.post(self.dev, {"project": self.foreign_project.pk, "entry_date": MONDAY.isoformat(), "hours": "1"}).status_code, 400)
        self.assertFalse(dm.TimesheetEntry.objects.exists())

    def test_locked_week_rejects_create_update_delete(self):
        submitted = self.entry(status=S.SUBMITTED)
        self.assertEqual(self.post(self.dev, {"project": self.project.pk, "entry_date": (MONDAY + timedelta(days=2)).isoformat(), "hours": "1"}).status_code, 409)
        client = self.api(self.dev)
        self.assertEqual(client.patch(f"/api/v1/timesheets/{submitted.pk}/", {"hours": "9"}, format="json").status_code, 409)
        self.assertEqual(client.delete(f"/api/v1/timesheets/{submitted.pk}/").status_code, 409)
        approved = self.entry(day=MONDAY - timedelta(days=7), status=S.APPROVED)
        self.assertEqual(client.patch(f"/api/v1/timesheets/{approved.pk}/", {"hours": "9"}, format="json").status_code, 409)
        submitted.refresh_from_db(); approved.refresh_from_db()
        self.assertEqual((submitted.hours, approved.hours), (2, 2))

    def test_cannot_move_draft_into_locked_week(self):
        self.entry(status=S.SUBMITTED)
        draft = self.entry(day=MONDAY + timedelta(days=7))
        res = self.api(self.dev).patch(f"/api/v1/timesheets/{draft.pk}/", {"entry_date": MONDAY.isoformat()}, format="json")
        self.assertEqual(res.status_code, 409)

    def test_manager_cannot_edit_subordinate_entry_nor_forge_approval(self):
        e = self.entry()
        client = self.api(self.lead)
        self.assertEqual(client.patch(f"/api/v1/timesheets/{e.pk}/", {"hours": "1"}, format="json").status_code, 403)
        self.assertEqual(client.delete(f"/api/v1/timesheets/{e.pk}/").status_code, 403)
        res = self.api(self.dev).patch(f"/api/v1/timesheets/{e.pk}/", {"approval_status": "APPROVED", "hours": "4"}, format="json")
        self.assertEqual(res.status_code, 200)
        e.refresh_from_db()
        self.assertEqual((e.approval_status, e.hours), (S.DRAFT, 4))

    def test_reassigning_entry_to_other_user_is_refused(self):
        e = self.entry()
        res = self.api(self.dev).patch(f"/api/v1/timesheets/{e.pk}/", {"user": self.peer.pk}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_correction_after_rejection_reopens_week(self):
        rejected = self.entry(status=S.REJECTED)
        res = self.api(self.dev).patch(f"/api/v1/timesheets/{rejected.pk}/", {"hours": "5"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        other = self.entry(day=MONDAY + timedelta(days=1), status=S.REJECTED)
        self.post(self.dev, {"project": self.project.pk, "entry_date": (MONDAY + timedelta(days=2)).isoformat(), "hours": "1"})
        other.refresh_from_db()
        self.assertEqual(other.approval_status, S.DRAFT)

    def test_own_draft_delete_ok(self):
        e = self.entry()
        self.assertEqual(self.api(self.dev).delete(f"/api/v1/timesheets/{e.pk}/").status_code, 204)
