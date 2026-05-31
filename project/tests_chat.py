"""
Tests Chat unifié — DM + groupes + cross-tenant.

Lance avec :
    python manage.py test project.tests_chat
"""

from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from project import models as dm
from project.services.chat import ChatService

User = get_user_model()


class ChatServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            username="alice_chat", email="ac@example.com", password="x",
        )
        cls.bob = User.objects.create_user(
            username="bob_chat", email="bc@example.com", password="x",
        )
        cls.charlie = User.objects.create_user(
            username="charlie_chat", email="cc@example.com", password="x",
        )
        cls.workspace = dm.Workspace.objects.create(
            name="WS Chat", owner=cls.alice,
        )
        # Alice + Bob + Charlie sont membres du même workspace via profile
        for u in (cls.alice, cls.bob, cls.charlie):
            dm.UserProfile.objects.create(user=u, workspace=cls.workspace)

    def test_find_or_create_direct_idempotent(self):
        c1 = ChatService.find_or_create_direct(
            user_a=self.alice, user_b=self.bob, workspace=self.workspace,
        )
        c2 = ChatService.find_or_create_direct(
            user_a=self.bob, user_b=self.alice, workspace=self.workspace,
        )
        self.assertEqual(c1.pk, c2.pk)
        # Toujours 2 membres
        self.assertEqual(c1.members.count(), 2)
        self.assertTrue(c1.is_private)

    def test_create_group_with_creator_auto_added(self):
        group = ChatService.create_group(
            workspace=self.workspace,
            name="Équipe DevFlow",
            members=[self.bob, self.charlie],
            creator=self.alice,
        )
        self.assertEqual(group.members.count(), 3)
        member_ids = set(group.members.values_list("pk", flat=True))
        self.assertEqual(
            member_ids, {self.alice.pk, self.bob.pk, self.charlie.pk},
        )

    def test_post_message_requires_membership(self):
        # Bob et Alice → canal DM
        channel = ChatService.find_or_create_direct(
            user_a=self.alice, user_b=self.bob, workspace=self.workspace,
        )
        # Charlie n'est pas dedans
        with self.assertRaises(PermissionError):
            ChatService.post_message(
                channel=channel, author=self.charlie, body="hack",
            )

    def test_post_and_list_messages(self):
        channel = ChatService.find_or_create_direct(
            user_a=self.alice, user_b=self.bob, workspace=self.workspace,
        )
        ChatService.post_message(channel=channel, author=self.alice, body="Hello")
        ChatService.post_message(channel=channel, author=self.bob, body="Salut !")
        messages = ChatService.latest_messages(
            channel=channel, user=self.alice,
        )
        self.assertEqual(len(messages), 2)
        # Le 1er affiché doit être le plus ancien
        self.assertEqual(messages[0]["body"], "Hello")
        self.assertEqual(messages[1]["body"], "Salut !")
        self.assertTrue(messages[0]["is_self"])  # Alice = expéditeur
        self.assertFalse(messages[1]["is_self"])

    def test_latest_messages_after_id_polling(self):
        channel = ChatService.find_or_create_direct(
            user_a=self.alice, user_b=self.bob, workspace=self.workspace,
        )
        m1 = ChatService.post_message(channel=channel, author=self.alice, body="1").message
        m2 = ChatService.post_message(channel=channel, author=self.alice, body="2").message
        # Polling : récupère uniquement après m1
        new = ChatService.latest_messages(
            channel=channel, user=self.alice, after_id=m1.pk,
        )
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0]["body"], "2")

    def test_contacts_includes_workspace_members_only(self):
        # User externe (autre workspace) — ne doit PAS apparaître
        outside = User.objects.create_user(
            username="outside", email="o@example.com", password="x",
        )
        other_ws = dm.Workspace.objects.create(name="Other WS", owner=outside)
        dm.UserProfile.objects.create(user=outside, workspace=other_ws)

        contacts = ChatService.contacts_for(self.alice)
        ids = {c["id"] for c in contacts}
        self.assertIn(self.bob.pk, ids)
        self.assertIn(self.charlie.pk, ids)
        self.assertNotIn(outside.pk, ids)
        self.assertNotIn(self.alice.pk, ids)  # pas soi-même


class ChatEndpointsCrossTenantTests(TestCase):
    """Vérifie qu'on ne peut pas écrire dans un canal d'un autre workspace."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            username="a_ep", email="aep@example.com", password="pw-a",
        )
        cls.bob_otherws = User.objects.create_user(
            username="b_other", email="bo@example.com", password="pw-b",
        )
        cls.ws_a = dm.Workspace.objects.create(name="WS A ep", owner=cls.alice)
        cls.ws_b = dm.Workspace.objects.create(name="WS B ep", owner=cls.bob_otherws)
        dm.UserProfile.objects.create(user=cls.alice, workspace=cls.ws_a)
        dm.UserProfile.objects.create(user=cls.bob_otherws, workspace=cls.ws_b)

        # Canal privé dans WS B entre 2 fictifs B-only — Alice ne doit pas y accéder
        cls.bob_friend = User.objects.create_user(
            username="b_friend", email="bf@example.com", password="x",
        )
        dm.UserProfile.objects.create(user=cls.bob_friend, workspace=cls.ws_b)
        cls.channel_b = ChatService.find_or_create_direct(
            user_a=cls.bob_otherws, user_b=cls.bob_friend, workspace=cls.ws_b,
        )

    def _login_alice(self):
        client = Client()
        client.login(username="a_ep", password="pw-a")
        return client

    def test_alice_does_not_see_channel_b_in_list(self):
        client = self._login_alice()
        resp = client.get("/api/v1/me/chat/channels/")
        self.assertEqual(resp.status_code, 200)
        channels = resp.json().get("channels", [])
        ids = {c["id"] for c in channels}
        self.assertNotIn(self.channel_b.pk, ids)

    def test_alice_cannot_get_messages_of_channel_b(self):
        client = self._login_alice()
        resp = client.get(
            f"/api/v1/me/chat/channels/{self.channel_b.pk}/messages/",
        )
        self.assertEqual(resp.status_code, 404)

    def test_alice_cannot_post_to_channel_b(self):
        client = self._login_alice()
        resp = client.post(
            f"/api/v1/me/chat/channels/{self.channel_b.pk}/messages/",
            data=json.dumps({"body": "intrusion"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)
        # Aucun message créé
        self.assertEqual(self.channel_b.messages.count(), 0)

    def test_alice_cannot_dm_user_from_other_workspace(self):
        client = self._login_alice()
        resp = client.post(
            "/api/v1/me/chat/direct/",
            data=json.dumps({"user_id": self.bob_otherws.pk}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)
