"""
P0 sécurité multi-tenant — non-régression.

User du workspace A ne peut ni lire, modifier, supprimer ni référencer un
objet du workspace B (HTML, querystring, payload, DRF, WebSocket, médias),
et les permissions légitimes continuent de fonctionner.

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_security_p0
"""

import shutil
import tempfile

from asgiref.sync import async_to_sync
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from project import models as dm
from project.forms import RiskForm
from project.routing import websocket_urlpatterns

User = get_user_model()
MEDIA_TMP = tempfile.mkdtemp(prefix="devflow-media-tests-")


@override_settings(
    STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage",
    MEDIA_ROOT=MEDIA_TMP,
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
)
class TenantFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Users avant les workspaces : le signal de profil ne s'applique pas.
        cls.alice = User.objects.create_user("alice", "alice@a.test", "pw-12345678")
        cls.bob = User.objects.create_user("bob", "bob@b.test", "pw-12345678")
        cls.client_user = User.objects.create_user("cli", "cli@a.test", "pw-12345678")
        cls.ws_a = dm.Workspace.objects.create(name="Tenant A", owner=cls.alice)
        cls.ws_b = dm.Workspace.objects.create(name="Tenant B", owner=cls.bob)
        for user, ws in ((cls.alice, cls.ws_a), (cls.bob, cls.ws_b), (cls.client_user, cls.ws_a)):
            dm.UserProfile.objects.create(user=user, workspace=ws)
            dm.TeamMembership.objects.create(user=user, workspace=ws)
        dm.WorkspaceRoleAssignment.objects.create(workspace=cls.ws_a, user=cls.client_user, role="CLIENT")

        cls.project_a = dm.Project.objects.create(workspace=cls.ws_a, name="Projet A")
        cls.project_b = dm.Project.objects.create(workspace=cls.ws_b, name="Projet B")
        cls.task_a = dm.Task.objects.create(workspace=cls.ws_a, project=cls.project_a, title="Tâche A")
        cls.task_b = dm.Task.objects.create(workspace=cls.ws_b, project=cls.project_b, title="Tâche B")
        cls.channel_a = dm.DirectChannel.objects.create(workspace=cls.ws_a, name="general-a", is_private=True)
        dm.ChannelMembership.objects.create(channel=cls.channel_a, user=cls.alice)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_TMP, ignore_errors=True)


class HtmlIsolationTests(TenantFixture):
    def setUp(self):
        self.client.force_login(self.alice)

    def test_read_foreign_objects_404(self):
        self.assertEqual(self.client.get(reverse("project_detail", args=[self.project_b.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("workspace_detail", args=[self.ws_b.pk])).status_code, 404)
        self.assertEqual(
            self.client.get(reverse("project_budget_export_excel", args=[self.project_b.pk])).status_code, 404,
        )
        workspaces = self.client.get(reverse("workspace_list")).context["object_list"]
        self.assertEqual(list(workspaces), [self.ws_a])

    def test_querystring_workspace_forgery_refused(self):
        url = reverse("project_delete", args=[self.project_b.pk]) + f"?workspace={self.ws_b.pk}"
        self.assertEqual(self.client.post(url).status_code, 404)
        self.assertTrue(dm.Project.objects.filter(pk=self.project_b.pk).exists())
        url = reverse("project_detail", args=[self.project_a.pk]) + f"?workspace={self.ws_b.pk}"
        self.assertEqual(self.client.get(url).status_code, 404)
        url = reverse("workspace_update", args=[self.ws_b.pk])
        self.assertEqual(self.client.post(url, {"name": "pwned", "owner": self.alice.pk}).status_code, 404)
        self.ws_b.refresh_from_db()
        self.assertEqual(self.ws_b.owner, self.bob)

    def test_payload_foreign_fk_rejected(self):
        form = RiskForm(
            data={"project": self.project_b.pk, "title": "x"},
            current_workspace=self.ws_a, allowed_workspaces=[self.ws_a],
        )
        self.assertNotIn(self.project_b, form.fields["project"].queryset)
        self.assertFalse(form.is_valid())
        self.assertIn("project", form.errors)

    def test_profile_cannot_join_foreign_workspace(self):
        form = self.client.get(reverse("profile_update")).context["form"]
        self.assertEqual(list(form.fields["workspace"].queryset), [self.ws_a])

    def test_foreign_chat_channel_404(self):
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(reverse("channel_chat_page", args=[self.channel_a.pk])).status_code, 404)
        resp = self.client.post(reverse("channel_send_message", args=[self.channel_a.pk]), {"body": "hi"})
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(dm.Message.objects.filter(channel=self.channel_a).exists())

    def test_client_role_cannot_delete_workspace_or_project(self):
        self.client.force_login(self.client_user)
        self.assertEqual(self.client.post(reverse("workspace_delete", args=[self.ws_a.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("project_delete", args=[self.project_a.pk])).status_code, 403)
        self.assertTrue(dm.Workspace.objects.filter(pk=self.ws_a.pk).exists())
        self.assertTrue(dm.Project.objects.filter(pk=self.project_a.pk).exists())

    def test_legitimate_access_still_works(self):
        self.assertEqual(self.client.get(reverse("project_detail", args=[self.project_a.pk])).status_code, 200)
        url = reverse("project_detail", args=[self.project_a.pk]) + f"?workspace={self.ws_a.pk}"
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(reverse("channel_chat_page", args=[self.channel_a.pk])).status_code, 302)
        resp = self.client.post(reverse("project_delete", args=[self.project_a.pk]))
        self.assertEqual(resp.status_code, 302)  # owner : suppression autorisée
        self.assertFalse(dm.Project.objects.filter(pk=self.project_a.pk).exists())


class ApiIsolationTests(TenantFixture):
    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.alice)

    def test_read_update_delete_foreign_objects_refused(self):
        url = f"/api/v1/projects/{self.project_b.pk}/"
        self.assertEqual(self.api.get(url).status_code, 404)
        self.assertEqual(self.api.patch(url, {"name": "x"}, format="json").status_code, 404)
        self.assertEqual(self.api.delete(url).status_code, 404)
        self.assertTrue(dm.Project.objects.filter(pk=self.project_b.pk, name="Projet B").exists())

    def test_payload_cannot_reference_foreign_objects(self):
        resp = self.api.patch(f"/api/v1/projects/{self.project_a.pk}/", {"workspace": self.ws_b.pk}, format="json")
        self.assertEqual(resp.status_code, 400)
        resp = self.api.post("/api/v1/projects/", {"workspace": self.ws_b.pk, "name": "Intrus"}, format="json")
        self.assertEqual(resp.status_code, 400)
        resp = self.api.post("/api/v1/project-members/", {"project": self.project_b.pk, "user": self.alice.pk}, format="json")
        self.assertEqual(resp.status_code, 400)
        resp = self.api.post("/api/v1/project-members/", {"project": self.project_a.pk, "user": self.bob.pk}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.project_a.refresh_from_db()
        self.assertEqual(self.project_a.workspace, self.ws_a)
        self.assertFalse(dm.Project.objects.filter(name="Intrus").exists())
        self.assertFalse(dm.ProjectMember.objects.exists())

    def test_client_cannot_delete_workspace(self):
        api = APIClient()
        api.force_authenticate(self.client_user)
        self.assertEqual(api.delete(f"/api/v1/workspaces/{self.ws_a.pk}/").status_code, 403)
        self.assertTrue(dm.Workspace.objects.filter(pk=self.ws_a.pk).exists())

    def test_legitimate_api_usage(self):
        resp = self.api.patch(f"/api/v1/projects/{self.project_a.pk}/", {"name": "Renommé"}, format="json")
        self.assertEqual(resp.status_code, 200)
        resp = self.api.post("/api/v1/project-members/", {"project": self.project_a.pk, "user": self.alice.pk}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        payload = self.api.get("/api/v1/projects/").json()
        rows = payload.get("results", payload) if isinstance(payload, dict) else payload
        self.assertEqual({p["id"] for p in rows}, {self.project_a.pk})


class WebSocketIsolationTests(TenantFixture):
    app = URLRouter(websocket_urlpatterns)

    def _connect(self, user, path):
        async def run():
            communicator = WebsocketCommunicator(self.app, path)
            communicator.scope["user"] = user
            connected, _ = await communicator.connect()
            if connected:
                await communicator.disconnect()
            return connected
        return async_to_sync(run)()

    def test_foreign_and_anonymous_refused(self):
        from django.contrib.auth.models import AnonymousUser

        for path in (f"/ws/chat/{self.channel_a.pk}/", f"/ws/channels/{self.channel_a.pk}/"):
            self.assertFalse(self._connect(self.bob, path), path)
            self.assertFalse(self._connect(AnonymousUser(), path), path)

    def test_member_can_connect_and_send(self):
        async def run():
            communicator = WebsocketCommunicator(self.app, f"/ws/chat/{self.channel_a.pk}/")
            communicator.scope["user"] = self.alice
            connected, _ = await communicator.connect()
            await communicator.send_json_to({"body": "bonjour"})
            await communicator.receive_from(timeout=2)
            await communicator.disconnect()
            return connected
        self.assertTrue(async_to_sync(run)())
        self.assertTrue(dm.Message.objects.filter(channel=self.channel_a, body="bonjour").exists())


class MediaIsolationTests(TenantFixture):
    def setUp(self):
        self.attachment = dm.TaskAttachment.objects.create(
            task=self.task_b, uploaded_by=self.bob,
            file=SimpleUploadedFile("contrat.pdf", b"%PDF-secret", content_type="application/pdf"),
        )
        self.url = "/media/" + self.attachment.file.name

    def test_foreign_and_anonymous_refused(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)  # → login
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.get("/media/../settings.py").status_code, 404)

    def test_owner_tenant_can_download(self):
        self.client.force_login(self.bob)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(b"".join(resp.streaming_content), b"%PDF-secret")
