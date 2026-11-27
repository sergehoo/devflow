"""
Synchronisation tâches ↔ timesheet ↔ Suivi Pôle Développement.

Il n'existe qu'une tâche (``dm.Task``) : le timesheet, /tasks, la fiche projet et le
Suivi la lisent directement. Ces tests vérifient les trois sens d'écriture :

* timesheet → tâche / projet / suivi : tâche créée depuis le timesheet, activité
  libre convertie, activité libre du projet d'accueil reprise par le suivi ;
* tâche → timesheet / suivi : statut, avancement, échéance et réaffectation faits
  dans /tasks (API, formulaire, actions rapides) visibles au timesheet et au suivi ;
* import du suivi → tâche / timesheet : statut et porteur importés visibles dans
  /tasks et au timesheet, annulation comprise ;

plus l'isolation entre workspaces et la diffusion temps réel « task.changed ».
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.urls import reverse
from django.utils import timezone

from project import models as dm
from project.services import realtime
from project.services import tracking_import as importer
from project.tests_tracking import TrackingFixture

TODAY = timezone.localdate()


class SyncFixture(TrackingFixture):
    def week(self, user, day=None):
        response = self.api(user).get("/api/v1/timesheet/week/", {"date": (day or TODAY).isoformat()})
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def week_row(self, user, task, day=None):
        return next((r for r in self.week(user, day)["rows"] if r["task"] and r["task"]["id"] == task.pk), None)

    def board_rows(self, user=None) -> dict:
        response = self.board(user)
        self.assertEqual(response.status_code, 200, response.content)
        return {row["title"]: row for row in response.json()["rows"]}

    def create_from_timesheet(self, user, **payload):
        return self.api(user).post("/api/v1/timesheet/tasks/", payload, format="json")

    def convert(self, user, **payload):
        return self.api(user).post("/api/v1/timesheet/activities/convert/", payload, format="json")

    def container(self):
        return dm.Project.objects.get(workspace=self.ws, category__code=importer.CONTAINER_CATEGORY)


# ---------------------------------------------------------------------------
# Timesheet → tâche / projet / suivi
# ---------------------------------------------------------------------------
class TimesheetToTaskTests(SyncFixture):
    def test_task_created_in_timesheet_is_the_project_task(self):
        due = TODAY + timedelta(days=5)
        response = self.create_from_timesheet(self.dev, project_id=self.project.pk, title="Recette  API",
                                              date=TODAY.isoformat(), hours="2", due_date=due.isoformat())
        self.assertEqual(response.status_code, 201, response.content)
        task = dm.Task.objects.get(pk=response.json()["task"]["id"])
        self.assertEqual((task.title, task.project, task.workspace, task.assignee, task.reporter),
                         ("Recette API", self.project, self.ws, self.dev, self.dev))
        self.assertEqual((task.status, task.due_date, task.spent_hours), ("IN_PROGRESS", due, Decimal("2")))
        self.assertIsNotNone(task.started_at)
        self.assertTrue(dm.TaskAssignment.objects.filter(task=task, user=self.dev, is_active=True).exists())
        self.assertEqual(dm.TimesheetEntry.objects.get(task=task).hours, Decimal("2"))
        # Pas de notification « tâche assignée » pour sa propre création.
        self.assertFalse(dm.Notification.objects.filter(recipient=self.dev, metadata__task_id=task.pk).exists())

        # /tasks (chef de projet) : la même tâche, assignée au collaborateur.
        listed = self.api(self.pm).get("/api/v1/tasks/", {"project": self.project.pk}).json()["results"]
        self.assertIn((task.pk, self.dev.pk), [(t["id"], t["assignee"]) for t in listed])
        # Timesheet : ligne « tâche » avec son état réel.
        row = self.week_row(self.dev, task)
        self.assertEqual((row["task"]["status"], row["task"]["due_date"], row["total"]), ("IN_PROGRESS", due.isoformat(), 2.0))
        self.assertTrue(row["task"]["can_update"])
        # Suivi : action à venir du projet et temps saisi repris dans les actions menées.
        portail = self.board_rows()["Portail"]
        self.assertIn(task.pk, [i["id"] for i in portail["next"]])
        self.assertTrue(any(i["text"].startswith("Recette API — Awa Diallo, 2 h") for i in portail["done"]))
        self.assertEqual(portail["logged_hours"], 2.0)

    def test_task_created_in_container_project_is_a_suivi_activity(self):
        self.imported()
        response = self.create_from_timesheet(self.dev, project_id=self.container().pk, title="Revue sécurité",
                                              date=TODAY.isoformat(), hours="1.5")
        self.assertEqual(response.status_code, 201, response.content)
        row = self.board_rows()["Revue sécurité"]
        self.assertEqual((row["kind"], row["status_key"], row["logged_hours"]), ("task", "en_cours", 1.5))
        self.assertEqual([o["name"] for o in row["owners"]], ["Awa Diallo"])

    def test_refused_hours_cancel_the_whole_creation(self):
        before = dm.Task.objects.count()
        response = self.create_from_timesheet(self.dev, project_id=self.project.pk, title="Trop long", hours="30")
        self.assertEqual(response.status_code, 400)
        # Semaine soumise : la saisie est refusée et la tâche n'est pas créée non plus.
        dm.TimesheetEntry.objects.create(user=self.dev, workspace=self.ws, project=self.project, entry_date=TODAY,
                                         hours=Decimal("1"), description="Réunion",
                                         approval_status=dm.TimesheetEntry.ApprovalStatus.SUBMITTED)
        response = self.create_from_timesheet(self.dev, project_id=self.project.pk, title="Semaine close", hours="2")
        self.assertEqual(response.status_code, 400)
        self.assertIn("soumise ou validée", response.json()["detail"])
        self.assertEqual(dm.Task.objects.count(), before)
        # Intitulé obligatoire, échéance cohérente.
        self.assertEqual(self.create_from_timesheet(self.dev, project_id=self.project.pk, title="  ").status_code, 400)
        self.assertEqual(self.create_from_timesheet(
            self.dev, project_id=self.project.pk, title="X", date=TODAY.isoformat(),
            due_date=(TODAY - timedelta(days=3)).isoformat()).status_code, 400)

    def test_free_activity_is_converted_into_a_task(self):
        last_week = TODAY - timedelta(days=7)
        approved = dm.TimesheetEntry.objects.create(
            user=self.dev, workspace=self.ws, project=self.project, entry_date=last_week, hours=Decimal("3"),
            description="Réunion client", approval_status=dm.TimesheetEntry.ApprovalStatus.APPROVED)
        draft = dm.TimesheetEntry.objects.create(
            user=self.dev, workspace=self.ws, project=self.project, entry_date=TODAY, hours=Decimal("1.5"),
            description="Réunion client")
        response = self.convert(self.dev, project_id=self.project.pk, description="réunion client")
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual((body["created"], body["linked_entries"]), (True, 1))
        task = dm.Task.objects.get(pk=body["task"]["id"])
        self.assertEqual((task.project, task.assignee, task.status, task.spent_hours),
                         (self.project, self.dev, "IN_PROGRESS", Decimal("1.5")))
        draft.refresh_from_db()
        approved.refresh_from_db()
        self.assertEqual((draft.task, approved.task), (task, None))  # la saisie validée reste telle quelle
        week = self.week(self.dev)
        self.assertNotIn("activity", [r["kind"] for r in week["rows"]])
        self.assertEqual(self.week_row(self.dev, task)["total"], 1.5)
        self.assertIn(task.pk, [t["id"] for t in self.api(self.pm).get("/api/v1/tasks/").json()["results"]])

        # Nouvelle saisie libre du même libellé : rattachée à la même tâche, sans doublon.
        dm.TimesheetEntry.objects.create(user=self.dev, workspace=self.ws, project=self.project,
                                         entry_date=TODAY, hours=Decimal("1"), description="Réunion client")
        response = self.convert(self.dev, project_id=self.project.pk, description="Réunion client")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual((response.json()["created"], response.json()["task"]["id"]), (False, task.pk))
        task.refresh_from_db()
        self.assertEqual(task.spent_hours, Decimal("2.5"))
        # Ne reste que la saisie validée : rien de modifiable à convertir.
        response = self.convert(self.dev, project_id=self.project.pk, description="Réunion client")
        self.assertEqual(response.status_code, 400)
        self.assertIn("soumises ou validées", response.json()["detail"])

    def test_converting_only_locked_entries_is_refused(self):
        dm.TimesheetEntry.objects.create(
            user=self.dev, workspace=self.ws, project=self.project, entry_date=TODAY, hours=Decimal("2"),
            description="Support", approval_status=dm.TimesheetEntry.ApprovalStatus.SUBMITTED)
        response = self.convert(self.dev, project_id=self.project.pk, description="Support")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(dm.Task.objects.filter(title="Support").exists())

    def test_free_activity_on_container_project_reaches_its_suivi_activity(self):
        """Avant : une activité libre sur le projet d'accueil disparaissait du suivi."""
        self.imported()
        dm.TimesheetEntry.objects.create(user=self.dev, workspace=self.ws, project=self.container(),
                                         entry_date=TODAY, hours=Decimal("2"),
                                         description="Maintenance serveurs - sauvegardes")
        row = self.board_rows()["Maintenance serveurs · Sauvegardes"]
        self.assertEqual(row["logged_hours"], 2.0)
        self.assertTrue(any(i["source"] == "timesheet" and "Awa Diallo, 2 h" in i["text"] for i in row["done"]))


# ---------------------------------------------------------------------------
# Tâche (/tasks, fiche projet) → timesheet / suivi
# ---------------------------------------------------------------------------
class TaskToTimesheetTests(SyncFixture):
    def setUp(self):
        super().setUp()
        self.imported()
        response = self.api(self.pm).post("/api/v1/tasks/", {
            "project": self.container().pk, "title": "Refonte caisse", "assignee": self.dev.pk, "status": "TODO",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.task = dm.Task.objects.get(pk=response.json()["id"])

    def test_updates_made_in_tasks_show_in_timesheet_and_suivi(self):
        self.assertTrue(dm.TaskAssignment.objects.filter(task=self.task, user=self.dev, is_active=True).exists())
        self.assertEqual(self.week_row(self.dev, self.task)["task"]["status"], "TODO")
        self.assertEqual(self.board_rows()["Refonte caisse"]["status_key"], "en_cours")

        due = TODAY + timedelta(days=10)
        self.assertEqual(self.api(self.pm).patch(f"/api/v1/tasks/{self.task.pk}/", {
            "title": "Refonte caisse v2", "due_date": due.isoformat()}, format="json").status_code, 200)
        response = self.api(self.dev).post(f"/api/v1/tasks/{self.task.pk}/quick-update/",
                                           {"progress_percent": 60, "status": "IN_PROGRESS"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        row = self.week_row(self.dev, self.task)
        self.assertEqual((row["label"], row["task"]["status"], row["task"]["progress_percent"], row["task"]["due_date"]),
                         ("Refonte caisse v2", "IN_PROGRESS", 60, due.isoformat()))
        board = self.board_rows()["Refonte caisse v2"]
        self.assertEqual((board["progress"], board["end"]), (60, due.isoformat()))

        # Clôture depuis le board kanban : même règle que partout (100 %, date de clôture)…
        self.assertEqual(self.api(self.dev).post(f"/api/v1/tasks/{self.task.pk}/move-kanban/",
                                                 {"status": "DONE"}, format="json").status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual((self.task.progress_percent, self.task.completed_at is not None), (100, True))
        self.assertEqual(self.board_rows()["Refonte caisse v2"]["status_key"], "realise")
        self.assertEqual(self.week_row(self.dev, self.task)["task"]["status"], "DONE")
        # … et réouverture : la date de clôture disparaît (plus « terminée » dans le suivi).
        self.api(self.dev).post(f"/api/v1/tasks/{self.task.pk}/move-kanban/", {"status": "IN_PROGRESS"}, format="json")
        self.task.refresh_from_db()
        self.assertIsNone(self.task.completed_at)
        self.assertEqual(self.board_rows()["Refonte caisse v2"]["status_key"], "en_cours")

    def test_api_reassignment_moves_the_task_between_timesheets_and_owners(self):
        response = self.api(self.pm).patch(f"/api/v1/tasks/{self.task.pk}/", {"assignee": self.peer.pk}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(dm.TaskAssignment.objects.filter(task=self.task, user=self.dev, is_active=True).exists())
        self.assertTrue(dm.TaskAssignment.objects.filter(task=self.task, user=self.peer, is_active=True).exists())
        self.assertIsNone(self.week_row(self.dev, self.task))
        self.assertIsNotNone(self.week_row(self.peer, self.task))
        self.assertEqual([o["user_id"] for o in self.board_rows()["Refonte caisse"]["owners"]], [self.peer.pk])
        # Le périmètre « mes tâches » du suivi suit aussi : l'ancien assigné ne la voit plus.
        self.assertNotIn("Refonte caisse", self.titles(self.dev))

    def test_form_reassignment_keeps_co_owners_and_drops_previous_assignee(self):
        dm.TaskAssignment.objects.create(task=self.task, user=self.outsider, assigned_by=self.pm, allocation_percent=50)
        self.client.force_login(self.pm)
        response = self.client.post(reverse("task_update", args=[self.task.pk]), {
            "project": self.task.project_id, "title": self.task.title, "status": "TODO", "priority": "MEDIUM",
            "risk_score": 0, "progress_percent": 0, "spent_hours": "0", "assignee": self.peer.pk,
        })
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["form"].errors)
        active = set(dm.TaskAssignment.objects.filter(task=self.task, is_active=True).values_list("user_id", flat=True))
        self.assertEqual(active, {self.peer.pk, self.outsider.pk})
        self.assertIsNone(self.week_row(self.dev, self.task))
        owners = {o["user_id"] for o in self.board_rows()["Refonte caisse"]["owners"]}
        self.assertEqual(owners, {self.peer.pk, self.outsider.pk})

    def test_form_status_change_follows_the_common_rule(self):
        self.client.force_login(self.pm)
        data = {"project": self.task.project_id, "title": self.task.title, "priority": "MEDIUM", "risk_score": 0,
                "progress_percent": 30, "spent_hours": "0", "assignee": self.dev.pk}
        self.assertEqual(self.client.post(reverse("task_update", args=[self.task.pk]),
                                          {**data, "status": "DONE"}).status_code, 302)
        self.task.refresh_from_db()
        self.assertEqual((self.task.progress_percent, self.task.completed_at is not None), (100, True))
        self.assertEqual(self.week_row(self.dev, self.task)["task"]["status"], "DONE")
        self.assertEqual(self.board_rows()["Refonte caisse"]["status_key"], "realise")
        # Réouverture par le formulaire (date de clôture encore affichée) : elle est retirée.
        completed = timezone.localtime(self.task.completed_at).strftime("%Y-%m-%dT%H:%M")
        self.client.post(reverse("task_update", args=[self.task.pk]),
                         {**data, "status": "IN_PROGRESS", "progress_percent": 100, "completed_at": completed})
        self.task.refresh_from_db()
        self.assertIsNone(self.task.completed_at)
        self.assertEqual(self.board_rows()["Refonte caisse"]["status_key"], "en_cours")


# ---------------------------------------------------------------------------
# Import du suivi → tâche / timesheet
# ---------------------------------------------------------------------------
class ImportToTaskTests(SyncFixture):
    def reimport_updating(self, title):
        upload = self.upload()
        self.assertEqual(upload.status_code, 201, upload.content)
        detail = upload.json()
        row = next(r for r in detail["analysis"]["rows"] if r["title"] == title)
        self.assertIsNotNone(row["match"])
        applied = self.apply(detail["id"], {"rows": {row["id"]: {"action": "update", "target_id": row["match"]["id"]}}})
        self.assertEqual(applied.status_code, 200, applied.content)
        return detail["id"]

    def test_import_update_reaches_tasks_and_timesheet_and_rolls_back(self):
        self.imported()
        task = dm.Task.objects.get(title="Support utilisateurs")
        # État divergent avant le second import : sans assigné, terminée.
        dm.TaskAssignment.objects.filter(task=task).delete()
        dm.Task.objects.filter(pk=task.pk).update(assignee=None, status="DONE", progress_percent=100,
                                                  completed_at=timezone.now())
        import_id = self.reimport_updating("Support utilisateurs")
        task.refresh_from_db()
        # « en cours », 50 %, porteur Serge OGAH (pm) devenu l'assigné.
        self.assertEqual((task.status, task.progress_percent, task.assignee), ("IN_PROGRESS", 50, self.pm))
        self.assertIsNone(task.completed_at)
        self.assertEqual(self.api(self.pm).get(f"/api/v1/tasks/{task.pk}/").json()["assignee"], self.pm.pk)
        row = self.week_row(self.pm, task)
        self.assertEqual((row["task"]["status"], row["task"]["progress_percent"], row["task"]["can_update"]),
                         ("IN_PROGRESS", 50, True))
        self.assertEqual(self.board_rows()["Support utilisateurs"]["status_key"], "en_cours")

        rollback = self.api(self.pm).post(f"/api/v1/tracking/imports/{import_id}/rollback/", {}, format="json")
        self.assertEqual(rollback.status_code, 200, rollback.content)
        task.refresh_from_db()
        self.assertEqual((task.status, task.assignee_id), ("DONE", None))
        self.assertIsNotNone(task.completed_at)


# ---------------------------------------------------------------------------
# Isolation et temps réel
# ---------------------------------------------------------------------------
class TaskSyncIsolationTests(SyncFixture):
    def test_timesheet_cannot_write_tasks_in_another_workspace(self):
        before = dm.Task.objects.count()
        response = self.create_from_timesheet(self.dev, project_id=self.foreign_project.pk, title="Intrusion")
        self.assertEqual(response.status_code, 404)
        response = self.api(self.dev).post(f"/api/v1/timesheet/tasks/?workspace={self.other.pk}",
                                           {"project_id": self.foreign_project.pk, "title": "Intrusion"}, format="json")
        self.assertEqual(response.status_code, 404)
        dm.TimesheetEntry.objects.create(user=self.bob, workspace=self.other, project=self.foreign_project,
                                         entry_date=TODAY, hours=Decimal("1"), description="Secret")
        self.assertEqual(self.convert(self.dev, project_id=self.foreign_project.pk, description="Secret").status_code, 404)
        self.assertEqual(self.convert(self.bob, project_id=self.project.pk, description="Secret").status_code, 404)
        # Un rôle client n'a pas accès aux tâches internes.
        self.assertEqual(self.create_from_timesheet(self.customer, project_id=self.project.pk, title="X").status_code, 403)
        self.assertEqual(dm.Task.objects.count(), before)
        # La tâche créée par dev reste invisible pour l'autre tenant.
        task_id = self.create_from_timesheet(self.dev, project_id=self.project.pk, title="Interne").json()["task"]["id"]
        self.assertEqual(self.api(self.bob).get(f"/api/v1/tasks/{task_id}/").status_code, 404)
        self.assertNotIn("Interne", self.titles(self.bob))

    def test_one_realtime_event_per_person_and_transaction(self):
        for bucket in realtime._pending_state().values():
            bucket.clear()
        with mock.patch("project.services.realtime.push_to_users") as push, \
                self.captureOnCommitCallbacks(execute=True):
            self.create_from_timesheet(self.dev, project_id=self.project2.pk, title="Temps réel", hours="1")
        self.assertEqual(push.call_count, 1)
        users, event, data = push.call_args.args
        self.assertEqual((event, data), ("task.changed", {}))
        self.assertIn(self.dev.pk, users)
        self.assertIn(self.outsider.pk, users)  # chef de produit du projet 2
        self.assertNotIn(self.bob.pk, users)
