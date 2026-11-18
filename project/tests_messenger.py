"""
Messagerie (Messenger) : DM automatiques uniques, conversations Équipe / Projet
synchronisées, non-lus, pièces jointes / réactions, WebSocket, isolation tenant,
serializers Task / Workspace.

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_messenger
"""

import shutil
import tempfile
from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from project import models as dm
from project.routing import websocket_urlpatterns
from project.services.chat import ChatService

User = get_user_model()
API = "/api/v1/me/chat"
MEDIA_TMP = tempfile.mkdtemp(prefix="devflow-messenger-tests-")
Kind = dm.DirectChannel.Kind


@override_settings(
    STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage",
    MEDIA_ROOT=MEDIA_TMP,
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
)
class MessengerFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@a.test", "pw", first_name="Alice", last_name="A")
        cls.bob = User.objects.create_user("bob", "bob@a.test", "pw", first_name="Bob", last_name="B")
        cls.carol = User.objects.create_user("carol", "carol@a.test", "pw", first_name="Carol", last_name="C")
        cls.dave = User.objects.create_user("dave", "dave@b.test", "pw", first_name="Dave", last_name="D")
        cls.ws_a = dm.Workspace.objects.create(name="Tenant A", owner=cls.alice)
        cls.ws_b = dm.Workspace.objects.create(name="Tenant B", owner=cls.dave)
        for user, ws in ((cls.alice, cls.ws_a), (cls.bob, cls.ws_a), (cls.carol, cls.ws_a), (cls.dave, cls.ws_b)):
            dm.UserProfile.objects.create(user=user, workspace=ws)
            dm.TeamMembership.objects.create(user=user, workspace=ws)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_TMP, ignore_errors=True)

    def api(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def open_dm(self, user, other):
        resp = self.api(user).post(f"{API}/direct/", {"user_id": other.pk}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        return resp.json()["id"]


class DirectMessageTests(MessengerFixture):
    def test_dm_created_automatically_and_unique_per_pair(self):
        first = self.open_dm(self.alice, self.bob)
        self.assertEqual(self.open_dm(self.alice, self.bob), first)
        self.assertEqual(self.open_dm(self.bob, self.alice), first)
        channel = dm.DirectChannel.objects.get(pk=first)
        self.assertEqual((channel.kind, channel.dm_key), (Kind.DM, f"{self.alice.pk}:{self.bob.pk}"))
        self.assertEqual(set(channel.members.values_list("pk", flat=True)), {self.alice.pk, self.bob.pk})
        self.assertEqual(dm.DirectChannel.objects.filter(kind=Kind.DM).count(), 1)

    def test_dm_with_other_tenant_refused(self):
        resp = self.api(self.alice).post(f"{API}/direct/", {"user_id": self.dave.pk}, format="json")
        self.assertEqual(resp.status_code, 404)
        with self.assertRaises(ValueError):
            ChatService.find_or_create_direct(user_a=self.alice, user_b=self.dave, workspace=self.ws_a)
        self.assertFalse(dm.DirectChannel.objects.exists())

    def test_users_cannot_create_channels(self):
        resp = self.api(self.alice).post(f"{API}/groups/", {"name": "x", "member_ids": [self.bob.pk]}, format="json")
        self.assertEqual(resp.status_code, 403)
        self.client.force_login(self.alice)
        self.assertRedirects(self.client.get("/channels/create/"), "/chat/", fetch_redirect_response=False)


class GroupConversationTests(MessengerFixture):
    def test_team_conversation_created_and_members_synced(self):
        with self.captureOnCommitCallbacks(execute=True):
            team = dm.Team.objects.create(workspace=self.ws_a, name="Dev", lead=self.alice)
            bob_m = dm.TeamMembership.objects.create(workspace=self.ws_a, team=team, user=self.bob)
            dm.TeamMembership.objects.create(workspace=self.ws_a, team=team, user=self.carol)
        channel = dm.DirectChannel.objects.get(team=team)
        self.assertEqual(channel.kind, Kind.TEAM)
        self.assertEqual(set(channel.members.all()), {self.alice, self.bob, self.carol})

        with self.captureOnCommitCallbacks(execute=True):
            bob_m.delete()
        self.assertEqual(set(channel.members.all()), {self.alice, self.carol})

        ChatService.sync_team_channel(team)
        ChatService.sync_team_channel(team)  # idempotent
        self.assertEqual(dm.DirectChannel.objects.filter(team=team).count(), 1)
        self.assertEqual(channel.memberships.count(), 2)

    def test_project_conversation_created_and_participants_synced(self):
        with self.captureOnCommitCallbacks(execute=True):
            project = dm.Project.objects.create(workspace=self.ws_a, name="Portail", owner=self.alice)
            member = dm.ProjectMember.objects.create(project=project, user=self.carol)
        channel = dm.DirectChannel.objects.get(project=project)
        self.assertEqual(channel.kind, Kind.PROJECT)
        self.assertEqual(set(channel.members.all()), {self.alice, self.carol})
        with self.captureOnCommitCallbacks(execute=True):
            member.delete()
        self.assertEqual(set(channel.members.all()), {self.alice})
        self.assertEqual(dm.DirectChannel.objects.filter(project=project).count(), 1)

    def test_conversation_list_sections_and_tenant_isolation(self):
        with self.captureOnCommitCallbacks(execute=True):
            team = dm.Team.objects.create(workspace=self.ws_a, name="Dev")
            dm.TeamMembership.objects.create(workspace=self.ws_a, team=team, user=self.alice)
            dm.Project.objects.create(workspace=self.ws_a, name="Portail", owner=self.alice)
        self.open_dm(self.alice, self.bob)
        convs = self.api(self.alice).get(f"{API}/conversations/").json()["conversations"]
        self.assertEqual({(c["section"], c["title"]) for c in convs},
                         {("direct", "Bob B"), ("teams", "Dev"), ("projects", "Portail")})
        self.assertEqual(self.api(self.dave).get(f"{API}/conversations/").json()["conversations"], [])
        contacts = self.api(self.alice).get(f"{API}/contacts/").json()["contacts"]
        self.assertEqual({c["id"] for c in contacts}, {self.bob.pk, self.carol.pk})


class UnreadAttachmentReactionTests(MessengerFixture):
    def setUp(self):
        self.channel_id = self.open_dm(self.alice, self.bob)

    def test_unread_counts_and_mark_read(self):
        bob = self.api(self.bob)
        bob.post(f"{API}/channels/{self.channel_id}/messages/", {"body": "Salut"}, format="json")
        bob.post(f"{API}/channels/{self.channel_id}/messages/", {"body": "Tu es là ?"}, format="json")
        alice = self.api(self.alice)
        self.assertEqual(alice.get(f"{API}/unread/").json()["total"], 2)
        conv = alice.get(f"{API}/conversations/").json()["conversations"][0]
        self.assertEqual((conv["unread_count"], conv["last_message_preview"]), (2, "Tu es là ?"))
        self.assertEqual(self.api(self.bob).get(f"{API}/unread/").json()["total"], 0)  # ses propres messages
        self.assertTrue(dm.Notification.objects.filter(recipient=self.alice, notification_type="MESSAGE").exists())
        alice.post(f"{API}/channels/{self.channel_id}/mark-read/")
        self.assertEqual(alice.get(f"{API}/unread/").json()["total"], 0)

    def test_attachment_private_to_participants(self):
        resp = self.api(self.bob).post(
            f"{API}/channels/{self.channel_id}/messages/",
            {"body": "", "files": SimpleUploadedFile("devis.pdf", b"%PDF-1", content_type="application/pdf")},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        url = resp.json()["attachments"][0]["url"]
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_login(self.carol)  # même workspace, pas participante
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.dave)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_reactions_toggle_and_participants_only(self):
        msg_id = self.api(self.bob).post(
            f"{API}/channels/{self.channel_id}/messages/", {"body": "Go"}, format="json",
        ).json()["id"]
        alice = self.api(self.alice)
        resp = alice.post(f"{API}/messages/{msg_id}/reactions/", {"emoji": "👍"}, format="json")
        self.assertEqual(resp.json()["reactions"], [{"emoji": "👍", "count": 1, "mine": True}])
        resp = alice.post(f"{API}/messages/{msg_id}/reactions/", {"emoji": "👍"}, format="json")
        self.assertEqual(resp.json()["reactions"], [])
        self.assertEqual(alice.post(f"{API}/messages/{msg_id}/reactions/", {"emoji": "💣"}, format="json").status_code, 400)
        for intruder in (self.carol, self.dave):
            resp = self.api(intruder).post(f"{API}/messages/{msg_id}/reactions/", {"emoji": "👍"}, format="json")
            self.assertEqual(resp.status_code, 404)
            resp = self.api(intruder).get(f"{API}/channels/{self.channel_id}/messages/")
            self.assertEqual(resp.status_code, 404)


class MessengerWebSocketTests(MessengerFixture):
    app = URLRouter(websocket_urlpatterns)

    def test_non_participant_refused_participants_exchange_in_real_time(self):
        channel_id = self.open_dm(self.alice, self.bob)
        path = f"/ws/channels/{channel_id}/"

        async def scenario():
            refused = []
            for user in (self.carol, self.dave):
                ws = WebsocketCommunicator(self.app, path)
                ws.scope["user"] = user
                ok, _ = await ws.connect()
                refused.append(not ok)
            alice = WebsocketCommunicator(self.app, path)
            alice.scope["user"] = self.alice
            bob = WebsocketCommunicator(self.app, path)
            bob.scope["user"] = self.bob
            assert (await alice.connect())[0] and (await bob.connect())[0]
            await bob.send_json_to({"body": "Hello Alice", "client_id": "x1"})
            received = await alice.receive_json_from(timeout=3)
            await alice.disconnect()
            await bob.disconnect()
            return refused, received

        refused, received = async_to_sync(scenario)()
        self.assertEqual(refused, [True, True])
        self.assertEqual(received["type"], "chat_message")
        self.assertEqual((received["message"]["body"], received["message"]["is_mine"]), ("Hello Alice", False))
        self.assertTrue(dm.Message.objects.filter(channel_id=channel_id, body="Hello Alice", author=self.bob).exists())


class SerializerFixTests(MessengerFixture):
    def test_task_and_workspace_endpoints_work_and_stay_scoped(self):
        project = dm.Project.objects.create(workspace=self.ws_a, name="P")
        dm.Task.objects.create(workspace=self.ws_a, project=project, title="T-A")
        other = dm.Project.objects.create(workspace=self.ws_b, name="Q")
        dm.Task.objects.create(workspace=self.ws_b, project=other, title="T-B")
        alice = self.api(self.alice)

        def rows(resp):
            data = resp.json()
            return data.get("results", data) if isinstance(data, dict) else data

        resp = alice.get("/api/v1/tasks/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([t["title"] for t in rows(resp)], ["T-A"])
        resp = alice.get("/api/v1/workspaces/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([w["id"] for w in rows(resp)], [self.ws_a.pk])
        self.assertEqual(alice.get(f"/api/v1/workspaces/{self.ws_a.pk}/").status_code, 200)


class MessengerUiTests(MessengerFixture):
    def test_page_and_global_bubble_render(self):
        self.client.force_login(self.alice)
        page = self.client.get("/chat/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "mode: 'page'")
        self.assertNotContains(page, "mode: 'bubble'")
        other = self.client.get("/timesheets/list/")
        self.assertEqual(other.status_code, 200)
        self.assertContains(other, "mode: 'bubble'")
        for label in ("Membres channels", "Pièces jointes messages", ">Réactions<"):
            self.assertNotContains(other, label)


class ReadSyncTests(MessengerFixture):
    """Notifications « message » et lecture des conversations restent alignées (badge Messagerie)."""

    NOTIF = "/api/v1/me/notifications"

    def setUp(self):
        self.dm_id = self.open_dm(self.alice, self.bob)
        self.other_id = self.open_dm(self.alice, self.carol)
        self.t0 = timezone.now() - timedelta(hours=1)

    def say(self, author, channel_id, body, minutes):
        resp = self.api(author).post(f"{API}/channels/{channel_id}/messages/", {"body": body}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        at = self.t0 + timedelta(minutes=minutes)
        dm.Message.objects.filter(pk=resp.json()["id"]).update(created_at=at)
        notif = dm.Notification.objects.get(recipient=self.alice, metadata__message_id=resp.json()["id"])
        dm.Notification.objects.filter(pk=notif.pk).update(created_at=at)
        return notif

    def unread(self):
        by_channel = self.api(self.alice).get(f"{API}/unread/").json()["by_channel"]
        return {int(k): v for k, v in by_channel.items()}

    def is_read(self, notif):
        notif.refresh_from_db()
        return notif.is_read

    def test_opening_conversation_reads_its_message_notifications(self):
        first = self.say(self.bob, self.dm_id, "Salut", 1)
        second = self.say(self.bob, self.dm_id, "Tu es là ?", 2)
        elsewhere = self.say(self.carol, self.other_id, "Coucou", 3)
        task = dm.Notification.objects.create(
            recipient=self.alice, workspace=self.ws_a, notification_type="TASK", title="Tâche",
        )
        resp = self.api(self.alice).post(f"{API}/channels/{self.dm_id}/mark-read/")
        self.assertEqual((resp.status_code, resp.json()["notifications_read"]), (200, 2))
        self.assertEqual([self.is_read(n) for n in (first, second, elsewhere, task)], [True, True, False, False])
        summary = self.api(self.alice).get(f"{self.NOTIF}/summary/").json()
        self.assertEqual(summary["unread_count"], 2)
        self.assertEqual(self.api(self.alice).post(f"{API}/channels/{self.dm_id}/mark-read/").json()["notifications_read"], 0)

    def test_read_all_notifications_clears_messenger_badge(self):
        self.say(self.bob, self.dm_id, "Salut", 1)
        self.say(self.carol, self.other_id, "Coucou", 2)
        others = dict(dm.ChannelMembership.objects.exclude(user=self.alice).values_list("pk", "last_read_at"))
        self.assertEqual(self.unread(), {self.dm_id: 1, self.other_id: 1})
        self.assertEqual(self.api(self.alice).post(f"{self.NOTIF}/read-all/").json()["updated"], 2)
        self.assertEqual(self.unread(), {})
        conversations = self.api(self.alice).get(f"{API}/conversations/").json()["conversations"]
        self.assertEqual({c["unread_count"] for c in conversations}, {0})
        # Les repères de lecture des autres participants ne bougent pas.
        self.assertEqual(dict(dm.ChannelMembership.objects.exclude(user=self.alice).values_list("pk", "last_read_at")), others)

    def test_single_notification_reads_conversation_up_to_its_message(self):
        older = self.say(self.bob, self.dm_id, "Un", 1)
        middle = self.say(self.bob, self.dm_id, "Deux", 2)
        newer = self.say(self.bob, self.dm_id, "Trois", 3)
        resp = self.api(self.alice).post(f"{self.NOTIF}/{middle.pk}/read/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.unread(), {self.dm_id: 1})  # « Trois » reste non lu
        self.assertEqual([self.is_read(n) for n in (older, middle, newer)], [True, True, False])
        mark = dm.ChannelMembership.objects.get(channel_id=self.dm_id, user=self.alice).last_read_at
        self.assertEqual(mark, self.t0 + timedelta(minutes=2))

    def test_read_marker_never_moves_backwards(self):
        old = self.say(self.bob, self.dm_id, "Ancien", 1)
        self.say(self.bob, self.dm_id, "Récent", 2)
        later = self.t0 + timedelta(minutes=30)
        dm.ChannelMembership.objects.filter(channel_id=self.dm_id, user=self.alice).update(last_read_at=later)
        dm.Notification.objects.filter(pk=old.pk).update(is_read=False)
        self.api(self.alice).post(f"{self.NOTIF}/{old.pk}/read/")
        self.assertEqual(dm.ChannelMembership.objects.get(channel_id=self.dm_id, user=self.alice).last_read_at, later)

    def test_other_users_and_recording_notifications_untouched(self):
        self.say(self.bob, self.dm_id, "Salut", 1)
        self.api(self.alice).post(f"{API}/channels/{self.dm_id}/messages/", {"body": "Réponse"}, format="json")
        bob_mark = dm.ChannelMembership.objects.get(channel_id=self.dm_id, user=self.bob).last_read_at
        recording = dm.Notification.objects.create(
            recipient=self.alice, workspace=self.ws_a, notification_type="MESSAGE", title="Compte rendu prêt",
            url="/meetings/1/recordings/1/summary/", metadata={"meeting_id": 1},
        )
        resp = self.api(self.alice).post(f"{self.NOTIF}/{recording.pk}/read/")
        self.assertEqual(resp.status_code, 200)
        self.api(self.alice).post(f"{self.NOTIF}/read-all/")
        self.assertEqual(dm.ChannelMembership.objects.get(channel_id=self.dm_id, user=self.bob).last_read_at, bob_mark)
        self.assertEqual(self.api(self.bob).get(f"{API}/unread/").json()["total"], 1)

    def test_legacy_notification_pages_read_conversations_too(self):
        one = self.say(self.bob, self.dm_id, "Salut", 1)
        self.say(self.carol, self.other_id, "Coucou", 2)
        self.client.force_login(self.alice)
        self.client.post(reverse("notification_mark_read", args=[one.pk]))
        self.assertEqual(self.unread(), {self.other_id: 1})
        self.client.post(reverse("notification_mark_all_read"))
        self.assertEqual(self.unread(), {})

    def test_migration_reconciles_existing_state(self):
        from importlib import import_module

        from django.apps import apps as global_apps

        sync = import_module("project.migrations.0060_sync_chat_read_with_message_notifications").sync
        acknowledged = self.say(self.bob, self.dm_id, "Lu par la cloche", 1)
        self.say(self.carol, self.other_id, "Lu dans le fil", 2)
        stale = self.say(self.carol, self.other_id, "Notification restée non lue", 3)
        recording = dm.Notification.objects.create(
            recipient=self.alice, workspace=self.ws_a, notification_type="MESSAGE", title="Compte rendu prêt",
            metadata={"meeting_id": 1},
        )
        dm.Notification.objects.filter(pk=acknowledged.pk).update(is_read=True)
        dm.ChannelMembership.objects.filter(channel_id=self.other_id, user=self.alice).update(
            last_read_at=self.t0 + timedelta(minutes=5),
        )
        self.assertEqual(self.unread(), {self.dm_id: 1})
        sync(global_apps, None)
        sync(global_apps, None)  # idempotente
        self.assertEqual(self.unread(), {})
        self.assertEqual(
            dm.ChannelMembership.objects.get(channel_id=self.dm_id, user=self.alice).last_read_at,
            self.t0 + timedelta(minutes=1),
        )
        self.assertEqual(
            dm.ChannelMembership.objects.get(channel_id=self.other_id, user=self.alice).last_read_at,
            self.t0 + timedelta(minutes=5),  # jamais reculé
        )
        self.assertTrue(self.is_read(stale))
        self.assertFalse(self.is_read(recording))
