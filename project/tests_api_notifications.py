"""
Phase 4 — API Notifications, préférences et flux WebSocket personnel /ws/me/.

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_api_notifications
"""

from unittest import mock

from asgiref.sync import async_to_sync, sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from project import models as dm
from project.routing import websocket_urlpatterns
from project.services.chat import ChatService
from project.services.realtime import push_to_users

User = get_user_model()
API = "/api/v1/me/notifications"
T = dm.Notification.NotificationType


@override_settings(CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}})
class NotificationFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@a.test", "pw")
        cls.bob = User.objects.create_user("bob", "bob@a.test", "pw")
        cls.dave = User.objects.create_user("dave", "dave@b.test", "pw")
        cls.ws_a = dm.Workspace.objects.create(name="A", owner=cls.alice)
        cls.ws_b = dm.Workspace.objects.create(name="B", owner=cls.dave)
        for user, ws in ((cls.alice, cls.ws_a), (cls.bob, cls.ws_a), (cls.dave, cls.ws_b)):
            dm.UserProfile.objects.create(user=user, workspace=ws)
            dm.TeamMembership.objects.create(user=user, workspace=ws)

    def notify(self, user, ws=None, **kw):
        data = {"notification_type": T.TASK, "title": "Tâche assignée", "url": "/tasks/1/", **kw}
        return dm.Notification.objects.create(recipient=user, workspace=ws or self.ws_a, **data)

    def api(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client


class NotificationApiTests(NotificationFixture):
    def test_list_is_scoped_to_recipient_and_accessible_workspaces(self):
        mine = self.notify(self.alice)
        self.notify(self.bob)
        self.notify(self.alice, ws=self.ws_b)  # ancien workspace : plus accessible
        data = self.api(self.alice).get(f"{API}/").json()
        self.assertEqual([r["id"] for r in data["results"]], [mine.pk])
        self.assertEqual((data["unread_count"], data["total_count"]), (1, 1))
        self.assertEqual(data["results"][0]["type_label"], "Tâche")

    def test_filters_and_summary(self):
        self.notify(self.alice, title="Risque critique", notification_type=T.RISK)
        read = self.notify(self.alice, is_read=True)
        client = self.api(self.alice)
        self.assertEqual([r["id"] for r in client.get(f"{API}/", {"status": "read"}).json()["results"]], [read.pk])
        self.assertEqual(client.get(f"{API}/", {"type": "RISK"}).json()["count"], 1)
        self.assertEqual(client.get(f"{API}/", {"q": "critique"}).json()["count"], 1)
        summary = client.get(f"{API}/summary/").json()
        self.assertEqual((summary["unread_count"], len(summary["recent"])), (1, 2))

    def test_mark_read_and_delete_are_recipient_only(self):
        n = self.notify(self.alice)
        other = self.notify(self.bob)
        self.assertEqual(self.api(self.alice).post(f"{API}/{other.pk}/read/").status_code, 404)
        self.assertEqual(self.api(self.alice).delete(f"{API}/{other.pk}/").status_code, 404)
        self.assertEqual(self.api(self.dave).post(f"{API}/{n.pk}/read/").status_code, 404)
        res = self.api(self.alice).post(f"{API}/{n.pk}/read/")
        self.assertEqual((res.status_code, res.json()["is_read"]), (200, True))
        other.refresh_from_db()
        self.assertFalse(other.is_read)
        self.assertEqual(self.api(self.alice).delete(f"{API}/{n.pk}/").status_code, 204)
        self.assertTrue(dm.Notification.objects.filter(pk=other.pk).exists())

    def test_read_all_only_touches_own(self):
        self.notify(self.alice)
        self.notify(self.alice)
        other = self.notify(self.bob)
        self.assertEqual(self.api(self.alice).post(f"{API}/read-all/").json()["updated"], 2)
        other.refresh_from_db()
        self.assertFalse(other.is_read)

    def test_preferences_are_personal_and_validated(self):
        client = self.api(self.alice)
        data = client.get("/api/v1/me/notification-preferences/").json()
        self.assertTrue(data["channel_in_app"])
        self.assertIn("notify_frequency", data["choices"])
        res = client.patch("/api/v1/me/notification-preferences/", {"channel_email": False, "priority_types": ["RISK"]}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertFalse(dm.NotificationPreference.objects.get(user=self.alice).channel_email)
        self.assertFalse(dm.NotificationPreference.objects.filter(user=self.bob).exists())
        self.assertEqual(client.patch("/api/v1/me/notification-preferences/", {"quiet_hours_start": 30}, format="json").status_code, 400)
        self.assertEqual(client.patch("/api/v1/me/notification-preferences/", {"priority_types": ["NOPE"]}, format="json").status_code, 400)

    def test_anonymous_refused(self):
        self.assertIn(APIClient().get(f"{API}/").status_code, (401, 403))


class RealtimeSignalTests(NotificationFixture):
    def test_new_notification_is_pushed_to_recipient_after_commit(self):
        with mock.patch("project.services.realtime.push_to_users") as push:
            with self.captureOnCommitCallbacks(execute=True):
                n = self.notify(self.alice)
        push.assert_called_once()
        user_ids, event, data = push.call_args.args
        self.assertEqual((list(user_ids), event, data["notification"]["id"]), ([self.alice.pk], "notification", n.pk))

    def test_chat_message_pushes_activity_to_participants(self):
        channel = ChatService.find_or_create_direct(user_a=self.alice, user_b=self.bob, workspace=self.ws_a)
        with mock.patch("project.services.realtime.push_to_users") as push:
            ChatService.post_message(channel=channel, author=self.alice, body="Salut")
        user_ids, event, data = push.call_args.args
        self.assertEqual((set(user_ids), event, data["channel_id"]), ({self.alice.pk, self.bob.pk}, "chat.activity", channel.pk))


class UserEventsWebSocketTests(NotificationFixture):
    app = URLRouter(websocket_urlpatterns)

    def connect(self, user):
        ws = WebsocketCommunicator(self.app, "/ws/me/")
        ws.scope["user"] = user
        return ws

    def test_anonymous_closed_with_4401(self):
        async def scenario():
            ws = self.connect(AnonymousUser())
            await ws.connect()
            out = await ws.receive_output(timeout=2)
            await ws.disconnect()
            return out

        out = async_to_sync(scenario)()
        self.assertEqual((out["type"], out.get("code")), ("websocket.close", 4401))

    def test_events_reach_only_their_recipient(self):
        async def scenario():
            alice, bob = self.connect(self.alice), self.connect(self.bob)
            assert (await alice.connect())[0] and (await bob.connect())[0]
            hello = await alice.receive_json_from(timeout=2)
            await bob.receive_json_from(timeout=2)
            await sync_to_async(push_to_users)([self.alice.pk], "notification", {"notification": {"id": 7}})
            got = await alice.receive_json_from(timeout=2)
            bob_silent = await bob.receive_nothing(timeout=0.3)
            await alice.send_json_to({"type": "ping"})
            pong = await alice.receive_json_from(timeout=2)
            await alice.disconnect()
            await bob.disconnect()
            return hello, got, bob_silent, pong

        hello, got, bob_silent, pong = async_to_sync(scenario)()
        self.assertEqual(hello, {"type": "hello", "user_id": self.alice.pk})
        self.assertEqual(got, {"type": "notification", "notification": {"id": 7}})
        self.assertTrue(bob_silent)
        self.assertEqual(pong["type"], "pong")
