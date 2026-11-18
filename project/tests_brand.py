"""
Identité DevFlow « ampoule & engrenage » : fichiers générés, gabarits Django, e-mails.

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_brand
"""

from pathlib import Path

from django.conf import settings
from django.template import Context, Template
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase, override_settings

PUBLIC = Path(settings.BASE_DIR) / "frontend" / "public"


class BrandAssetsTests(SimpleTestCase):
    def test_generated_files_exist(self):
        for name in ("favicon.svg", "favicon-16.png", "favicon-32.png", "apple-touch-icon.png", "icon-192.png",
                     "icon-512.png", "icon-maskable-512.png", "brand/devflow-logo.png", "brand/devflow-logo-dark.png",
                     "brand/logo-mark.svg", "brand/logo-mark-dark.svg"):
            self.assertTrue((PUBLIC / name).is_file(), name)
        self.assertFalse((PUBLIC / "brand" / "logo.svg").exists())  # ancien logo « flux binaire » retiré
        favicon = (PUBLIC / "favicon.svg").read_text()
        self.assertIn("#FFD119", favicon)  # ampoule jaune
        self.assertIn("prefers-color-scheme:dark", favicon)  # engrenage crème en thème sombre

    def test_django_mark_partial_uses_current_color(self):
        html = render_to_string("partials/_devflow_mark.html", {"size": 30})
        self.assertIn('width="30"', html)
        self.assertIn('stroke="currentColor"', html)
        self.assertIn("#FFD119", html)

    def test_full_logo_partial_has_light_and_dark_versions(self):
        html = render_to_string("partials/_devflow_logo.html", {"height": 44})
        self.assertIn("/static/frontend/brand/devflow-logo.png", html)
        self.assertIn("/static/frontend/brand/devflow-logo-dark.png", html)
        self.assertIn('aria-label="DevFlow"', html)
        self.assertIn("height:44px", html)
        self.assertIn("devflow-logo--on-dark", render_to_string("partials/_devflow_logo.html", {"tone": "dark"}))


class BrandEmailTests(SimpleTestCase):
    def render(self):
        return Template('{% load devflow_extras %}{% brand_logo_url %}').render(Context())

    @override_settings(SITE_URL="https://flow.example.test/")
    def test_logo_url_is_absolute_when_site_url_is_set(self):
        self.assertEqual(self.render(), "https://flow.example.test/static/frontend/brand/devflow-logo.png")
        html = render_to_string("emails/workspace_invitation.html", {"workspace_name": "Alpha"})
        self.assertIn('<img src="https://flow.example.test/static/frontend/brand/devflow-logo.png" alt="DevFlow"', html)

    @override_settings(SITE_URL="")
    def test_no_logo_without_site_url(self):
        self.assertEqual(self.render(), "")
        self.assertNotIn("<img", render_to_string("emails/workspace_invitation.html", {"workspace_name": "Alpha"}))


@override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
class BrandPagesTests(TestCase):
    def test_login_page_shows_the_new_logo(self):
        html = self.client.get("/accounts/login/").content.decode()
        self.assertEqual(html.count("/static/frontend/brand/devflow-logo.png"), 2)  # carte visuelle + formulaire
        self.assertIn("devflow-logo--on-dark", html)  # carte visuelle sur fond sombre
        self.assertNotIn("Dev'Flow</div>", html)

    def test_legacy_sidebar_shows_the_new_logo(self):
        from django.contrib.auth import get_user_model

        from project import models as dm

        owner = get_user_model().objects.create_user("owner", "owner@a.test", "pw")
        ws = dm.Workspace.objects.create(name="Alpha", owner=owner)
        dm.UserProfile.objects.create(user=owner, workspace=ws)
        dm.TeamMembership.objects.create(user=owner, workspace=ws)
        self.client.force_login(owner)
        html = self.client.get("/teams/").content.decode()
        self.assertIn('class="logo"', html)
        self.assertIn("/static/frontend/brand/devflow-logo-dark.png", html)  # bascule en thème sombre
        self.assertNotIn("Dev<em>Flow</em>", html)
