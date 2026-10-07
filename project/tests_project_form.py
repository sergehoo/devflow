"""
Formulaire projet : erreurs explicites (type + section + champ), aucune
erreur silencieuse, champs obligatoires réellement affichés.

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_project_form
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from project import models as dm

User = get_user_model()


@override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
class ProjectFormErrorsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("owner", "owner@a.test", "pw")
        cls.other = User.objects.create_user("bob", "bob@b.test", "pw")
        cls.ws = dm.Workspace.objects.create(name="DATARIUM", owner=cls.owner)
        cls.ws_b = dm.Workspace.objects.create(name="Autre", owner=cls.other)
        dm.UserProfile.objects.create(user=cls.owner, workspace=cls.ws)
        dm.TeamMembership.objects.create(user=cls.owner, workspace=cls.ws)
        cls.team = dm.Team.objects.create(workspace=cls.ws, name="Backend-Developer Team")
        cls.data_team = dm.Team.objects.create(workspace=cls.ws, name="DATA / AI TEAM")
        cls.foreign_team = dm.Team.objects.create(workspace=cls.ws_b, name="Équipe étrangère")

    def setUp(self):
        self.client.force_login(self.owner)

    def payload(self, **extra):
        data = {
            "name": "Oasis-Trading", "methodology": "AGILE", "status": "PLANNED",
            "priority": "MEDIUM", "health_status": "GRAY", "progress_percent": "0",
            "team": self.team.pk, "teams": [self.data_team.pk],
        }
        data.update(extra)
        return {k: v for k, v in data.items() if v is not None}

    def test_create_page_shows_required_methodology(self):
        resp = self.client.get(reverse("project_create"))
        self.assertContains(resp, 'name="methodology"')
        self.assertContains(resp, "Méthodologie de gestion")

    def test_errors_listed_with_type_and_location(self):
        resp = self.client.post(reverse("project_create"), self.payload(
            name="", methodology=None, team=self.foreign_team.pk,
        ))
        self.assertEqual(resp.status_code, 200)
        report = resp.context["form"].error_report()
        found = {(e["type"], e["section"], e["label"]) for e in report}
        self.assertIn(("Champ obligatoire", "Informations générales", "Nom du projet"), found)
        self.assertIn(("Champ obligatoire", "Informations générales", "Méthodologie de gestion"), found)
        self.assertIn(("Choix non autorisé", "Informations générales", "Équipe principale"), found)
        self.assertContains(resp, 'id="form-error-summary"')
        self.assertContains(resp, "Enregistrement impossible : 3 erreurs à corriger")
        self.assertContains(resp, 'href="#id_name"')
        self.assertContains(resp, 'aria-invalid="true"')
        self.assertFalse(dm.Project.objects.exists())

    def test_coherence_rule_reported_on_field(self):
        today = timezone.localdate()
        resp = self.client.post(reverse("project_create"), self.payload(
            start_date=today.isoformat(), target_date=(today - timedelta(days=5)).isoformat(),
        ))
        report = resp.context["form"].error_report()
        self.assertEqual(
            [(e["type"], e["section"], e["label"]) for e in report],
            [("Règle de cohérence", "Planning & budget", "Date cible")],
        )

    def test_valid_project_is_created(self):
        resp = self.client.post(reverse("project_create"), self.payload())
        project = dm.Project.objects.get(name="Oasis-Trading")
        self.assertRedirects(resp, reverse("project_detail", args=[project.pk]), fetch_redirect_response=False)
        self.assertEqual(project.methodology, "AGILE")
        self.assertEqual(set(project.teams.all()), {self.data_team})

    def test_late_project_saved_with_warning(self):
        past = timezone.localdate() - timedelta(days=30)
        resp = self.client.post(reverse("project_create"), self.payload(
            start_date=(past - timedelta(days=60)).isoformat(), target_date=past.isoformat(),
        ), follow=True)
        self.assertTrue(dm.Project.objects.filter(name="Oasis-Trading").exists())
        self.assertContains(resp, "Ce projet est en retard")

    def test_update_keeps_methodology_and_contributing_teams(self):
        project = dm.Project.objects.create(workspace=self.ws, name="Existant", methodology="SCRUM")
        project.teams.add(self.data_team)
        page = self.client.get(reverse("project_update", args=[project.pk]))
        self.assertContains(page, 'name="methodology"')
        self.assertContains(page, 'name="teams"')
        resp = self.client.post(reverse("project_update", args=[project.pk]), self.payload(
            name="Existant renommé", methodology="SCRUM",
        ))
        self.assertEqual(resp.status_code, 302, resp.context and resp.context["form"].error_report())
        project.refresh_from_db()
        self.assertEqual((project.name, project.methodology), ("Existant renommé", "SCRUM"))
        self.assertEqual(set(project.teams.all()), {self.data_team})
