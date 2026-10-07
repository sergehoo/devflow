"""
Pages d'authentification (gabarit account/base_auth.html).

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_auth_pages
"""

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

User = get_user_model()


@override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
class AuthPagesTests(TestCase):
    def test_login_page_is_complete_and_clean(self):
        resp = self.client.get("/accounts/login/?next=/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('type="email"', html)
        self.assertIn("Adresse email", html)
        self.assertIn('class="hero-title"', html)
        for leftover in ("128+", "+18%", "floating-chip", "Live sprint tracking", "{#"):
            self.assertNotIn(leftover, html)
        self.assertEqual(html.count('class="company-logo-top"'), 1)

    def test_bad_credentials_show_error_and_keep_email(self):
        resp = self.client.post("/accounts/login/", {"login": "jean@a.test", "password": "faux"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "msg-error")
        self.assertContains(resp, 'value="jean@a.test"')

    def test_other_auth_pages_render(self):
        for url in ("/accounts/password/reset/", "/accounts/signup/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)
