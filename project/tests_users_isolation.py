"""
Tests d'isolation des utilisateurs entre workspaces.

Vérifie qu'aucune zone d'affichage ne révèle un utilisateur d'un autre
workspace :
    * Helper users_in_workspaces / users_for_user
    * Endpoint /api/v1/me/chat/contacts/
    * Form TaskForm assignee queryset

Lance avec :
    python manage.py test project.tests_users_isolation
"""

from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from project import models as dm
from project.utils.workspaces import users_for_user, users_in_workspaces

User = get_user_model()


class UsersHelperIsolationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Workspace A
        cls.alice = User.objects.create_user(
            username="alice_iso", email="ai@e.com", password="x",
        )
        cls.ws_a = dm.Workspace.objects.create(name="WS Iso A", owner=cls.alice)
        dm.UserProfile.objects.create(user=cls.alice, workspace=cls.ws_a)

        cls.bob = User.objects.create_user(
            username="bob_iso", email="bi@e.com", password="x",
        )
        dm.UserProfile.objects.create(user=cls.bob, workspace=cls.ws_a)

        # Workspace B (totalement isolé)
        cls.carol = User.objects.create_user(
            username="carol_iso", email="ci@e.com", password="x",
        )
        cls.ws_b = dm.Workspace.objects.create(name="WS Iso B", owner=cls.carol)
        dm.UserProfile.objects.create(user=cls.carol, workspace=cls.ws_b)

        # User externe (aucun workspace)
        cls.outsider = User.objects.create_user(
            username="outsider", email="o@e.com", password="x",
        )

    def test_users_in_workspaces_strict_isolation(self):
        in_a = list(users_in_workspaces([self.ws_a.pk]).values_list("pk", flat=True))
        in_b = list(users_in_workspaces([self.ws_b.pk]).values_list("pk", flat=True))
        self.assertIn(self.alice.pk, in_a)
        self.assertIn(self.bob.pk, in_a)
        self.assertNotIn(self.carol.pk, in_a)
        self.assertNotIn(self.outsider.pk, in_a)
        self.assertIn(self.carol.pk, in_b)
        self.assertNotIn(self.alice.pk, in_b)

    def test_users_for_user_returns_only_own_workspaces(self):
        # Alice (WS A) ne doit voir QUE alice + bob, jamais carol
        visible_ids = set(users_for_user(self.alice).values_list("pk", flat=True))
        self.assertIn(self.alice.pk, visible_ids)
        self.assertIn(self.bob.pk, visible_ids)
        self.assertNotIn(self.carol.pk, visible_ids)
        self.assertNotIn(self.outsider.pk, visible_ids)

    def test_users_for_user_superuser_sees_all(self):
        admin = User.objects.create_superuser(
            username="admin_iso", email="a@e.com", password="x",
        )
        visible_ids = set(users_for_user(admin).values_list("pk", flat=True))
        # SuperAdmin voit tout le monde actif
        for u in (self.alice, self.bob, self.carol, self.outsider):
            self.assertIn(u.pk, visible_ids,
                msg=f"SuperAdmin doit voir {u.username}")

    def test_anonymous_user_sees_no_one(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertEqual(users_for_user(AnonymousUser()).count(), 0)

    def test_inactive_users_excluded(self):
        self.bob.is_active = False
        self.bob.save()
        visible_ids = set(users_for_user(self.alice).values_list("pk", flat=True))
        self.assertNotIn(self.bob.pk, visible_ids)


class ChatContactsCrossTenantTests(TestCase):
    """Vérifie que GET /api/v1/me/chat/contacts/ ne fuite jamais."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            username="alice_chat_iso", email="ac@e.com", password="pw-a",
        )
        cls.ws_a = dm.Workspace.objects.create(name="WS A Chat", owner=cls.alice)
        dm.UserProfile.objects.create(user=cls.alice, workspace=cls.ws_a)

        cls.bob = User.objects.create_user(
            username="bob_chat_iso", email="bc@e.com", password="x",
        )
        dm.UserProfile.objects.create(user=cls.bob, workspace=cls.ws_a)

        cls.carol = User.objects.create_user(
            username="carol_chat_iso", email="cc@e.com", password="x",
        )
        ws_b = dm.Workspace.objects.create(name="WS B Chat", owner=cls.carol)
        dm.UserProfile.objects.create(user=cls.carol, workspace=ws_b)

    def test_contacts_endpoint_excludes_other_workspace(self):
        client = Client()
        client.login(username="alice_chat_iso", password="pw-a")
        resp = client.get("/api/v1/me/chat/contacts/")
        self.assertEqual(resp.status_code, 200)
        contacts = resp.json().get("contacts", [])
        usernames = [c["username"] for c in contacts]
        self.assertIn("bob_chat_iso", usernames)
        self.assertNotIn("carol_chat_iso", usernames,
            msg="Carol (autre workspace) ne doit pas apparaître dans les contacts")
        self.assertNotIn("alice_chat_iso", usernames,
            msg="L'utilisateur lui-même ne doit pas apparaître dans ses contacts")


class TaskFormAssigneeIsolationTests(TestCase):
    """Le queryset assignee de TaskForm ne doit jamais exposer d'user d'un autre workspace."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            username="a_tf", email="atf@e.com", password="x",
        )
        cls.ws_a = dm.Workspace.objects.create(name="WS A TF", owner=cls.alice)
        dm.UserProfile.objects.create(user=cls.alice, workspace=cls.ws_a)
        dm.TeamMembership.objects.create(
            user=cls.alice, workspace=cls.ws_a, role="ADMIN",
        )

        cls.bob = User.objects.create_user(
            username="b_tf", email="btf@e.com", password="x",
        )
        dm.UserProfile.objects.create(user=cls.bob, workspace=cls.ws_a)
        dm.TeamMembership.objects.create(
            user=cls.bob, workspace=cls.ws_a, role="DEVELOPER",
        )

        cls.carol_other_ws = User.objects.create_user(
            username="c_tf", email="ctf@e.com", password="x",
        )
        other_ws = dm.Workspace.objects.create(name="WS B TF", owner=cls.carol_other_ws)
        dm.UserProfile.objects.create(user=cls.carol_other_ws, workspace=other_ws)
        dm.TeamMembership.objects.create(
            user=cls.carol_other_ws, workspace=other_ws, role="ADMIN",
        )

    def test_taskform_assignee_excludes_other_workspace_users(self):
        from project.forms import TaskForm

        form = TaskForm(
            current_workspace=self.ws_a,
            current_user=self.alice,
        )
        # Le queryset des assignees ne doit pas inclure carol
        assignees = list(form.fields["assignee"].queryset.values_list(
            "username", flat=True,
        ))
        self.assertIn("a_tf", assignees)
        self.assertIn("b_tf", assignees)
        self.assertNotIn("c_tf", assignees,
            msg="Carol (autre workspace) ne doit pas être assignable")
