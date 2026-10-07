"""
Réinitialisation du mot de passe d'un membre depuis la liste des membres.

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_password_reset
"""

from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from project import models as dm
from project.tasks import send_member_password_reset_email_task

User = get_user_model()
OLD_PASSWORD = "Old-pass-1234"
NEW_PASSWORD = "N3w-Strong-pass!"


@override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
class MemberPasswordResetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("owner", "owner@a.test", OLD_PASSWORD, first_name="Olga", last_name="Owner")
        cls.member = User.objects.create_user("jean", "jean@a.test", OLD_PASSWORD, first_name="Jean", last_name="Dev")
        cls.peer = User.objects.create_user("luc", "luc@a.test", OLD_PASSWORD)
        cls.outsider = User.objects.create_user("bob", "bob@b.test", OLD_PASSWORD)
        cls.ws = dm.Workspace.objects.create(name="Tenant A", owner=cls.owner)
        cls.ws_b = dm.Workspace.objects.create(name="Tenant B", owner=cls.outsider)
        cls.memberships = {}
        for user, ws in ((cls.owner, cls.ws), (cls.member, cls.ws), (cls.peer, cls.ws), (cls.outsider, cls.ws_b)):
            dm.UserProfile.objects.create(user=user, workspace=ws)
            cls.memberships[user.username] = dm.TeamMembership.objects.create(user=user, workspace=ws)

    def setUp(self):
        cache.clear()
        patcher = mock.patch("project.tasks.send_member_password_reset_email_task.delay")
        self.delay = patcher.start()
        self.addCleanup(patcher.stop)

    def reset(self, actor, username, mode="link"):
        self.client.force_login(actor)
        url = reverse("team_membership_password_reset", args=[self.memberships[username].pk])
        return self.client.post(url, {"mode": mode})

    def reset_url(self):
        return self.delay.call_args.args[1]

    def test_link_mode_sends_link_and_keeps_current_password(self):
        resp = self.reset(self.owner, "jean")
        self.assertRedirects(resp, reverse("team_membership_list"), fetch_redirect_response=False)
        self.delay.assert_called_once()
        user_id, url, forced = self.delay.call_args.args[:3]
        self.assertEqual((user_id, forced), (self.member.pk, False))
        self.assertIn("/accounts/password/reset/key/", url)
        self.member.refresh_from_db()
        self.assertTrue(self.member.check_password(OLD_PASSWORD))
        self.assertTrue(dm.SecurityAuditLog.objects.filter(action="member.password_reset.link").exists())

    def test_force_mode_invalidates_current_password(self):
        self.reset(self.owner, "jean", mode="force")
        self.member.refresh_from_db()
        self.assertFalse(self.member.has_usable_password())
        self.assertTrue(self.delay.call_args.args[2])

    def test_link_lets_member_create_new_password_once(self):
        self.reset(self.owner, "jean", mode="force")
        url = self.reset_url()
        self.client.logout()
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)  # allauth : jeton validé → page « set-password »
        resp = self.client.post(resp["Location"], {"password1": NEW_PASSWORD, "password2": NEW_PASSWORD})
        self.assertEqual(resp.status_code, 302)
        self.member.refresh_from_db()
        self.assertTrue(self.member.check_password(NEW_PASSWORD))
        # Lien à usage unique
        self.client.logout()
        resp = self.client.get(url, follow=True)
        self.assertNotContains(resp, 'name="password1"')

    def test_email_contains_link(self):
        send_member_password_reset_email_task.run(
            self.member.pk, "https://devflow.test/accounts/password/reset/key/x-y/", True, "Olga Owner", "Tenant A",
        )
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.to, ["jean@a.test"])
        self.assertIn("Réinitialisation", email.subject)
        self.assertIn("https://devflow.test/accounts/password/reset/key/x-y/", email.body)
        self.assertIn("n'est plus valable", email.body)

    def test_permissions_and_isolation(self):
        # Membre sans droit RBAC
        self.reset(self.peer, "jean", mode="force")
        self.delay.assert_not_called()
        self.member.refresh_from_db()
        self.assertTrue(self.member.check_password(OLD_PASSWORD))
        # Autre tenant : membership introuvable
        self.assertEqual(self.reset(self.outsider, "jean").status_code, 404)
        # Soi-même
        self.reset(self.owner, "owner")
        self.delay.assert_not_called()

    def test_owner_and_inactive_accounts_protected(self):
        # Co-administrateur (rôle RBAC owner) : peut gérer les membres…
        dm.WorkspaceRoleAssignment.objects.create(workspace=self.ws, user=self.peer, role="WORKSPACE_OWNER")
        self.reset(self.peer, "jean")
        self.assertEqual(self.delay.call_count, 1)
        # …mais pas le propriétaire du workspace
        self.reset(self.peer, "owner", mode="force")
        self.assertEqual(self.delay.call_count, 1)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.check_password(OLD_PASSWORD))
        self.delay.reset_mock()
        User.objects.filter(pk=self.member.pk).update(is_active=False)
        self.reset(self.owner, "jean")
        self.delay.assert_not_called()

    def test_throttle_prevents_spam(self):
        self.reset(self.owner, "jean")
        self.reset(self.owner, "jean")
        self.assertEqual(self.delay.call_count, 1)

    def test_buttons_visible_only_to_managers(self):
        self.client.force_login(self.owner)
        page = self.client.get(reverse("team_membership_list"))
        self.assertContains(page, reverse("team_membership_password_reset", args=[self.memberships["jean"].pk]))
        self.assertNotContains(page, reverse("team_membership_password_reset", args=[self.memberships["owner"].pk]))
        self.client.force_login(self.peer)
        page = self.client.get(reverse("team_membership_list"))
        self.assertNotContains(page, "password-reset")
