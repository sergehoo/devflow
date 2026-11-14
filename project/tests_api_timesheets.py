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


@override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
class TimesheetExportTests(TestCase):
    """Consultation des semaines validées et exports Excel (périmètre N+1, filtres, isolation)."""

    # Mêmes données que TimesheetApiTests, sans rejouer ses tests.
    setUpTestData = classmethod(TimesheetApiTests.setUpTestData.__func__)
    cell = TimesheetApiTests.cell
    week_action = TimesheetApiTests.week_action

    def approved_week(self):
        self.client.force_login(self.dev)
        self.cell(task_id=self.task.pk, date=MONDAY.isoformat(), hours="6")
        self.cell(project_id=self.project.pk, description="Réunion client", date=(MONDAY + timedelta(days=1)).isoformat(), hours="2")
        self.assertEqual(self.week_action("submit").status_code, 200)
        self.client.force_login(self.lead)
        self.assertEqual(self.week_action("approve").status_code, 200)
        dm.TimesheetEntry.objects.filter(user=self.dev, description="Réunion client").update(is_billable=False)
        dm.TimesheetEntry.objects.create(user=self.peer, workspace=self.ws, project=self.project, entry_date=MONDAY, hours=9, description="Hors périmètre")
        dm.TimesheetEntry.objects.create(user=self.bob, workspace=self.other, project=self.foreign_project, entry_date=MONDAY, hours=4, description="Secret")

    def workbook(self, res):
        from io import BytesIO

        from openpyxl import load_workbook

        self.assertEqual(res.status_code, 200, res.content[:300])
        self.assertEqual(res["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertIn("attachment;", res["Content-Disposition"])
        return load_workbook(BytesIO(res.content))

    @staticmethod
    def values(ws):
        return [tuple(row) for row in ws.iter_rows(values_only=True)]

    def test_validated_weeks_stay_listed_and_viewable(self):
        self.approved_week()
        weeks = self.client.get("/api/v1/timesheet/weeks/", {"status": "APPROVED"}).json()
        self.assertEqual([(w["user"]["id"], w["status"]) for w in weeks["results"]], [(self.dev.pk, "APPROVED")])
        self.assertEqual({c["id"] for c in weeks["collaborators"]}, {self.dev.pk})
        self.assertEqual(self.client.get("/api/v1/timesheet/weeks/", {"date_from": (MONDAY + timedelta(days=7)).isoformat()}).json()["count"], 0)
        self.assertEqual(self.client.get("/api/v1/timesheet/weeks/", {"date_to": (MONDAY + timedelta(days=6)).isoformat()}).json()["count"], 1)
        week = self.client.get("/api/v1/timesheet/week/", {"user": self.dev.pk, "date": MONDAY.isoformat()}).json()
        self.assertEqual((week["week_status"], week["week_total"], week["history"][0]["action"]), ("APPROVED", 8.0, "APPROVED"))

    def test_history_export_follows_scope_and_filters(self):
        self.approved_week()
        wb = self.workbook(self.client.get("/api/v1/timesheet/export/"))
        self.assertEqual(wb.sheetnames, ["Synthèse", "Feuilles de temps", "Saisies", "Informations"])
        detail = self.values(wb["Saisies"])
        self.assertEqual(detail[3], ("Date", "Semaine", "Collaborateur", "Projet", "Tâche", "Description", "Heures", "Facturable", "Statut"))
        rows = detail[4:]
        self.assertEqual({r[2] for r in rows}, {"Dan"})  # ni peer (hors hiérarchie) ni bob (autre workspace)
        self.assertEqual(sorted(r[6] for r in rows), [2.0, 6.0])
        self.assertEqual({r[8] for r in rows}, {"Validée"})
        sheets = self.values(wb["Feuilles de temps"])[4:]
        self.assertEqual(len(sheets), 1)
        self.assertEqual(sheets[0][:2], ("Dan", "S41 2026"))
        self.assertEqual((sheets[0][4], sheets[0][5], sheets[0][6], sheets[0][8]), (8.0, 6.0, 2.0, "Validée"))
        self.assertTrue(sheets[0][9].startswith("Validée par Léa le "))
        summary = self.values(wb["Synthèse"])
        self.assertEqual(summary[4][:4], ("Dan", 8.0, 6.0, 2.0))
        info = {r[0]: r[1] for r in self.values(wb["Informations"])}
        self.assertEqual((info["Origine"], info["Exporté par"], info["Filtres appliqués"]), ("Généré automatiquement depuis DevFlow", "Léa", "aucun"))
        self.assertNotIn("Secret", str(self.values(wb["Saisies"])) + str(summary))

        wb = self.workbook(self.client.get("/api/v1/timesheet/export/", {"is_billable": "false", "date_from": MONDAY.isoformat()}))
        rows = self.values(wb["Saisies"])[4:]
        self.assertEqual([(r[5], r[6]) for r in rows], [("Réunion client", 2.0)])
        info = {r[0]: r[1] for r in self.values(wb["Informations"])}
        self.assertIn("Facturable : non", info["Filtres appliqués"])
        self.assertIn("Période : 05/10/2026", info["Filtres appliqués"])
        self.assertEqual(self.client.get("/api/v1/timesheet/export/", {"user": "abc"}).status_code, 400)

    def test_empty_export_is_clean(self):
        self.client.force_login(self.peer)
        wb = self.workbook(self.client.get("/api/v1/timesheet/export/"))
        self.assertIn("Aucune saisie pour le périmètre et les filtres appliqués.", str(self.values(wb["Saisies"])))
        self.client.force_login(self.bob)
        wb = self.workbook(self.client.get("/api/v1/timesheet/export/", {"user": self.dev.pk}))
        self.assertNotIn("Dan", str(self.values(wb["Saisies"])))

    def test_week_export_for_the_manager_and_the_employee(self):
        self.approved_week()
        res = self.client.get("/api/v1/timesheet/week/export/", {"user": self.dev.pk, "date": (MONDAY + timedelta(days=2)).isoformat()})
        wb = self.workbook(res)
        self.assertIn('filename="Timesheet_dan_s41_2026.xlsx"', res["Content-Disposition"])
        self.assertEqual(wb.sheetnames, ["Semaine S41 2026", "Saisies", "Informations"])
        grid = self.values(wb["Semaine S41 2026"])
        self.assertEqual(grid[0][0], "Feuille de temps — Dan")
        self.assertIn("statut : Validée", grid[1][0])
        self.assertIn("Validée par Léa le ", grid[1][0])
        self.assertEqual(grid[3][:4], ("Projet", "Tâche / activité", "Type", "Lun 05/10"))
        body = {r[1]: r for r in grid[4:6]}
        self.assertEqual((body["API"][3], body["API"][10]), (6.0, 6.0))
        self.assertEqual((body["Réunion client"][2], body["Réunion client"][4]), ("Activité", 2.0))
        self.assertEqual((grid[6][0], grid[6][10]), ("Total jour", 8.0))
        self.assertIn("Validée par Léa", str(grid))

        self.client.force_login(self.dev)  # sa propre semaine, sans paramètre user
        self.assertEqual(self.workbook(self.client.get("/api/v1/timesheet/week/export/", {"date": MONDAY.isoformat()})).sheetnames[0], "Semaine S41 2026")

    def test_week_export_is_scoped(self):
        self.approved_week()
        self.client.force_login(self.lead)  # peer n'est pas dans sa hiérarchie
        self.assertEqual(self.client.get("/api/v1/timesheet/week/export/", {"user": self.peer.pk}).status_code, 404)
        self.client.force_login(self.peer)  # pas le N+1 de dev
        self.assertEqual(self.client.get("/api/v1/timesheet/week/export/", {"user": self.dev.pk}).status_code, 404)
        self.client.force_login(self.bob)  # autre workspace → 404
        self.assertEqual(self.client.get("/api/v1/timesheet/week/export/", {"user": self.dev.pk, "date": MONDAY.isoformat()}).status_code, 404)
        self.assertEqual(self.client.get("/api/v1/timesheet/week/export/", {"user": "x"}).status_code, 404)
        self.client.logout()
        self.assertIn(self.client.get("/api/v1/timesheet/week/export/").status_code, (401, 403))
        self.assertIn(self.client.get("/api/v1/timesheet/export/").status_code, (401, 403))
