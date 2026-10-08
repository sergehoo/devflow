"""
Sidebar simplifiée : groupes fusionnés, liens techniques retirés, pages
enfants toujours accessibles depuis leur page parente.

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_sidebar
"""

import re
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from project import models as dm
from project.templatetags.devflow_extras import nav_active

User = get_user_model()


class NavActiveFilterTests(SimpleTestCase):
    def test_prefix_matching(self):
        self.assertEqual(nav_active("sprint_review_list", "sprint_"), "lenk-active")
        self.assertEqual(nav_active("task_list", "project_list,task_"), "lenk-active")
        self.assertEqual(nav_active("milestone_task_list", "task_"), "")
        self.assertEqual(nav_active(None, "task_"), "")


@override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
class SidebarTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("owner", "owner@a.test", "pw")
        cls.member = User.objects.create_user("member", "member@a.test", "pw")
        cls.ws = dm.Workspace.objects.create(name="A", owner=cls.owner)
        for user in (cls.owner, cls.member):
            dm.UserProfile.objects.create(user=user, workspace=cls.ws)
            dm.TeamMembership.objects.create(user=user, workspace=cls.ws)
        cls.project = dm.Project.objects.create(workspace=cls.ws, name="P")
        today = date.today()
        cls.sprint = dm.Sprint.objects.create(
            workspace=cls.ws, project=cls.project, name="Sprint 1", number=1,
            start_date=today, end_date=today + timedelta(days=14),
        )
        cls.other_sprint = dm.Sprint.objects.create(
            workspace=cls.ws, project=cls.project, name="Sprint 2", number=2,
            start_date=today + timedelta(days=15), end_date=today + timedelta(days=29),
        )
        dm.SprintReview.objects.create(sprint=cls.sprint, demo_notes="Démo S1")
        dm.SprintReview.objects.create(sprint=cls.other_sprint, demo_notes="Démo S2")

    def sidebar(self, user, url_name="task_list", **kwargs):
        self.client.force_login(user)
        html = self.client.get(reverse(url_name, kwargs=kwargs or None)).content.decode()
        return html[html.index('<aside class="sidebar">'):html.index("</aside>")]

    def test_merged_groups_and_shorter_menu(self):
        html = self.sidebar(self.owner)
        groups = re.findall(r'<div class="nav-parent-left">.*?<span>(.*?)</span>', html, re.S)
        self.assertEqual(groups, ["Projets", "Exécution", "Équipes &amp; temps", "Finance", "Réunions", "Paramètres"])
        self.assertLessEqual(html.count("nav-subitem"), 32)
        for removed in ("Éléments checklist", "Labels tâches", "Labels projets", "Snapshots dashboard",
                        "Préférences utilisateur", "Colonnes board", "Tâches de milestone", "Éléments roadmap",
                        "Métriques sprint", "Membres channels", "Facturation", "Qualité &amp; gouvernance"):
            self.assertNotIn(removed, html)

    def test_finance_hidden_without_rights(self):
        html = self.sidebar(self.member)
        self.assertNotIn(">Finance<", html)
        self.assertNotIn("Factures", html)

    def test_child_page_highlights_parent(self):
        html = self.sidebar(self.owner, "sprint_review_list")
        self.assertRegex(html, r'nav-subitem lenk-active" href="/sprints/"')

    def test_child_pages_reachable_from_parent(self):
        self.client.force_login(self.owner)
        detail = self.client.get(reverse("sprint_detail", args=[self.sprint.pk])).content.decode()
        link = f"{reverse('sprint_review_list')}?sprint={self.sprint.pk}"
        self.assertIn(link, detail)
        reviews = self.client.get(link).context["object_list"]
        self.assertEqual([r.demo_notes for r in reviews], ["Démo S1"])
