"""
API d'authentification du frontend React + page /app/.

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_api_auth
"""

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from project import models as dm

User = get_user_model()


@override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
class AuthApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("serge", "serge@a.test", "Str0ng-pass!", first_name="Serge", last_name="OGAH")
        cls.other = User.objects.create_user("bob", "bob@b.test", "Str0ng-pass!")
        EmailAddress.objects.create(user=cls.user, email=cls.user.email, verified=True, primary=True)
        cls.ws = dm.Workspace.objects.create(name="DATARIUM", owner=cls.user)
        cls.ws2 = dm.Workspace.objects.create(name="KAYDAN", owner=cls.user)
        cls.ws_b = dm.Workspace.objects.create(name="Autre", owner=cls.other)
        dm.UserProfile.objects.create(user=cls.user, workspace=cls.ws)
        dm.TeamMembership.objects.create(user=cls.user, workspace=cls.ws)

    def csrf_client(self):
        client = Client(enforce_csrf_checks=True)
        client.get("/api/v1/auth/csrf/")
        return client, client.cookies["csrftoken"].value

    def test_me_requires_session(self):
        self.assertIn(self.client.get("/api/v1/auth/me/").status_code, (401, 403))

    def test_login_with_csrf_then_me_and_logout(self):
        client, token = self.csrf_client()
        resp = client.post("/api/v1/auth/login/", {"login": "serge@a.test", "password": "Str0ng-pass!"},
                           content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(resp.status_code, 200, resp.content)
        me = client.get("/api/v1/auth/me/").json()
        self.assertEqual((me["full_name"], me["workspace"]["name"]), ("Serge OGAH", "DATARIUM"))
        self.assertEqual(me["workspace"]["role"], "WORKSPACE_OWNER")
        self.assertEqual({w["name"] for w in me["workspaces"]}, {"DATARIUM", "KAYDAN"})
        self.assertIn("members.manage", me["permissions"])
        token = client.cookies["csrftoken"].value
        self.assertEqual(client.post("/api/v1/auth/logout/", HTTP_X_CSRFTOKEN=token).status_code, 200)
        self.assertIn(client.get("/api/v1/auth/me/").status_code, (401, 403))

    def test_login_rejects_bad_password_and_missing_csrf(self):
        client, token = self.csrf_client()
        resp = client.post("/api/v1/auth/login/", {"login": "serge@a.test", "password": "faux"},
                           content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(resp.json()["detail"])
        resp = Client(enforce_csrf_checks=True).post(
            "/api/v1/auth/login/", {"login": "serge@a.test", "password": "Str0ng-pass!"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_workspace_switch_restricted_to_member_workspaces(self):
        self.client.force_login(self.user)
        resp = self.client.post("/api/v1/auth/workspace/", {"workspace_id": self.ws2.pk}, content_type="application/json")
        self.assertEqual(resp.json()["workspace"]["name"], "KAYDAN")
        resp = self.client.post("/api/v1/auth/workspace/", {"workspace_id": self.ws_b.pk}, content_type="application/json")
        self.assertEqual(resp.status_code, 404)

    def test_react_app_route_coexists(self):
        resp = self.client.get("/app/projects/12/")
        self.assertIn(resp.status_code, (200, 503))  # 503 tant que le build n'existe pas
        self.assertIn("csrftoken", resp.cookies)
        self.assertEqual(self.client.get("/accounts/login/").status_code, 200)  # ancien frontend intact
