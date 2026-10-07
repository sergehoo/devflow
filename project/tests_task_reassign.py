"""
Réaffectation de tâche (bouton « Réaffecter »).

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_task_reassign
"""

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from project import models as dm

User = get_user_model()


@override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
class TaskReassignTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("owner", "owner@a.test", "pw")
        cls.pm = User.objects.create_user("pm", "pm@a.test", "pw", first_name="Paula", last_name="PM")
        cls.dev = User.objects.create_user("dev", "dev@a.test", "pw", first_name="Jean", last_name="Dev")
        cls.dev2 = User.objects.create_user("dev2", "dev2@a.test", "pw", first_name="Luc", last_name="Dev")
        cls.peer = User.objects.create_user("peer", "peer@a.test", "pw", first_name="Pia", last_name="Peer")
        cls.outsider = User.objects.create_user("bob", "bob@b.test", "pw")
        cls.ws = dm.Workspace.objects.create(name="A", owner=cls.owner)
        cls.ws_b = dm.Workspace.objects.create(name="B", owner=cls.outsider)
        for user in (cls.owner, cls.pm, cls.dev, cls.dev2, cls.peer):
            dm.UserProfile.objects.create(user=user, workspace=cls.ws)
            dm.TeamMembership.objects.create(user=user, workspace=cls.ws)
        dm.UserProfile.objects.create(user=cls.outsider, workspace=cls.ws_b)
        dm.TeamMembership.objects.create(user=cls.outsider, workspace=cls.ws_b)
        cls.project = dm.Project.objects.create(workspace=cls.ws, name="Portail", product_manager=cls.pm)
        dm.ProjectMember.objects.create(project=cls.project, user=cls.dev2)
        other_project = dm.Project.objects.create(workspace=cls.ws_b, name="X")
        cls.foreign_task = dm.Task.objects.create(workspace=cls.ws_b, project=other_project, title="Étrangère")

    def setUp(self):
        self.task = dm.Task.objects.create(workspace=self.ws, project=self.project, title="API paiement")
        self.task.assign(self.dev, assigned_by=self.pm)

    def api(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def reassign(self, actor, user_id, task=None, **extra):
        task = task or self.task
        return self.api(actor).post(
            f"/api/v1/tasks/{task.pk}/quick-assign/", {"user_id": user_id, **extra}, format="json",
        )

    def test_project_manager_reassigns_with_note(self):
        resp = self.reassign(self.pm, self.dev2.pk, note="Reprends la suite stp")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["assignee_name"], "Luc Dev")
        self.task.refresh_from_db()
        self.assertEqual(self.task.assignee, self.dev2)
        self.assertEqual(
            list(self.task.assignments.filter(is_active=True).values_list("user_id", flat=True)), [self.dev2.pk],
        )
        self.assertTrue(dm.TaskComment.objects.filter(task=self.task, body__contains="Reprends la suite").exists())
        self.assertTrue(dm.Notification.objects.filter(recipient=self.dev2).exists())

    def test_current_assignee_can_hand_over_and_unassign(self):
        self.assertEqual(self.reassign(self.dev, self.dev2.pk).status_code, 200)
        self.assertEqual(self.reassign(self.dev2, None).status_code, 200)
        self.task.refresh_from_db()
        self.assertIsNone(self.task.assignee)

    def test_member_without_rights_refused(self):
        resp = self.reassign(self.peer, self.peer.pk)
        self.assertEqual(resp.status_code, 403)
        self.task.refresh_from_db()
        self.assertEqual(self.task.assignee, self.dev)

    def test_tenant_isolation(self):
        self.assertEqual(self.reassign(self.pm, self.outsider.pk).status_code, 400)
        self.assertEqual(self.reassign(self.pm, self.dev.pk, task=self.foreign_task).status_code, 404)
        self.assertEqual(self.api(self.pm).get(f"/api/v1/tasks/{self.foreign_task.pk}/assignees/").status_code, 404)
        self.task.refresh_from_db()
        self.assertEqual(self.task.assignee, self.dev)

    def test_candidates_list(self):
        data = self.api(self.pm).get(f"/api/v1/tasks/{self.task.pk}/assignees/").json()
        self.assertTrue(data["can_reassign"])
        ids = [u["id"] for u in data["users"]]
        self.assertEqual(ids[:2], [self.dev.pk, self.dev2.pk])  # assigné actuel puis membre du projet
        self.assertNotIn(self.outsider.pk, ids)
        current = data["users"][0]
        self.assertEqual((current["is_current"], current["open_tasks"]), (True, 1))
        self.assertTrue(data["users"][1]["is_project_member"])
        filtered = self.api(self.pm).get(f"/api/v1/tasks/{self.task.pk}/assignees/?q=luc").json()["users"]
        self.assertEqual([u["id"] for u in filtered], [self.dev2.pk])
        self.assertFalse(self.api(self.peer).get(f"/api/v1/tasks/{self.task.pk}/assignees/").json()["can_reassign"])

    def test_legacy_html_route_is_secured(self):
        self.client.force_login(self.pm)
        url = reverse("task_quick_assign", args=[self.task.pk])
        self.client.post(url, {"user": self.outsider.pk})
        self.task.refresh_from_db()
        self.assertEqual(self.task.assignee, self.dev)
        self.assertEqual(self.client.post(reverse("task_quick_assign", args=[self.foreign_task.pk]),
                                          {"user": self.dev.pk}).status_code, 404)
        resp = self.client.post(url, {"user": self.dev2.pk, "next": "https://evil.test/"})
        self.assertRedirects(resp, reverse("task_detail", args=[self.task.pk]), fetch_redirect_response=False)
        self.task.refresh_from_db()
        self.assertEqual(self.task.assignee, self.dev2)

    def test_button_and_modal_rendered(self):
        self.client.force_login(self.pm)
        page = self.client.get(reverse("task_detail", args=[self.task.pk]))
        self.assertContains(page, f"devflowReassign({self.task.pk}")
        self.assertContains(page, f'data-task-assignee="{self.task.pk}"')
        self.assertContains(page, "Réaffecter la tâche")

    def test_task_list_and_project_page_render_button(self):
        self.client.force_login(self.pm)
        listing = self.client.get(reverse("task_list"))
        self.assertEqual(listing.status_code, 200)
        self.assertContains(listing, "Réaffecter")
        self.assertNotContains(listing, "Affecter la tâche")  # ancienne modale supprimée
        project_page = self.client.get(reverse("project_detail", args=[self.project.pk]))
        self.assertEqual(project_page.status_code, 200)
        self.assertContains(project_page, f"devflowReassign({self.task.pk}")
