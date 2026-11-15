"""
Régressions : les heures saisies dans les timesheets alimentent les projets.

* grille hebdomadaire sur une tâche → ``Task.spent_hours`` suit les saisies
  (création, modification, suppression, déplacement vers une autre tâche) ;
* lignes « activité » (projet sans tâche) → comptées dans le temps consommé
  du projet ;
* rattrapage de l'historique (migration 0058) non destructif ;
* isolation : impossible de saisir sur le projet d'un autre workspace.
"""
import importlib
import json
from datetime import timedelta
from decimal import Decimal

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from project import models as dm
from project.services import project_time

User = get_user_model()


@override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
class TimesheetProjectSyncTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("ts-owner", "ts-owner@example.test", "pw")
        cls.dev = User.objects.create_user("ts-dev", "ts-dev@example.test", "pw")
        cls.workspace = dm.Workspace.objects.create(name="Pôle Dev", owner=cls.owner)
        for user in (cls.owner, cls.dev):
            dm.UserProfile.objects.create(user=user, workspace=cls.workspace)
            dm.TeamMembership.objects.create(user=user, workspace=cls.workspace)
        cls.project = dm.Project.objects.create(workspace=cls.workspace, name="ARTEPRIX")
        cls.other_owner = User.objects.create_user("ts-other", "ts-other@example.test", "pw")
        cls.other_ws = dm.Workspace.objects.create(name="Autre tenant", owner=cls.other_owner)
        cls.foreign_project = dm.Project.objects.create(workspace=cls.other_ws, name="Projet étranger")

    def setUp(self):
        self.task = dm.Task.objects.create(
            workspace=self.workspace, project=self.project, title="Correction DQE", assignee=self.dev,
        )
        self.monday = timezone.localdate() - timedelta(days=timezone.localdate().weekday())
        self.client.force_login(self.dev)

    def save_cell(self, **payload):
        return self.client.post(
            reverse("timesheet_calendar_save"), data=json.dumps({"date": self.monday.isoformat(), **payload}),
            content_type="application/json",
        )

    def spent(self):
        self.task.refresh_from_db()
        return self.task.spent_hours

    def test_weekly_grid_updates_task_spent_hours(self):
        self.assertEqual(self.save_cell(task_id=self.task.pk, hours="3").status_code, 200)
        self.assertEqual(self.spent(), Decimal("3"))
        self.assertEqual(self.save_cell(task_id=self.task.pk, hours="5.5").status_code, 200)
        self.assertEqual(self.spent(), Decimal("5.5"))
        self.save_cell(task_id=self.task.pk, hours="2", date=(self.monday + timedelta(days=1)).isoformat())
        self.assertEqual(self.spent(), Decimal("7.5"))
        # Cellule vidée → saisie supprimée → temps passé recalculé.
        self.assertEqual(self.save_cell(task_id=self.task.pk, hours="0").status_code, 200)
        self.assertEqual(self.spent(), Decimal("2"))

    def test_moving_an_entry_recomputes_both_tasks(self):
        other = dm.Task.objects.create(workspace=self.workspace, project=self.project, title="Autre", assignee=self.dev)
        entry = dm.TimesheetEntry.objects.create(
            user=self.dev, workspace=self.workspace, project=self.project, task=self.task,
            entry_date=self.monday, hours=Decimal("4"),
        )
        self.assertEqual(self.spent(), Decimal("4"))
        entry.task = other
        entry.save()
        other.refresh_from_db()
        self.assertEqual((self.spent(), other.spent_hours), (Decimal("0"), Decimal("4")))
        entry.delete()
        other.refresh_from_db()
        self.assertEqual(other.spent_hours, Decimal("0"))

    def test_activity_rows_count_in_project_consumed_time(self):
        self.save_cell(task_id=self.task.pk, hours="3")
        self.assertEqual(self.save_cell(project_id=self.project.pk, description="Réunion client", hours="2").status_code, 200)
        logged = project_time.project_logged_hours(self.project)
        self.assertEqual(logged, {"tasks": Decimal("3"), "activities": Decimal("2"), "total": Decimal("5")})

        api = APIClient()
        api.force_authenticate(self.owner)
        summary = api.get(f"/api/v1/projects/{self.project.pk}/summary/")
        self.assertEqual(summary.status_code, 200, summary.content)
        self.assertEqual((summary.data["spent_hours"], summary.data["logged_hours"], summary.data["activity_hours"]),
                         (3.0, 5.0, 2.0))

    def test_cannot_log_activity_on_another_workspace_project(self):
        response = self.save_cell(project_id=self.foreign_project.pk, description="Intrusion", hours="1")
        self.assertEqual(response.status_code, 404)
        self.assertFalse(dm.TimesheetEntry.objects.filter(project=self.foreign_project).exists())


class SpentHoursBackfillMigrationTests(TestCase):
    """Migration 0058 : relève ``spent_hours`` sous la somme des saisies, ne baisse jamais une saisie manuelle."""

    def test_backfill_raises_only(self):
        owner = User.objects.create_user("bf-owner", "bf@example.test", "pw")
        ws = dm.Workspace.objects.create(name="Backfill", owner=owner)
        project = dm.Project.objects.create(workspace=ws, name="Historique")
        late = dm.Task.objects.create(workspace=ws, project=project, title="Saisies non reportées")
        manual = dm.Task.objects.create(workspace=ws, project=project, title="Temps manuel")
        for task, hours in ((late, "6"), (manual, "1")):
            dm.TimesheetEntry.objects.create(user=owner, workspace=ws, project=project, task=task,
                                             entry_date=timezone.localdate(), hours=Decimal(hours))
        # État hérité d'avant la synchronisation (écrit sans passer par les signaux).
        dm.Task.objects.filter(pk=late.pk).update(spent_hours=Decimal("0"))
        dm.Task.objects.filter(pk=manual.pk).update(spent_hours=Decimal("9"))

        other = dm.Project.objects.create(workspace=ws, name="Autre")
        stray = dm.TimesheetEntry.objects.create(user=owner, workspace=ws, project=project, task=late,
                                                 entry_date=timezone.localdate(), hours=Decimal("0.5"))
        dm.TimesheetEntry.objects.filter(pk=stray.pk).update(project=other)  # état hérité incohérent
        dm.Task.objects.filter(pk=late.pk).update(spent_hours=Decimal("0"))

        module = importlib.import_module("project.migrations.0058_sync_task_spent_hours")
        module.attach_entries_to_task_project(django_apps, None)
        module.raise_spent_hours(django_apps, None)

        late.refresh_from_db()
        manual.refresh_from_db()
        stray.refresh_from_db()
        self.assertEqual((late.spent_hours, manual.spent_hours), (Decimal("6.5"), Decimal("9")))
        self.assertEqual(stray.project_id, project.pk)


@override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
class TimesheetCostInProjectFinanceTests(TestCase):
    """Le temps saisi (tâches + activités) est valorisé au TJM dans le coût réel du projet."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("fin-owner", "fin-owner@example.test", "pw")
        cls.dev = User.objects.create_user("fin-dev", "fin-dev@example.test", "pw")
        cls.workspace = dm.Workspace.objects.create(name="Finance TJM", owner=cls.owner)
        for user in (cls.owner, cls.dev):
            dm.TeamMembership.objects.create(user=user, workspace=cls.workspace)
        dm.UserProfile.objects.create(user=cls.owner, workspace=cls.workspace)
        dm.UserProfile.objects.create(user=cls.dev, workspace=cls.workspace,
                                      cost_per_day=Decimal("100000"), capacity_hours_per_day=Decimal("8"))
        cls.project = dm.Project.objects.create(workspace=cls.workspace, name="ANALYTICS HUB", owner=cls.owner)
        cls.task = dm.Task.objects.create(workspace=cls.workspace, project=cls.project, title="API", assignee=cls.dev)
        cls.human = dm.CostCategory.objects.create(name="Personnel", category_type=dm.CostCategory.CategoryType.HUMAN)
        cls.software = dm.CostCategory.objects.create(name="Licences", category_type=dm.CostCategory.CategoryType.SOFTWARE)

    def log(self, hours, task=None, description=""):
        return dm.TimesheetEntry.objects.create(
            user=self.dev, workspace=self.workspace, project=self.project, task=task,
            entry_date=timezone.localdate(), hours=Decimal(hours), description=description,
        )

    def overview(self):
        from project.services.budget import ProjectBudgetService

        return ProjectBudgetService.build_budget_overview(self.project)

    def test_logged_time_is_part_of_actual_cost(self):
        self.log("4", task=self.task)
        self.log("4", description="Atelier client")  # activité hors tâche
        ov = self.overview()
        # 8 h = 1 jour à 100 000 de TJM coût.
        self.assertEqual(ov["timesheet_logged_cost"], Decimal("100000.00"))
        self.assertEqual((ov["actual_cost"], ov["actual_labor_cost"]), (Decimal("100000.00"), Decimal("100000.00")))

    def test_labor_expense_and_timesheets_are_not_double_counted(self):
        self.log("8", task=self.task)
        dm.ProjectExpense.objects.create(project=self.project, title="Paie", category=self.human,
                                         amount=Decimal("150000"), status=dm.ProjectExpense.ExpenseStatus.PAID)
        dm.ProjectExpense.objects.create(project=self.project, title="Licence", category=self.software,
                                         amount=Decimal("20000"), status=dm.ProjectExpense.ExpenseStatus.PAID)
        ov = self.overview()
        # RH : max(150 000 comptabilisés, 100 000 pointés) + 20 000 de licences.
        self.assertEqual(ov["actual_cost"], Decimal("170000"))
        self.assertEqual(ov["actual_expense_cost"], Decimal("170000"))

    def test_zero_hours_entry_has_no_cost(self):
        entry = self.log("8", task=self.task)
        entry.hours = Decimal("0")
        entry.planned_hours = Decimal("8")
        entry.save()
        self.assertEqual(self.overview()["timesheet_logged_cost"], Decimal("0"))

    def test_entry_follows_its_task_project(self):
        other = dm.Project.objects.create(workspace=self.workspace, name="Autre projet", owner=self.owner)
        entry = dm.TimesheetEntry.objects.create(user=self.dev, workspace=self.workspace, project=other, task=self.task,
                                                 entry_date=timezone.localdate(), hours=Decimal("2"))
        entry.refresh_from_db()
        self.assertEqual(entry.project_id, self.project.pk)

    def test_project_page_shows_labor_cost_and_activity_hours(self):
        self.log("4", task=self.task)
        self.log("4", description="Atelier client")
        api = APIClient()
        api.force_authenticate(self.owner)
        forecast = api.get(f"/api/v1/projects/{self.project.pk}/detail-tabs/", {"tab": "budget_previsionnel"})
        self.assertEqual(forecast.status_code, 200, forecast.content)
        tab = forecast.json()["tab"]
        self.assertEqual(Decimal(tab["actual_cost"]), Decimal("100000"))
        self.assertEqual(Decimal(tab["timesheet_labor_cost"]), Decimal("100000"))
        self.assertEqual(Decimal(tab["timesheet_hours"]), Decimal("8"))
        tasks = api.get(f"/api/v1/projects/{self.project.pk}/detail-tabs/", {"tab": "taches"}).json()["tab"]["stats"]
        self.assertEqual((Decimal(tasks["total_spent_hours"]), Decimal(tasks["activity_hours"]), Decimal(tasks["logged_hours"])),
                         (Decimal("4"), Decimal("4"), Decimal("8")))

    def test_task_form_keeps_computed_spent_hours(self):
        from project.forms import TaskForm

        self.log("3", task=self.task)
        form = TaskForm(instance=self.task)
        self.assertTrue(form.fields["spent_hours"].disabled)
        api = APIClient()
        api.force_authenticate(self.owner)
        res = api.patch(f"/api/v1/tasks/{self.task.pk}/", {"spent_hours": "99", "title": "API v2"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.task.refresh_from_db()
        self.assertEqual((self.task.title, self.task.spent_hours), ("API v2", Decimal("3")))
