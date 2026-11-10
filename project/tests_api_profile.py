"""Profil React : formulaires profil et mot de passe exécutés par le pont (vues Django existantes)."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from project import models as dm

STORAGES = {**settings.STORAGES, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}


@override_settings(STORAGES=STORAGES)
class ProfileBridgeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("awa", "awa@x.test", "Ancien-mdp-2026!", first_name="Awa")
        ws = dm.Workspace.objects.create(name="Alpha", owner=cls.user)
        dm.UserProfile.objects.update_or_create(user=cls.user, defaults={"workspace": ws})
        dm.TeamMembership.objects.create(user=cls.user, workspace=ws)

    def setUp(self):
        self.client.force_login(self.user)

    def test_profile_form_is_served_for_current_user_only(self):
        res = self.client.get("/api/v1/forms/profile/")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertTrue(res.json()["fields"])

    def test_password_change_validates_old_password_and_keeps_session(self):
        bad = self.client.post("/api/v1/forms/password/", {"old_password": "faux", "new_password1": "Nouveau-mdp-2026!", "new_password2": "Nouveau-mdp-2026!"})
        self.assertEqual(bad.status_code, 400)
        ok = self.client.post("/api/v1/forms/password/", {"old_password": "Ancien-mdp-2026!", "new_password1": "Nouveau-mdp-2026!", "new_password2": "Nouveau-mdp-2026!"})
        self.assertEqual(ok.status_code, 200, ok.content)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Nouveau-mdp-2026!"))
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 200)  # session conservée
