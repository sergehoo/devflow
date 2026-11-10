"""Anciennes URL HTML migrées → pages React (navigation de page uniquement, réversible)."""

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from project.middleware_react import react_target

HTML = {"HTTP_ACCEPT": "text/html,application/xhtml+xml"}


@override_settings(DEVFLOW_REACT_DEFAULT=True)
class LegacyRedirectTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("u", "u@x.test", "pw"))

    def test_migrated_pages_redirect_to_react_with_safe_params(self):
        for legacy, target in (("/tasks/12/", "/app/tasks/12"), ("/meetings/5/?tab=recordings", "/app/meetings/5?tab=recordings"),
                               ("/billing/invoices/7/", "/app/invoices/7"), ("/profile/password/", "/app/profile"),
                               ("/risks/3/", "/app/m/risk/3"), ("/ai-proposals/4/", "/app/ai-proposals/4")):
            res = self.client.get(legacy, **HTML)
            self.assertEqual((res.status_code, res["Location"]), (302, target), legacy)

    def test_non_page_requests_are_untouched(self):
        self.assertNotEqual(self.client.get("/tasks/12/", HTTP_ACCEPT="application/json").status_code, 302)
        self.assertNotEqual(self.client.get("/tasks/12/", HTTP_HX_REQUEST="true", **HTML).status_code, 302)
        res = self.client.get("/tasks/12/?classic=1", **HTML)
        self.assertNotEqual(res.get("Location", ""), "/app/tasks/12")
        self.assertIsNone(react_target("/api/v1/tasks/1/", {}))
        self.assertIsNone(react_target("/ai-insights/dashboard/", {}))  # non migré : reste sur l'ancienne page

    @override_settings(DEVFLOW_REACT_DEFAULT=False)
    def test_rollback_disables_redirects(self):
        self.assertNotEqual(self.client.get("/tasks/12/", **HTML).get("Location", ""), "/app/tasks/12")
