"""
API Timesheets (React, Phase 3) : mêmes règles que l'interface Django.

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_api_timesheets
"""

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from project import models as dm

User = get_user_model()
MONDAY = date(2026, 10, 5)


@override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
class TimesheetApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.lead = User.objects.create_user("lead", "lead@a.test", "pw", first_name="Léa")
        cls.dev = User.objects.create_user("dev", "dev@a.test", "pw", first_name="Dan")
        cls.peer = User.objects.create_user("peer", "peer@a.test", "pw")
        cls.bob = User.objects.create_user("bob", "bob@b.test", "pw")
        cls.ws = dm.Workspace.objects.create(name="Alpha", owner=cls.lead)
        cls.other = dm.Workspace.objects.create(name="Beta", owner=cls.bob)
        lead_p = dm.UserProfile.objects.create(user=cls.lead, workspace=cls.ws, capacity_hours_per_week=40)
        dm.UserProfile.objects.create(user=cls.dev, workspace=cls.ws, manager=lead_p, capacity_hours_per_week=40)
        dm.UserProfile.objects.create(user=cls.peer, workspace=cls.ws, capacity_hours_per_week=40)
        dm.UserProfile.objects.create(user=cls.bob, workspace=cls.other)
        for u, ws in ((cls.lead, cls.ws), (cls.dev, cls.ws), (cls.peer, cls.ws), (cls.bob, cls.other)):
            dm.TeamMembership.objects.create(user=u, workspace=ws)
        cls.project = dm.Project.objects.create(workspace=cls.ws, name="Portail")
        cls.task = dm.Task.objects.create(
            workspace=cls.ws, project=cls.project, title="API", assignee=cls.dev, start_date=MONDAY - timedelta(days=7),
        )
        cls.foreign_project = dm.Project.objects.create(workspace=cls.other, name="Secret")

    def cell(self, **data):
        return self.client.post("/api/v1/actions/timesheet-cell/", data)

    def week_action(self, action, user=None, comment=""):
        return self.client.post("/api/v1/actions/timesheet-week/", {
            "user": (user or self.dev).pk, "monday": MONDAY.isoformat(), "action": action, "comment": comment,
        })

    def test_entry_totals_and_no_duplicate(self):
        self.client.force_login(self.dev)
        res = self.cell(task_id=self.task.pk, date=MONDAY.isoformat(), hours="3")
        self.assertEqual(res.status_code, 200, res.content)
        res = self.cell(task_id=self.task.pk, date=MONDAY.isoformat(), hours="4,5")  # même cellule → mise à jour
        self.assertEqual((res.json()["day_total"], res.json()["week_total"]), (4.5, 4.5))
        self.cell(project_id=self.project.pk, description="Réunion client", date=(MONDAY + timedelta(days=1)).isoformat(), hours="2")
        self.assertEqual(dm.TimesheetEntry.objects.filter(user=self.dev).count(), 2)

        week = self.client.get("/api/v1/timesheet/week/", {"date": (MONDAY + timedelta(days=3)).isoformat()}).json()
        self.assertEqual(week["monday"], MONDAY.isoformat())
        self.assertEqual(week["week_total"], 6.5)
        self.assertEqual(week["summary"]["total_hours"], 6.5)
        rows = {r["kind"]: r for r in week["rows"]}
        self.assertEqual(rows["task"]["cells"][0]["hours"], 4.5)
        self.assertEqual(rows["activity"]["label"], "Réunion client")
        self.assertEqual(week["day_totals"][MONDAY.isoformat()], 4.5)

        self.cell(task_id=self.task.pk, date=MONDAY.isoformat(), hours="0")  # 0 h supprime la cellule
        self.assertEqual(dm.TimesheetEntry.objects.filter(user=self.dev, task=self.task).count(), 0)

    def test_cell_validation_and_isolation(self):
        self.client.force_login(self.dev)
        self.assertEqual(self.cell(task_id=self.task.pk, date=MONDAY.isoformat(), hours="25").status_code, 400)
        res = self.cell(project_id=self.foreign_project.pk, description="x", date=MONDAY.isoformat(), hours="1")
        self.assertEqual(res.status_code, 404)
        self.assertIn("detail", res.json())
        self.client.force_login(self.peer)  # non affecté à la tâche
        self.assertEqual(self.cell(task_id=self.task.pk, date=MONDAY.isoformat(), hours="1").status_code, 403)

    def test_submit_lock_reject_and_correction_workflow(self):
        self.client.force_login(self.dev)
        self.cell(task_id=self.task.pk, date=MONDAY.isoformat(), hours="8")
        self.assertEqual(self.week_action("submit").status_code, 200)
        locked = self.cell(task_id=self.task.pk, date=MONDAY.isoformat(), hours="7")
        self.assertEqual(locked.status_code, 403)
        self.assertEqual(self.week_action("approve").status_code, 400)  # pas d'auto-validation (N+1 uniquement)
        self.assertEqual(dm.TimesheetEntry.objects.get(user=self.dev).approval_status, "SUBMITTED")

        self.client.force_login(self.peer)  # pas son N+1 → la semaine n'est pas visible
        self.assertEqual(self.week_action("approve").status_code, 404)

        self.client.force_login(self.lead)
        res = self.week_action("reject")
        self.assertEqual(res.status_code, 400)  # commentaire obligatoire
        self.assertEqual(self.week_action("reject", comment="Détail manquant").status_code, 200)
        weeks = self.client.get("/api/v1/timesheet/weeks/", {"scope": "review"}).json()["results"]
        self.assertEqual([(w["user"]["id"], w["status"], w["can_review"]) for w in weeks], [(self.dev.pk, "REJECTED", True)])
        week = self.client.get("/api/v1/timesheet/week/", {"user": self.dev.pk, "date": MONDAY.isoformat()}).json()
        self.assertTrue(week["can_review"])
        self.assertEqual(week["history"][0]["comment"], "Détail manquant")

        self.client.force_login(self.dev)  # correction → la semaine repasse en brouillon
        self.cell(task_id=self.task.pk, date=MONDAY.isoformat(), hours="7")
        self.assertEqual(dm.TimesheetEntry.objects.get(user=self.dev).approval_status, "DRAFT")
        self.week_action("submit")
        self.client.force_login(self.lead)
        self.assertEqual(self.week_action("approve").status_code, 200)
        self.assertEqual(dm.TimesheetEntry.objects.get(user=self.dev).approval_status, "APPROVED")

    def test_entries_visibility_totals_edit_and_delete(self):
        e1 = dm.TimesheetEntry.objects.create(user=self.dev, workspace=self.ws, project=self.project, entry_date=MONDAY, hours=5, is_billable=True)
        dm.TimesheetEntry.objects.create(user=self.dev, workspace=self.ws, project=self.project, entry_date=MONDAY, hours=2, is_billable=False, description="Interne")
        dm.TimesheetEntry.objects.create(user=self.peer, workspace=self.ws, project=self.project, entry_date=MONDAY, hours=9)

        self.client.force_login(self.lead)  # N+1 de dev, pas de peer
        data = self.client.get("/api/v1/timesheet/entries/").json()
        self.assertEqual({r["user"]["id"] for r in data["results"]}, {self.dev.pk})
        self.assertEqual((data["totals"]["hours"], data["totals"]["billable_hours"], data["totals"]["non_billable_hours"]), (7.0, 5.0, 2.0))
        self.assertFalse(any(r["can_edit"] for r in data["results"]))
        self.assertEqual(self.client.get("/api/v1/timesheet/entries/", {"is_billable": "false"}).json()["count"], 1)
        self.assertEqual(self.client.get("/api/v1/timesheet/week/", {"user": self.peer.pk}).status_code, 404)

        self.client.force_login(self.lead)  # pas propriétaire → modification/suppression refusées
        self.assertEqual(self.client.get(f"/api/v1/forms/timesheet-entry/{e1.pk}/").status_code, 404)
        self.assertEqual(self.client.post(f"/api/v1/actions/timesheet-entry-delete/{e1.pk}/").status_code, 404)

        self.client.force_login(self.dev)
        fields = {f["name"]: f["value"] for f in self.client.get(f"/api/v1/forms/timesheet-entry/{e1.pk}/").json()["fields"]}
        fields.update({"hours": "6", "description": "Corrigé"})
        payload = {k: ("" if v is None else v) for k, v in fields.items() if k != "is_billable"}
        payload["is_billable"] = "on"
        self.assertEqual(self.client.post(f"/api/v1/forms/timesheet-entry/{e1.pk}/", payload).status_code, 200)
        e1.refresh_from_db()
        self.assertEqual((float(e1.hours), e1.description), (6.0, "Corrigé"))
        self.assertEqual(self.client.post(f"/api/v1/actions/timesheet-entry-delete/{e1.pk}/").status_code, 200)
        self.assertFalse(dm.TimesheetEntry.objects.filter(pk=e1.pk).exists())

        self.client.force_login(self.bob)  # autre workspace
        self.assertEqual(self.client.get("/api/v1/timesheet/entries/").json()["count"], 0)
