"""
Suivi Pôle Développement — import du classeur Excel, vue consolidée, exports,
synthèse, notifications et RBAC.

Le classeur de test est synthétique (construit avec openpyxl) : même structure
que le fichier historique, aucune donnée réelle.
"""

from __future__ import annotations

import io
import shutil
import tempfile
from datetime import date, datetime
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import SimpleTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from openpyxl import Workbook, load_workbook

from project import models as dm
from project.services import tracking_board as board
from project.services import tracking_import as importer
from project.services import tracking_notifications as notifications
from project.tests_api_raw_writes import RawApiFixture

MEDIA_ROOT = tempfile.mkdtemp(prefix="devflow-tracking-")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
User = get_user_model()

PROJECT_HEADERS = [
    "ENTREPRISE", "PROJET", "PORTEUR DU PROJET", "INTERLOCUTEUR", "ACTIONS MENEES", "ACTIONS A VENIR",
    "ALERTE/DECISION", "Date de début", "Date de fin prévue", "État d’avancement (%)", "STATUT",
]
TASK_HEADERS = ["ENTREPRISE", "TACHE / ACTIVITE", "PORTEUR", *PROJECT_HEADERS[3:]]
PROJECTS_TITLE = "SUIVI DES PROJETS - POLE DEVELOPPEMENT"
TASKS_TITLE = "SUIVI DES TACHES - POLE DEVELOPPEMENT"

PROJECT_ROWS = [
    ["KAYDAN / DATARIUM", "AFFLUX", "Serge OGAH", "M. Koné\nMme Traoré",
     "- Cadrage réalisé\n- Maquettes validées", "- Acheter le capteur MileSight\n- Installer le pilote",
     "En attente de l'achat du capteur\nEn attente de la décision du port",
     datetime(2026, 1, 5), "30/06/2099", 1, "En cours"],
    ["KAYDAN", "Portail", "SORO Ibrahima / Serge OGAH", "", "— Recette terminée", "", "",
     46000, "15/03/2026\n20/04/2026", 0.4, "RÉALISÉ"],
    ["", "Projet Mystère", "Awa KONE", "", "", "Préparer le dossier", "Risque de retard critique",
     "date inconnue", None, "abc", "À lancer"],
    ["NOTE", None, None, None, None, None, None, None, None, None, None],
]
TASK_ROWS = [
    ["DATARIUM", "Maintenance serveurs\nSauvegardes", "Awa DIALLO", "DSI", "- Patch appliqué",
     "- Renouveler le certificat", "", "05/01/25", "10/01/2025", 30, "suspendu"],
    ["KAYDAN", "Veille techno", "", "", "", "", "", None, None, 100, "Annulé"],
    ["", "Support utilisateurs", "Serge OGAH", "", "", "", "", None, None, "50 %", "en cours"],
]


def tearDownModule():
    shutil.rmtree(MEDIA_ROOT, ignore_errors=True)


def workbook_bytes(projects=None, tasks=None) -> bytes:
    """Classeur au format du suivi : bloc projets (en-tête ligne 4) puis bloc tâches."""
    projects = PROJECT_ROWS if projects is None else projects
    tasks = TASK_ROWS if tasks is None else tasks
    wb = Workbook()
    ws = wb.active
    ws.title = "PROJET"
    ws["A2"] = PROJECTS_TITLE
    for col, header in enumerate(PROJECT_HEADERS, start=1):
        ws.cell(4, col, header)
    line = 5
    for values in projects:
        for col, value in enumerate(values, start=1):
            cell = ws.cell(line, col, value)
            if col == 10 and isinstance(value, float):
                cell.number_format = "0%"
        line += 1
    line += 1
    ws.cell(line, 1, TASKS_TITLE)
    line += 2
    for col, header in enumerate(TASK_HEADERS, start=1):
        ws.cell(line, col, header)
    for values in tasks:
        line += 1
        for col, value in enumerate(values, start=1):
            ws.cell(line, col, value)
    statuses = wb.create_sheet("Statut")
    for index, label in enumerate(("En cours", "suspendu", "réalisé", "Annulé"), start=1):
        statuses.cell(index, 1, label)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def parsed(data=None) -> dict:
    return importer.parse_workbook(io.BytesIO(data if data is not None else workbook_bytes()))


# ---------------------------------------------------------------------------
# Parseur (sans base de données)
# ---------------------------------------------------------------------------
class TrackingParserTests(SimpleTestCase):
    def rows(self):
        return {row["id"]: row for row in parsed()["rows"]}

    def test_two_sections_detected(self):
        result = parsed()
        self.assertEqual([s["kind"] for s in result["sections"]], [importer.PROJECTS, importer.TASKS])
        self.assertEqual([s["header_row"] for s in result["sections"]], [4, 12])
        self.assertEqual([s["title"] for s in result["sections"]], [PROJECTS_TITLE, TASKS_TITLE])
        # La ligne « NOTE » (entreprise seule) n'est ni un projet ni une tâche.
        self.assertEqual(sorted(self.rows()), ["P5", "P6", "P7", "T13", "T14", "T15"])

    def test_multiline_cells_become_items(self):
        rows = self.rows()
        afflux = rows["P5"]
        self.assertEqual(afflux["companies"], ["KAYDAN", "DATARIUM"])
        self.assertEqual(afflux["contacts"], ["M. Koné", "Mme Traoré"])
        self.assertEqual([i["text"] for i in afflux["done"]], ["Cadrage réalisé", "Maquettes validées"])
        self.assertEqual([i["text"] for i in afflux["next"]],
                         ["Acheter le capteur MileSight", "Installer le pilote"])
        self.assertEqual([i["text"] for i in afflux["alerts"]],
                         ["En attente de l'achat du capteur", "En attente de la décision du port"])
        self.assertEqual(rows["P6"]["owners"], ["SORO Ibrahima", "Serge OGAH"])
        self.assertEqual(rows["T13"]["title"], "Maintenance serveurs · Sauvegardes")
        self.assertTrue(rows["T13"]["title_multiline"])
        # Le texte d'origine est conservé tel quel.
        self.assertEqual(afflux["raw"]["done"], "- Cadrage réalisé\n- Maquettes validées")
        self.assertEqual(rows["T13"]["raw"]["title"], "Maintenance serveurs\nSauvegardes")

    def test_dates_text_excel_serial_and_datetime(self):
        rows = self.rows()
        self.assertEqual((rows["P5"]["start"], rows["P5"]["end"]), ("2026-01-05", "2099-06-30"))
        self.assertEqual(rows["P6"]["start"], "2025-12-09")  # numéro de série Excel 46000
        self.assertEqual((rows["T13"]["start"], rows["T13"]["end"]), ("2025-01-05", "2025-01-10"))
        # Deux dates dans la cellule : aucune n'est choisie d'office.
        self.assertIsNone(rows["P6"]["end"])
        self.assertEqual(rows["P6"]["end_all"], ["2026-03-15", "2026-04-20"])
        # Date illisible : signalée, jamais devinée.
        self.assertIsNone(rows["P7"]["start"])
        self.assertIn("invalid_date", [w["code"] for w in rows["P7"]["warnings"]])
        self.assertEqual(importer.parse_dates("1/2/2026 puis 03.04.26")["dates"], ["2026-02-01", "2026-04-03"])
        self.assertEqual(importer.parse_dates(date(2026, 5, 6))["dates"], ["2026-05-06"])
        self.assertEqual(importer.parse_dates(None)["dates"], [])

    def test_progress_is_never_silently_corrected(self):
        rows = self.rows()
        self.assertEqual(rows["P5"]["progress"], 1)  # 1 reste 1 : 1 % ou 100 % ?
        self.assertEqual(rows["P6"]["progress"], 40)  # 0,4 au format pourcentage
        self.assertEqual(rows["T15"]["progress"], 50)  # « 50 % »
        self.assertIsNone(rows["P7"]["progress"])
        self.assertIn("progress", [w["code"] for w in rows["P7"]["warnings"]])
        one = importer.parse_progress(1)
        self.assertEqual(one["value"], 1)
        self.assertEqual(sorted(o["value"] for o in one["ambiguity"]["options"]), [1, 100])
        self.assertEqual(one["ambiguity"]["default"], 1)
        fraction = importer.parse_progress(0.4)  # sans format pourcentage : rien n'est décidé
        self.assertIsNone(fraction["value"])
        self.assertIsNone(fraction["ambiguity"]["default"])
        self.assertEqual(importer.parse_progress(0.4, "0%")["value"], 40)
        self.assertIsNone(importer.parse_progress(75)["ambiguity"])
        self.assertTrue(importer.parse_progress(140)["warning"])

    def test_statuses_ignore_case_and_accents(self):
        rows = self.rows()
        self.assertEqual([rows[i]["status_key"] for i in ("P5", "P6", "T13", "T14", "T15")],
                         ["en_cours", "realise", "suspendu", "annule", "en_cours"])
        self.assertIsNone(rows["P7"]["status_key"])
        self.assertEqual(rows["P7"]["status_raw"], "À lancer")
        self.assertIn("unknown_status", [w["code"] for w in rows["P7"]["warnings"]])
        self.assertIn("status_progress", [w["code"] for w in rows["P6"]["warnings"]])

    def test_alerts_are_classified_without_ai(self):
        cases = {
            "En attente de la décision du port": "DECISION",
            "En attente de l'achat du capteur": "DEPENDENCY",
            "Projet bloqué par le prestataire": "BLOCKER",
            "Risque de retard critique": "RISK",
            "Point à surveiller": "ALERT",
        }
        for text, kind in cases.items():
            self.assertEqual(importer.classify_alert(text)["kind"], kind, text)
        self.assertEqual(importer.classify_alert("Risque de retard critique")["severity"], "CRITICAL")
        self.assertEqual(importer.classify_alert("Point à surveiller")["severity"], "LOW")

    def test_ambiguities_are_listed(self):
        ids = [a["id"] for row in parsed()["rows"] for a in row["ambiguities"]]
        self.assertEqual(sorted(ids), ["P5:progress", "P6:end"])

    def test_unreadable_or_foreign_workbook_is_refused(self):
        with self.assertRaises(importer.TrackingImportError):
            parsed(b"pas un classeur")
        wb = Workbook()
        wb.active["A1"] = "Autre document"
        out = io.BytesIO()
        wb.save(out)
        with self.assertRaises(importer.TrackingImportError):
            parsed(out.getvalue())


# ---------------------------------------------------------------------------
# Base commune
# ---------------------------------------------------------------------------
@override_settings(AI_BACKEND="none", MEDIA_ROOT=MEDIA_ROOT)
class TrackingFixture(RawApiFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for user, first, last in ((cls.pm, "Serge", "OGAH"), (cls.dev, "Awa", "Diallo")):
            user.first_name, user.last_name = first, last
            user.save(update_fields=["first_name", "last_name"])
        cls.customer = User.objects.create_user("customer", "customer@x.test", "pw")
        dm.UserProfile.objects.create(user=cls.customer, workspace=cls.ws)
        dm.TeamMembership.objects.create(user=cls.customer, workspace=cls.ws, team=None)
        dm.WorkspaceRoleAssignment.objects.create(user=cls.customer, workspace=cls.ws, role="CLIENT")

    def setUp(self):
        super().setUp()
        cache.clear()

    def upload(self, user=None, data=None, workspace=None, name="suivi.xlsx"):
        payload = {
            "workspace": str((workspace or self.ws).pk),
            "file": SimpleUploadedFile(name, workbook_bytes() if data is None else data, content_type=XLSX),
        }
        return self.api(user or self.pm).post("/api/v1/tracking/imports/", payload, format="multipart")

    def apply(self, import_id, decisions=None, user=None):
        return self.api(user or self.pm).post(
            f"/api/v1/tracking/imports/{import_id}/apply/", {"decisions": decisions or {}}, format="json")

    def imported(self, decisions=None, data=None) -> dict:
        created = self.upload(data=data)
        self.assertEqual(created.status_code, 201, created.content)
        applied = self.apply(created.json()["id"], decisions)
        self.assertEqual(applied.status_code, 200, applied.content)
        return applied.json()

    def board(self, user=None, **params):
        return self.api(user or self.pm).get("/api/v1/tracking/board/", params)

    def titles(self, user=None, **params) -> set:
        response = self.board(user, **params)
        self.assertEqual(response.status_code, 200, response.content)
        return {row["title"] for row in response.json()["rows"]}

    def export(self, user=None, **params):
        return self.api(user or self.pm).get("/api/v1/tracking/export/", params)

    def sheet(self, user=None, **params):
        response = self.export(user, **params)
        self.assertEqual(response.status_code, 200, response.content)
        return load_workbook(io.BytesIO(response.content))

    def counts(self) -> dict:
        return {
            "projects": dm.Project.objects.count(), "tasks": dm.Task.objects.count(),
            "risks": dm.Risk.objects.count(), "decisions": dm.MeetingDecision.objects.count(),
            "logs": dm.ActivityLog.objects.filter(metadata__source=importer.SOURCE).count(),
            "labels": dm.Label.objects.count(), "project_labels": dm.ProjectLabel.objects.count(),
            "task_labels": dm.TaskLabel.objects.count(), "stakeholders": dm.ProjectStakeholder.objects.count(),
            "members": dm.ProjectMember.objects.count(), "assignments": dm.TaskAssignment.objects.count(),
            "users": User.objects.count(),
        }


# ---------------------------------------------------------------------------
# Assistant d'import
# ---------------------------------------------------------------------------
class TrackingImportTests(TrackingFixture):
    def test_upload_analyses_without_writing(self):
        before = self.counts()
        response = self.upload()
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["state"], "analyzed")
        analysis = body["analysis"]
        self.assertEqual([s["kind"] for s in analysis["sections"]], ["PROJECTS", "TASKS"])
        stats = analysis["stats"]
        self.assertEqual(
            {k: stats[k] for k in ("projects", "tasks", "actions_done", "actions_next", "alerts", "companies",
                                   "people", "unresolved_people", "ambiguities")},
            {"projects": 3, "tasks": 3, "actions_done": 4, "actions_next": 4, "alerts": 3, "companies": 2,
             "people": 7, "unresolved_people": 2, "ambiguities": 2})
        self.assertEqual(analysis["unresolved_members"], ["SORO Ibrahima", "Awa KONE"])
        rows = {row["id"]: row for row in analysis["rows"]}
        self.assertEqual(rows["P5"]["default"], {"action": "create", "target_id": None})
        self.assertEqual(rows["P6"]["default"], {"action": "link", "target_id": self.project.pk})
        self.assertEqual(rows["T13"]["default"]["action"], "create")
        people = {p["name"]: p for p in analysis["people"]}
        self.assertEqual(people["Serge OGAH"]["default"], {"user_id": self.pm.pk})
        self.assertEqual(people["Awa DIALLO"]["default"], {"user_id": self.dev.pk})
        self.assertIsNone(people["SORO Ibrahima"]["default"]["user_id"])
        self.assertTrue(people["SORO Ibrahima"]["unresolved"])
        self.assertFalse(people["DSI"]["unresolved"])  # interlocuteur : pas de compte attendu
        statuses = {s["raw"]: s for s in analysis["statuses"]}
        self.assertEqual(statuses["RÉALISÉ"]["default"], {"project": "DONE", "task": "DONE"})
        self.assertEqual(statuses["suspendu"]["default"], {"project": "ON_HOLD", "task": "BLOCKED"})
        self.assertEqual(statuses["À lancer"]["default"], {"project": None, "task": None})
        self.assertEqual(analysis["container"]["default"]["mode"], "create")
        self.assertIn(self.pm.pk, [u["id"] for u in body["options"]["users"]])
        self.assertNotIn(self.bob.pk, [u["id"] for u in body["options"]["users"]])
        # L'analyse n'écrit aucune donnée métier.
        self.assertEqual(self.counts(), before)

    def test_upload_rejections_leave_nothing_behind(self):
        self.assertEqual(self.upload(name="suivi.csv").status_code, 400)
        garbage = self.upload(data=b"pas un classeur")
        self.assertEqual(garbage.status_code, 400)
        self.assertIn("file", garbage.json())
        missing = self.api(self.pm).post("/api/v1/tracking/imports/", {"workspace": str(self.ws.pk)},
                                         format="multipart")
        self.assertEqual(missing.status_code, 400)
        bad_workspace = self.api(self.pm).post("/api/v1/tracking/imports/", {"workspace": "abc"}, format="multipart")
        self.assertEqual(bad_workspace.status_code, 400)
        self.assertEqual(dm.ProjectDocumentImport.objects.count(), 0)

    def test_apply_maps_the_workbook_onto_existing_models(self):
        before_users = User.objects.count()
        detail = self.imported()
        self.assertEqual(detail["state"], "applied")
        self.assertEqual(detail["report"]["unresolved_members"], ["SORO Ibrahima", "Awa KONE"])
        self.assertEqual(len(detail["report"]["ambiguities_kept"]), 2)

        # Entreprises → étiquettes « entreprise »
        labels = {l.name: l for l in dm.Label.objects.filter(workspace=self.ws, kind=dm.Label.Kind.COMPANY)}
        self.assertEqual(sorted(labels), ["DATARIUM", "KAYDAN"])

        # Projet créé
        afflux = dm.Project.objects.get(workspace=self.ws, name="AFFLUX")
        self.assertEqual(afflux.owner, self.pm)
        self.assertEqual(afflux.status, "IN_PROGRESS")
        self.assertEqual(afflux.progress_percent, 1)  # ambiguïté conservée : 1 n'est pas devenu 100
        self.assertEqual((afflux.start_date, afflux.target_date), (date(2026, 1, 5), date(2099, 6, 30)))
        self.assertEqual(sorted(afflux.labels.values_list("label__name", flat=True)),
                         ["DATARIUM", "KAYDAN"])
        self.assertTrue(dm.ProjectMember.objects.filter(project=afflux, user=self.pm, role="Porteur").exists())
        self.assertEqual(
            sorted(dm.ProjectStakeholder.objects.filter(project=afflux, role="INTERLOCUTEUR")
                   .values_list("name", flat=True)), ["M. Koné", "Mme Traoré"])
        logs = dm.ActivityLog.objects.filter(project=afflux, metadata__source=importer.SOURCE)
        self.assertEqual(sorted(logs.values_list("description", flat=True)),
                         ["Cadrage réalisé", "Maquettes validées"])
        self.assertEqual(logs.first().metadata["row"], 5)
        tasks = dm.Task.objects.filter(project=afflux)
        self.assertEqual(sorted(tasks.values_list("title", flat=True)),
                         ["Acheter le capteur MileSight", "Installer le pilote"])
        self.assertEqual(set(tasks.values_list("assignee_id", flat=True)), {self.pm.pk})
        risk = dm.Risk.objects.get(project=afflux)
        self.assertEqual((risk.title, risk.category, risk.owner), ("En attente de l'achat du capteur",
                                                                    "DEPENDENCY", self.pm))
        decision = dm.MeetingDecision.objects.get(projects=afflux)
        self.assertEqual((decision.title, decision.status), ("En attente de la décision du port", "PENDING"))
        self.assertIsNone(decision.meeting_id)

        # Projet existant : rattaché, jamais écrasé
        self.project.refresh_from_db()
        self.assertEqual(dm.Project.objects.filter(workspace=self.ws, name__iexact="portail").count(), 1)
        self.assertIsNone(self.project.target_date)
        self.assertNotEqual(self.project.status, "DONE")
        self.assertEqual(list(self.project.labels.values_list("label__name", flat=True)), ["KAYDAN"])
        self.assertTrue(dm.ProjectStakeholder.objects.filter(
            project=self.project, role="PORTEUR", name="SORO Ibrahima", user__isnull=True).exists())
        self.assertTrue(dm.ProjectMember.objects.filter(project=self.project, user=self.pm).exists())

        # Statut inconnu, avancement illisible : valeurs neutres, rien d'inventé
        mystery = dm.Project.objects.get(workspace=self.ws, name="Projet Mystère")
        self.assertEqual((mystery.status, mystery.progress_percent, mystery.owner), ("PLANNED", 0, None))
        self.assertIsNone(mystery.start_date)
        self.assertTrue(dm.ProjectStakeholder.objects.filter(project=mystery, role="PORTEUR",
                                                             name="Awa KONE").exists())
        self.assertEqual(dm.Risk.objects.get(project=mystery).severity, "CRITICAL")

        # Bloc tâches → projet d'accueil
        container = dm.Project.objects.get(workspace=self.ws, name=importer.DEFAULT_CONTAINER)
        self.assertEqual(container.category.code, importer.CONTAINER_CATEGORY)
        maintenance = dm.Task.objects.get(project=container, title="Maintenance serveurs · Sauvegardes")
        self.assertEqual((maintenance.status, maintenance.progress_percent, maintenance.assignee),
                         ("BLOCKED", 30, self.dev))
        self.assertEqual((maintenance.start_date, maintenance.due_date), (date(2025, 1, 5), date(2025, 1, 10)))
        self.assertEqual(maintenance.description, "Maintenance serveurs\nSauvegardes")
        self.assertEqual(list(maintenance.labels.values_list("label__name", flat=True)), ["DATARIUM"])
        self.assertTrue(dm.ProjectStakeholder.objects.filter(task=maintenance, name="DSI").exists())
        sub = dm.Task.objects.get(parent=maintenance)
        self.assertEqual((sub.title, sub.assignee), ("Renouveler le certificat", self.dev))
        watch = dm.Task.objects.get(project=container, title="Veille techno")
        self.assertEqual((watch.status, watch.progress_percent), ("CANCELLED", 100))
        support = dm.Task.objects.get(project=container, title="Support utilisateurs")
        self.assertEqual((support.status, support.progress_percent, support.assignee),
                         ("IN_PROGRESS", 50, self.pm))

        # Aucun compte créé ; un seul récapitulatif pour le porteur concerné
        self.assertEqual(User.objects.count(), before_users)
        summary = dm.Notification.objects.filter(metadata__kind="import_assignment")
        self.assertEqual(list(summary.values_list("recipient_id", flat=True)), [self.dev.pk])
        self.assertFalse(dm.Notification.objects.filter(metadata__source=notifications.SOURCE).exists())

    def test_provenance_is_kept_for_every_cell(self):
        detail = self.imported()
        obj = dm.ProjectDocumentImport.objects.get(pk=detail["id"])
        self.assertEqual(obj.uploaded_by, self.pm)
        self.assertEqual(detail["applied_by"]["id"], self.pm.pk)
        self.assertTrue(detail["applied_at"])
        project_record = obj.records.get(field="project", row_number=5)
        self.assertEqual((project_record.section, project_record.action, project_record.target_model),
                         ("PROJECTS", "CREATED", "Project"))
        # Texte d'origine de toute la ligne, multilignes compris.
        self.assertIn("- Cadrage réalisé\\n- Maquettes validées", project_record.original_text)
        self.assertIn("KAYDAN / DATARIUM", project_record.original_text)
        self.assertEqual(obj.records.get(field="project", row_number=6).action, "LINKED")
        texts = set(obj.records.values_list("original_text", flat=True))
        for expected in ("Maquettes validées", "Installer le pilote", "En attente de la décision du port",
                         "SORO Ibrahima", "DSI", "Renouveler le certificat"):
            self.assertIn(expected, texts)
        page = self.api(self.pm).get(f"/api/v1/tracking/imports/{obj.pk}/records/").json()
        self.assertEqual(page["count"], obj.records.count())
        self.assertEqual(page["count"], detail["report"]["records"])
        self.assertTrue(all(not r["rolled_back"] for r in page["results"]))

    def test_reimporting_the_same_file_creates_no_duplicate(self):
        self.imported()
        before = self.counts()
        again = self.upload()
        rows = {row["id"]: row for row in again.json()["analysis"]["rows"]}
        self.assertEqual({row["default"]["action"] for row in rows.values()}, {"link"})
        self.assertEqual({i["default"]["action"] for row in rows.values() for i in row["next"]}, {"link"})
        self.assertEqual({a["default"]["action"] for row in rows.values() for a in row["alerts"]}, {"link"})
        self.assertEqual(again.json()["analysis"]["container"]["default"]["mode"], "existing")
        applied = self.apply(again.json()["id"])
        self.assertEqual(applied.status_code, 200, applied.content)
        self.assertEqual(self.counts(), before)
        counts = applied.json()["report"]["counts"]
        self.assertNotIn("created", counts["project"])
        self.assertNotIn("created", counts["action_done"])

    def test_apply_twice_is_refused(self):
        detail = self.imported()
        before = self.counts()
        again = self.apply(detail["id"])
        self.assertEqual(again.status_code, 400)
        self.assertIn("déjà été appliqué", again.json()["detail"])
        self.assertEqual(self.counts(), before)
        analyze = self.api(self.pm).post(f"/api/v1/tracking/imports/{detail['id']}/analyze/", {}, format="json")
        self.assertEqual(analyze.status_code, 400)

    def test_rollback_then_replay(self):
        initial = self.counts()
        detail = self.imported()
        rolled = self.api(self.pm).post(f"/api/v1/tracking/imports/{detail['id']}/rollback/", {}, format="json")
        self.assertEqual(rolled.status_code, 200, rolled.content)
        self.assertEqual(rolled.json()["state"], "rolled_back")
        self.assertEqual(rolled.json()["rolled_back_by"]["id"], self.pm.pk)
        # Annulation logique : créations archivées, liens et historique retirés, existant intact.
        for name in ("AFFLUX", "Projet Mystère", importer.DEFAULT_CONTAINER):
            self.assertTrue(dm.Project.objects.get(workspace=self.ws, name=name).is_archived, name)
        self.assertFalse(dm.Task.objects.filter(is_archived=False, title="Veille techno").exists())
        self.assertFalse(dm.Risk.objects.filter(is_archived=False).exists())
        self.assertFalse(dm.MeetingDecision.objects.filter(is_archived=False).exists())
        self.project.refresh_from_db()
        self.assertFalse(self.project.is_archived)
        after = self.counts()
        for name in ("logs", "labels", "project_labels", "task_labels", "stakeholders", "members"):
            self.assertEqual(after[name], initial[name], name)
        self.assertFalse(dm.ProjectImportRecord.objects.filter(rolled_back_at__isnull=True).exists())
        self.assertEqual(self.titles(), {"Portail", "Interne"})
        twice = self.api(self.pm).post(f"/api/v1/tracking/imports/{detail['id']}/rollback/", {}, format="json")
        self.assertEqual(twice.status_code, 400)
        # Rejeu : le projet archivé est restauré, pas dupliqué.
        replay = self.apply(detail["id"])
        self.assertEqual(replay.status_code, 200, replay.content)
        self.assertEqual(replay.json()["state"], "applied")
        self.assertEqual(dm.Project.objects.filter(workspace=self.ws, name="AFFLUX").count(), 1)
        self.assertFalse(dm.Project.objects.get(workspace=self.ws, name="AFFLUX").is_archived)
        self.assertIn("AFFLUX", self.titles())
        self.assertEqual(dm.Task.objects.filter(is_archived=False, title="Veille techno").count(), 1)

    def test_user_decisions_override_the_defaults(self):
        created = self.upload().json()
        rows = {row["id"]: row for row in created["analysis"]["rows"]}
        end = next(a for a in created["analysis"]["ambiguities"] if a["id"] == "P6:end")
        self.assertIn("2026-04-20", [o["value"] for o in end["options"]])
        decisions = {
            "people": {importer.key("SORO Ibrahima"): {"user_id": self.lead.pk}},
            "ambiguities": {"P5:progress": 100, "P6:end": "2026-04-20"},
            "rows": {"P6": {"action": "update"}, "T14": {"action": "skip"}},
            "items": {rows["P5"]["next"][1]["id"]: {"action": "skip"},
                      rows["P7"]["next"][0]["id"]: {"action": "link", "target_id": self.task.pk}},
            "alerts": {rows["P5"]["alerts"][0]["id"]: {"kind": "BLOCKER", "severity": "CRITICAL"},
                       rows["P7"]["alerts"][0]["id"]: {"action": "skip"}},
            "statuses": {importer.norm("À lancer"): {"project": "ON_HOLD"}},
            "done_as_tasks": True,
        }
        applied = self.apply(created["id"], decisions)
        self.assertEqual(applied.status_code, 200, applied.content)
        report = applied.json()["report"]
        self.assertEqual(report["unresolved_members"], ["Awa KONE"])
        self.assertEqual(report["ambiguities_kept"], [])

        afflux = dm.Project.objects.get(workspace=self.ws, name="AFFLUX")
        self.assertEqual(afflux.progress_percent, 100)
        self.assertEqual(sorted(dm.Task.objects.filter(project=afflux).values_list("title", "status")),
                         [("Acheter le capteur MileSight", "TODO"), ("Cadrage réalisé", "DONE"),
                          ("Maquettes validées", "DONE")])
        risk = dm.Risk.objects.get(project=afflux)
        self.assertEqual((risk.category, risk.severity), ("BLOCKER", "CRITICAL"))
        # Mise à jour explicite du projet existant, avec les valeurs levées par l'utilisateur.
        self.project.refresh_from_db()
        self.assertEqual((self.project.status, self.project.progress_percent), ("DONE", 40))
        self.assertEqual((self.project.start_date, self.project.target_date), (date(2025, 12, 9), date(2026, 4, 20)))
        self.assertEqual(self.project.owner, self.lead)
        self.assertTrue(dm.ProjectMember.objects.filter(project=self.project, user=self.lead,
                                                        role="Porteur").exists())
        self.assertFalse(dm.ProjectStakeholder.objects.filter(project=self.project, role="PORTEUR").exists())
        mystery = dm.Project.objects.get(workspace=self.ws, name="Projet Mystère")
        self.assertEqual(mystery.status, "ON_HOLD")
        self.assertFalse(dm.Task.objects.filter(project=mystery).exists())  # rattachée à une tâche existante
        self.assertFalse(dm.Risk.objects.filter(project=mystery).exists())
        self.assertFalse(dm.Task.objects.filter(title="Veille techno").exists())
        # Retour arrière : le projet existant retrouve ses valeurs.
        self.api(self.pm).post(f"/api/v1/tracking/imports/{created['id']}/rollback/", {}, format="json")
        self.project.refresh_from_db()
        self.assertNotEqual(self.project.status, "DONE")
        self.assertIsNone(self.project.target_date)
        self.assertIsNone(self.project.owner)

    def test_invalid_decisions_write_nothing(self):
        created = self.upload().json()
        before = self.counts()
        soro = importer.key("SORO Ibrahima")
        cases = [
            {"people": {soro: {"user_id": self.bob.pk}}},  # utilisateur d'un autre espace
            {"ambiguities": {"P5:progress": 55}},  # valeur hors des choix proposés
            {"rows": {"P5": {"action": "link", "target_id": self.foreign_project.pk}}},  # projet d'un autre espace
            {"rows": {"P7": {"action": "explode"}}},
            {"alerts": {"P7:a0": {"kind": "NOPE"}}},
            {"container": {"mode": "existing", "project_id": self.foreign_project.pk}},
        ]
        for decisions in cases:
            response = self.apply(created["id"], decisions)
            self.assertEqual(response.status_code, 400, decisions)
            self.assertEqual(self.counts(), before, decisions)
        detail = self.api(self.pm).get(f"/api/v1/tracking/imports/{created['id']}/").json()
        self.assertEqual(detail["state"], "analyzed")
        wrong_type = self.api(self.pm).post(f"/api/v1/tracking/imports/{created['id']}/apply/",
                                            {"decisions": ["x"]}, format="json")
        self.assertEqual(wrong_type.status_code, 400)

    def test_legacy_import_endpoints_know_the_tracking_kind(self):
        created = self.upload().json()
        listing = self.api(self.pm).get("/api/v1/imports/")
        self.assertEqual(listing.status_code, 200)
        data = listing.json()
        rows = data["results"] if isinstance(data, dict) else data
        row = next(r for r in rows if r["id"] == created["id"])
        self.assertEqual(row["kind"], importer.KIND)
        legacy = self.api(self.pm).post(f"/api/v1/imports/{created['id']}/analyze/", {}, format="json")
        self.assertEqual(legacy.status_code, 400)
        search = self.api(self.pm).get(f"/api/v1/tracking/imports/{created['id']}/tasks/", {"q": "AP"})
        self.assertEqual([t["title"] for t in search.json()["results"]], ["API"])


# ---------------------------------------------------------------------------
# RBAC et cloisonnement
# ---------------------------------------------------------------------------
class TrackingRbacTests(TrackingFixture):
    def test_import_is_reserved_to_authorised_roles(self):
        for user in (self.dev, self.lead, self.customer):
            self.assertEqual(self.upload(user).status_code, 403, user.username)
            self.assertEqual(self.api(user).get("/api/v1/tracking/imports/").status_code, 403, user.username)
        self.assertEqual(self.upload(self.owner).status_code, 201)
        listing = self.api(self.pm).get("/api/v1/tracking/imports/").json()
        self.assertEqual([w["name"] for w in listing["workspaces"]], ["Alpha"])
        self.assertEqual(len(listing["results"]), 1)
        self.assertEqual(dm.ProjectDocumentImport.objects.count(), 1)

    def test_import_is_scoped_to_the_workspace(self):
        created = self.upload().json()
        base = f"/api/v1/tracking/imports/{created['id']}/"
        bob = self.api(self.bob)
        self.assertEqual(bob.get(base).status_code, 404)
        self.assertEqual(bob.get(base + "records/").status_code, 404)
        self.assertEqual(bob.get(base + "tasks/", {"q": "API"}).status_code, 404)
        for action in ("analyze", "apply", "rollback"):
            self.assertEqual(bob.post(base + action + "/", {}, format="json").status_code, 404, action)
        self.assertEqual(self.upload(self.bob).status_code, 404)  # espace d'un autre tenant
        self.assertEqual(self.upload(self.pm, workspace=self.other).status_code, 404)
        self.assertEqual(self.api(self.pm).post(
            "/api/v1/tracking/imports/", {"workspace": "999999"}, format="multipart").status_code, 404)
        # Lecteur de l'espace sans droit d'import : 403, jamais le contenu.
        self.assertEqual(self.api(self.dev).get(base).status_code, 403)
        self.assertEqual(self.apply(created["id"], user=self.dev).status_code, 403)
        self.assertFalse(dm.Project.objects.filter(name="AFFLUX").exists())
        self.assertEqual(self.api(self.bob).get("/api/v1/tracking/imports/").json()["results"], [])

    def test_board_scope_follows_the_role(self):
        self.imported()
        activities = {"Maintenance serveurs · Sauvegardes", "Veille techno", "Support utilisateurs"}
        everything = {"Portail", "Interne", "AFFLUX", "Projet Mystère"} | activities
        self.assertEqual(self.titles(self.pm), everything)
        self.assertEqual(self.titles(self.owner), everything)
        # Membre : uniquement ce qui lui est attribué.
        self.assertEqual(self.titles(self.dev), {"Maintenance serveurs · Sauvegardes"})
        self.assertEqual(self.titles(self.outsider), {"Interne"})
        self.assertEqual(self.titles(self.bob), {"Secret"})
        self.assertEqual(self.board(self.customer).status_code, 403)
        self.assertEqual(self.export(self.customer).status_code, 403)
        self.assertEqual(self.api(self.customer).get("/api/v1/tracking/brief/").status_code, 403)
        dev = self.board(self.dev).json()
        self.assertTrue(dev["scope"]["restricted"])
        self.assertFalse(dev["can_import"])
        self.assertEqual(dev["kpis"]["projects_total"], 0)
        self.assertEqual(dev["options"]["companies"], ["DATARIUM"])
        self.assertTrue(self.board(self.pm).json()["can_import"])
        # Un filtre ne permet pas de sortir du périmètre.
        self.assertEqual(self.titles(self.dev, q="AFFLUX"), set())
        self.assertEqual(self.titles(self.bob, workspace=self.ws.pk), set())

    def test_project_synthesis_is_scoped(self):
        self.imported()
        afflux = dm.Project.objects.get(name="AFFLUX")
        url = f"/api/v1/tracking/projects/{afflux.pk}/"
        body = self.api(self.pm).get(url)
        self.assertEqual(body.status_code, 200, body.content)
        row = body.json()["row"]
        self.assertEqual(row["title"], "AFFLUX")
        self.assertEqual([o["name"] for o in row["owners"]], ["Serge OGAH"])
        self.assertEqual(row["contacts"], ["M. Koné", "Mme Traoré"])
        self.assertEqual([i["text"] for i in row["done"]], ["Cadrage réalisé", "Maquettes validées"])
        self.assertEqual(sorted(i["text"] for i in row["next"]),
                         ["Acheter le capteur MileSight", "Installer le pilote"])
        self.assertEqual(sorted(a["kind"] for a in row["alerts"]), ["DECISION", "DEPENDENCY"])
        self.assertTrue(row["blocked"])
        self.assertEqual(row["pending_decisions"], 1)
        self.assertTrue(body.json()["recent"])
        for user in (self.bob, self.dev, self.customer):
            self.assertEqual(self.api(user).get(url).status_code, 404, user.username)
        self.assertEqual(self.api(self.pm).get(
            f"/api/v1/tracking/projects/{self.foreign_project.pk}/").status_code, 404)
        container = dm.Project.objects.get(name=importer.DEFAULT_CONTAINER)
        activities = self.api(self.pm).get(f"/api/v1/tracking/projects/{container.pk}/").json()
        self.assertIsNone(activities["row"])
        self.assertEqual(len(activities["activities"]), 3)

    def test_anonymous_is_refused(self):
        from rest_framework.test import APIClient

        for path in ("board/", "export/", "brief/", "imports/", f"projects/{self.project.pk}/"):
            self.assertIn(APIClient().get(f"/api/v1/tracking/{path}").status_code, (401, 403), path)


# ---------------------------------------------------------------------------
# Vue consolidée, indicateurs, synthèse
# ---------------------------------------------------------------------------
class TrackingBoardTests(TrackingFixture):
    def setUp(self):
        super().setUp()
        self.imported()

    def test_rows_are_consolidated_views_of_existing_data(self):
        body = self.board().json()
        rows = {row["title"]: row for row in body["rows"]}
        self.assertEqual(body["count"], 7)
        self.assertEqual(body["total"], 7)
        self.assertNotIn(importer.DEFAULT_CONTAINER, rows)  # le projet d'accueil n'est pas un projet du suivi
        afflux = rows["AFFLUX"]
        self.assertEqual(afflux["kind"], "project")
        self.assertEqual(afflux["companies"], ["DATARIUM", "KAYDAN"])
        self.assertEqual((afflux["progress"], afflux["status_key"], afflux["sheet_status"]), (1, "en_cours", "En cours"))
        self.assertEqual((afflux["start"], afflux["end"], afflux["late"]), ("2026-01-05", "2099-06-30", False))
        self.assertEqual((afflux["done_count"], afflux["next_count"]), (2, 2))
        self.assertEqual(afflux["url"], f"/projects/{afflux['pk']}")
        maintenance = rows["Maintenance serveurs · Sauvegardes"]
        self.assertEqual((maintenance["kind"], maintenance["status_key"]), ("task", "suspendu"))
        self.assertTrue(maintenance["late"])
        self.assertGreater(maintenance["days_late"], 300)
        self.assertEqual([o["name"] for o in maintenance["owners"]], ["Awa Diallo"])
        self.assertEqual(maintenance["contacts"], ["DSI"])
        self.assertEqual([i["text"] for i in maintenance["next"]], ["Renouveler le certificat"])
        self.assertEqual(rows["Projet Mystère"]["owners"], [{"name": "Awa KONE", "user_id": None}])
        self.assertEqual([o["name"] for o in rows["Portail"]["owners"]], ["Serge OGAH", "SORO Ibrahima"])
        # Une tâche terminée dans DevFlow rejoint les actions réalisées, sans ressaisie.
        dm.Task.objects.filter(title="Acheter le capteur MileSight").update(status="DONE")
        afflux = next(r for r in self.board().json()["rows"] if r["title"] == "AFFLUX")
        self.assertIn("Acheter le capteur MileSight", [i["text"] for i in afflux["done"]])
        self.assertEqual([i["text"] for i in afflux["next"]], ["Installer le pilote"])

    def test_kpis_and_charts(self):
        body = self.board().json()
        kpis = body["kpis"]
        self.assertEqual(kpis["projects_total"], 4)
        self.assertEqual(kpis["projects_done"], 0)
        self.assertEqual(kpis["projects_suspended"], 0)
        self.assertEqual(kpis["projects_late"], 0)
        self.assertEqual(kpis["projects_blocked"], 1)
        self.assertEqual(kpis["pending_decisions"], 1)
        self.assertEqual(kpis["activities_total"], 3)
        self.assertEqual(kpis["progress_avg"], 0)  # (1 + 0 + 0 + 0) / 4
        # Ouvertes : API, Doc, 2 actions AFFLUX, 1 Mystère, 1 sous-tâche + 2 activités non closes.
        self.assertEqual(kpis["tasks_open"], 8)
        # En retard : l'activité Maintenance et sa sous-tâche (échéance 10/01/2025).
        self.assertEqual(kpis["tasks_late"], 2)
        charts = body["charts"]
        self.assertEqual({c["label"]: c["value"] for c in charts["by_company"]},
                         {"KAYDAN": 2, "DATARIUM": 1, "Sans entreprise": 2})
        self.assertEqual(sum(c["value"] for c in charts["by_status"]), 4)
        self.assertEqual(sum(c["value"] for c in charts["progress"]), 4)
        self.assertEqual(charts["deadlines"][0], {"label": "En retard", "value": 1})
        self.assertIn({"label": "06/2099", "value": 1}, charts["deadlines"])
        workload = {c["label"]: c for c in charts["workload"]}
        self.assertEqual((workload["Serge OGAH"]["projects"], workload["Serge OGAH"]["tasks"]), (2, 1))
        self.assertEqual(workload["Awa Diallo"]["tasks"], 1)
        alerts = {c["key"]: c["value"] for c in charts["alerts"]}
        self.assertEqual((alerts["CRITICAL"], alerts["DECISION"]), (1, 1))
        self.assertEqual(sum(alerts.values()), 3)
        self.assertEqual(body["options"]["companies"], ["DATARIUM", "KAYDAN"])

    def test_filters(self):
        activities = {"Maintenance serveurs · Sauvegardes", "Veille techno", "Support utilisateurs"}
        self.assertEqual(self.titles(company="datarium"), {"AFFLUX", "Maintenance serveurs · Sauvegardes"})
        self.assertEqual(self.titles(company="aucune"), {"Interne", "Projet Mystère", "Support utilisateurs"})
        self.assertEqual(self.titles(status="suspendu"), {"Maintenance serveurs · Sauvegardes"})
        self.assertEqual(self.titles(status="suspendu,annule"), {"Maintenance serveurs · Sauvegardes", "Veille techno"})
        self.assertEqual(self.titles(late="1"), {"Maintenance serveurs · Sauvegardes"})
        self.assertNotIn("Maintenance serveurs · Sauvegardes", self.titles(late="0"))
        self.assertEqual(self.titles(owner=str(self.pm.pk)), {"AFFLUX", "Portail", "Support utilisateurs"})
        self.assertEqual(self.titles(owner="awa kone"), {"Projet Mystère"})
        self.assertEqual(self.titles(q="capteur milesight"), {"AFFLUX"})
        self.assertEqual(self.titles(q="traoré"), {"AFFLUX"})
        self.assertEqual(self.titles(alert="DECISION"), {"AFFLUX"})
        self.assertEqual(self.titles(alert="RISK"), {"Projet Mystère"})
        self.assertEqual(self.titles(alert="1"), {"AFFLUX", "Projet Mystère"})
        self.assertEqual(self.titles(section="tasks"), activities)
        self.assertEqual(self.titles(progress_min="50"), {"Veille techno", "Support utilisateurs"})
        self.assertEqual(self.titles(progress_max="0", section="projects"), {"Portail", "Interne", "Projet Mystère"})
        self.assertEqual(self.titles(**{"from": "2099-01-01"}), {"AFFLUX"})
        self.assertEqual(self.titles(to="2025-12-31"), {"Maintenance serveurs · Sauvegardes"})
        afflux = dm.Project.objects.get(name="AFFLUX")
        self.assertEqual(self.titles(project=afflux.pk), {"AFFLUX"})
        body = self.board(company="DATARIUM", late="1").json()
        self.assertEqual(body["filters"], ["Entreprise : DATARIUM", "En retard uniquement"])
        self.assertEqual((body["count"], body["total"]), (1, 7))
        self.assertEqual(body["kpis"]["projects_total"], 0)  # indicateurs calculés sur les lignes filtrées
        for params in ({"status": "inconnu"}, {"late": "oui"}, {"from": "2026-13-01"}, {"alert": "x"},
                       {"progress_min": "150"}, {"section": "all"}, {"workspace": "abc"},
                       {"from": "2026-05-01", "to": "2026-01-01"}):
            self.assertEqual(self.board(**params).status_code, 400, params)
            self.assertEqual(self.export(**params).status_code, 400, params)

    def test_brief_reports_real_facts_only(self):
        body = self.api(self.pm).get("/api/v1/tracking/brief/").json()
        self.assertEqual(body["source"], "rules")
        facts = {f["kind"]: f["text"] for f in body["facts"]}
        self.assertIn("1 élément(s) attendent une décision : AFFLUX.", facts["decision"])
        self.assertIn("En attente de l'achat du capteur", " ".join(f["text"] for f in body["facts"]
                                                                   if f["kind"] == "blocker"))
        self.assertIn("1 échéance(s) dépassée(s)", facts["late"])
        self.assertIn("Projet Mystère", facts["risk"])
        self.assertIn("Serge OGAH (3)", facts["workload"])
        empty = self.api(self.pm).get("/api/v1/tracking/brief/", {"q": "introuvable-zzz"}).json()
        self.assertEqual([f["kind"] for f in empty["facts"]], ["ok"])
        # Sans fournisseur IA : la synthèse factuelle est renvoyée telle quelle.
        offline = self.api(self.pm).post("/api/v1/tracking/brief/", {}, format="json")
        self.assertEqual(offline.status_code, 200, offline.content)
        self.assertEqual((offline.json()["source"], offline.json()["text"]), ("rules", body["text"]))
        # La reformulation IA suit le droit « ai.summarize » ; sans accès au suivi, rien n'est renvoyé.
        self.assertEqual(self.api(self.lead).post("/api/v1/tracking/brief/", {}, format="json").status_code, 200)
        self.assertEqual(self.api(self.customer).post("/api/v1/tracking/brief/", {}, format="json").status_code, 403)

    def test_brief_ai_only_rewrites_the_computed_facts(self):
        provider = mock.Mock()
        provider.is_available.return_value = True
        provider.generate.return_value = mock.Mock(text="Note de pilotage reformulée.")
        with mock.patch("project.services.ai.factory.get_ai_provider", return_value=provider):
            body = self.api(self.pm).post("/api/v1/tracking/brief/", {}, format="json").json()
        self.assertEqual((body["source"], body["text"]), ("ai", "Note de pilotage reformulée."))
        self.assertTrue(body["facts"])
        messages = provider.generate.call_args.args[0]
        self.assertEqual(messages[1].content, "\n".join(f"- {f['text']}" for f in body["facts"]))
        # Fournisseur en panne : jamais d'erreur, jamais de texte inventé.
        provider.generate.side_effect = RuntimeError("boom")
        with mock.patch("project.services.ai.factory.get_ai_provider", return_value=provider):
            fallback = self.api(self.pm).post("/api/v1/tracking/brief/", {}, format="json")
        self.assertEqual((fallback.status_code, fallback.json()["source"]), (200, "rules"))


# ---------------------------------------------------------------------------
# Export Excel « Direction » et rapports
# ---------------------------------------------------------------------------
class TrackingExportTests(TrackingFixture):
    def setUp(self):
        super().setUp()
        self.imported()

    @staticmethod
    def find(ws, text, column=1):
        return next((r for r in range(1, ws.max_row + 1) if ws.cell(r, column).value == text), None)

    def test_same_structure_as_the_historical_workbook(self):
        response = self.export()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], XLSX)
        self.assertRegex(response["Content-Disposition"], r'attachment; filename="Suivi_Pole_Developpement_[\d-]+\.xlsx"')
        self.assertEqual(response["Cache-Control"], "no-store")
        wb = load_workbook(io.BytesIO(response.content))
        self.assertEqual(wb.sheetnames, ["PROJET", "Statut", "Informations"])
        ws = wb["PROJET"]
        self.assertEqual(ws["A2"].value, PROJECTS_TITLE)
        self.assertEqual([c.value for c in ws[4]], PROJECT_HEADERS)
        tasks_title = self.find(ws, TASKS_TITLE)
        self.assertEqual([c.value for c in ws[tasks_title + 2]], TASK_HEADERS)
        self.assertEqual(tasks_title, 5 + 4 + 1)  # 4 projets à partir de la ligne 5, une ligne vide
        self.assertEqual([c.value for c in wb["Statut"]["A"]], ["En cours", "suspendu", "réalisé", "Annulé"])
        # Mise en page
        self.assertEqual(ws.freeze_panes, "A5")
        self.assertEqual(ws.auto_filter.ref, "A4:K8")
        self.assertEqual(ws.page_setup.orientation, "landscape")
        self.assertEqual(ws.column_dimensions["B"].width, 54.5)
        # Mentions
        mention = ws["A1"].value
        for expected in ("Généré automatiquement depuis DevFlow", "Serge OGAH", "Périmètre : tous les projets de Alpha",
                         "Filtres : aucun"):
            self.assertIn(expected, mention)
        info = {row[0].value: row[1].value for row in wb["Informations"].iter_rows(min_row=1, max_col=2)
                if row[0].value}
        self.assertEqual(info["Origine"], "Généré automatiquement depuis DevFlow")
        self.assertEqual(info["Exporté par"], "Serge OGAH")
        self.assertEqual((info["Projets"], info["Tâches / activités"]), (4, 3))

    def test_values_come_from_devflow(self):
        ws = self.sheet()["PROJET"]
        line = self.find(ws, "AFFLUX", column=2)
        values = [c.value for c in ws[line]]
        self.assertEqual(values[0], "DATARIUM / KAYDAN")
        self.assertEqual(values[2], "Serge OGAH")
        self.assertEqual(values[3], "M. Koné\nMme Traoré")
        self.assertEqual(values[4], "— Cadrage réalisé\n— Maquettes validées")
        self.assertEqual(sorted(values[5].split("\n")), ["— Acheter le capteur MileSight", "— Installer le pilote"])
        self.assertEqual(sorted(values[6].split("\n")),
                         ["En attente de l'achat du capteur", "En attente de la décision du port"])
        self.assertEqual((values[7].date(), values[8].date()), (date(2026, 1, 5), date(2099, 6, 30)))
        self.assertEqual((values[9], values[10]), (1, "En cours"))
        self.assertEqual(ws.cell(line, 8).number_format, "DD/MM/YYYY")
        self.assertEqual(ws.cell(line, 10).number_format, '0"%"')
        self.assertTrue(ws.cell(line, 5).alignment.wrap_text)
        task_line = self.find(ws, "Maintenance serveurs · Sauvegardes", column=2)
        task = [c.value for c in ws[task_line]]
        self.assertEqual((task[0], task[2], task[3], task[9], task[10]), ("DATARIUM", "Awa Diallo", "DSI", 30, "suspendu"))
        self.assertEqual(task[8].date(), date(2025, 1, 10))
        # Statuts normalisés sur les quatre valeurs du classeur.
        statuses = {ws.cell(r, 11).value for r in range(5, ws.max_row + 1)} - {None, "STATUT"}
        self.assertLessEqual(statuses, {"En cours", "suspendu", "réalisé", "Annulé"})

    def test_export_can_be_read_back_by_the_importer(self):
        response = self.export()
        result = importer.parse_workbook(io.BytesIO(response.content))
        self.assertEqual([s["kind"] for s in result["sections"]], ["PROJECTS", "TASKS"])
        board_rows = self.board().json()["rows"]
        self.assertEqual([r["title"] for r in result["rows"]], [r["title"] for r in board_rows])
        by_title = {r["title"]: r for r in result["rows"]}
        afflux = by_title["AFFLUX"]
        self.assertEqual((afflux["start"], afflux["end"], afflux["status_key"]), ("2026-01-05", "2099-06-30", "en_cours"))
        self.assertEqual([i["text"] for i in afflux["done"]], ["Cadrage réalisé", "Maquettes validées"])
        self.assertEqual(afflux["companies"], ["DATARIUM", "KAYDAN"])
        self.assertTrue(all(r["status_key"] for r in result["rows"]))
        self.assertEqual(by_title["Maintenance serveurs · Sauvegardes"]["progress"], 30)

    def test_export_follows_the_active_filters(self):
        ws = self.sheet(company="DATARIUM", late="0")["PROJET"]
        titles = {ws.cell(r, 2).value for r in range(5, ws.max_row + 1)} - {None, "TACHE / ACTIVITE"}
        self.assertEqual(titles, {"AFFLUX"})
        self.assertIn("Filtres : Entreprise : DATARIUM · Sans retard", ws["A1"].value)
        only_tasks = self.sheet(section="tasks")["PROJET"]
        self.assertIsNone(self.find(only_tasks, "AFFLUX", column=2))
        self.assertIsNotNone(self.find(only_tasks, "Veille techno", column=2))
        self.assertEqual(only_tasks["A5"].value, board.EMPTY_MENTION)

    def test_export_never_exceeds_the_user_scope(self):
        def cells(user, **params):
            ws = self.sheet(user, **params)["PROJET"]
            return {c.value for row in ws.iter_rows(min_row=5) for c in row if isinstance(c.value, str)}

        dev = cells(self.dev)
        self.assertIn("Maintenance serveurs · Sauvegardes", dev)
        for hidden in ("AFFLUX", "Portail", "Veille techno", "Support utilisateurs", "Secret"):
            self.assertNotIn(hidden, dev)
        self.assertIn("vos projets et tâches", self.sheet(self.dev)["PROJET"]["A1"].value)
        bob = cells(self.bob)
        self.assertIn("Secret", bob)
        self.assertNotIn("AFFLUX", bob)
        self.assertNotIn("AFFLUX", cells(self.bob, workspace=self.ws.pk))
        self.assertEqual(self.export(self.customer).status_code, 403)

    def test_empty_export_is_clean(self):
        wb = self.sheet(q="introuvable-zzz")
        ws = wb["PROJET"]
        self.assertEqual(ws["A2"].value, PROJECTS_TITLE)
        self.assertEqual([c.value for c in ws[4]], PROJECT_HEADERS)
        self.assertEqual(ws["A5"].value, board.EMPTY_MENTION)
        tasks_title = self.find(ws, TASKS_TITLE)
        self.assertEqual([c.value for c in ws[tasks_title + 2]], TASK_HEADERS)
        self.assertEqual(ws.cell(tasks_title + 3, 1).value, board.EMPTY_MENTION)
        info = {row[0].value: row[1].value for row in wb["Informations"].iter_rows(max_col=2) if row[0].value}
        self.assertEqual((info["Projets"], info["Tâches / activités"]), (0, 0))
        self.assertIn("Recherche : « introuvable-zzz »", info["Filtres appliqués"])

    def test_large_volume(self):
        label = dm.Label.objects.get(workspace=self.ws, name="KAYDAN")
        projects = dm.Project.objects.bulk_create([
            dm.Project(workspace=self.ws, name=f"Volume {i:04d}", owner=self.pm, status="IN_PROGRESS",
                       progress_percent=i % 101, start_date=date(2026, 1, 1), target_date=date(2026, 12, 31))
            for i in range(600)])
        dm.ProjectLabel.objects.bulk_create([dm.ProjectLabel(project=p, label=label) for p in projects])
        dm.Task.objects.bulk_create([
            dm.Task(workspace=self.ws, project=p, title=f"Action {p.name}", status="TODO") for p in projects])
        with CaptureQueriesContext(connection) as queries:
            response = self.export()
        self.assertEqual(response.status_code, 200)
        self.assertLess(len(queries), 40)  # pas de requête par ligne
        ws = load_workbook(io.BytesIO(response.content))["PROJET"]
        self.assertEqual(ws.auto_filter.ref, "A4:K608")
        self.assertIsNotNone(self.find(ws, "Volume 0599", column=2))
        self.assertEqual(self.find(ws, TASKS_TITLE), 610)
        self.assertEqual(self.board().json()["count"], 607)

    def test_formats_and_pdf_reports(self):
        self.assertEqual(self.export(fmt="csv").status_code, 400)
        self.assertEqual(self.export(fmt="pdf", variant="annual").status_code, 400)
        for variant in ("direction", "weekly", "monthly"):
            response = self.export(fmt="pdf", variant=variant, company="DATARIUM")
            self.assertEqual(response.status_code, 200, variant)
            self.assertEqual(response["Content-Type"], "application/pdf")
            self.assertTrue(response.content.startswith(b"%PDF"), variant)
            self.assertIn(f"Suivi_Pole_Developpement_{variant}_", response["Content-Disposition"])
        self.assertEqual(self.export(self.customer, fmt="pdf").status_code, 403)


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
class TrackingNotificationTests(TrackingFixture):
    def tracking(self, **filters):
        return dm.Notification.objects.filter(metadata__source=notifications.SOURCE, **filters)

    def test_daily_sweep_notifies_once(self):
        self.imported()
        afflux = dm.Project.objects.get(name="AFFLUX")
        result = notifications.run_sweep(today=date(2099, 6, 28))
        self.assertFalse(result["truncated"])
        self.assertEqual(result["total"], self.tracking().count())
        kinds = lambda user: sorted(self.tracking(recipient=user).values_list("metadata__kind", flat=True))  # noqa: E731
        # pm : AFFLUX (échéance dans 2 jours, décision attendue, bloqué) ; Support n'a pas d'échéance.
        self.assertEqual(kinds(self.pm), ["blocked", "deadline", "decision"])
        # dev : activité Maintenance en retard et suspendue.
        self.assertEqual(kinds(self.dev), ["blocked", "late"])
        deadline = self.tracking(recipient=self.pm, metadata__kind="deadline").get()
        self.assertEqual(deadline.url, f"/projects/{afflux.pk}/")
        self.assertIn("dans 2 jours", deadline.title)
        self.assertEqual(deadline.workspace, self.ws)
        # Le lendemain : pas de répétition des alertes déjà envoyées.
        again = notifications.run_sweep(today=date(2099, 6, 28))
        self.assertEqual(again["total"], 0)
        from project.tasks import run_tracking_alert_sweep

        self.assertEqual(run_tracking_alert_sweep()["deadline"], 0)

    def test_immediate_events(self):
        self.imported()
        self.assertFalse(self.tracking().exists())  # l'import n'émet qu'un récapitulatif
        afflux = dm.Project.objects.get(name="AFFLUX")
        dm.Risk.objects.create(workspace=self.ws, project=afflux, title="Serveur saturé", severity="HIGH")
        alert = self.tracking(metadata__kind="new_alert").get()
        self.assertEqual((alert.recipient, alert.body), (self.pm, "Serveur saturé"))
        decision = dm.MeetingDecision.objects.create(workspace=self.ws, title="Arbitrage budget", status="PENDING")
        decision.projects.add(afflux)
        self.assertEqual(self.tracking(metadata__kind="decision_created").get().recipient, self.pm)
        validated = dm.MeetingDecision.objects.create(workspace=self.ws, title="Déjà validée")
        validated.projects.add(afflux)
        self.assertEqual(self.tracking(metadata__kind="decision_created").count(), 1)
        afflux.owner = self.dev
        afflux.save()
        change = self.tracking(metadata__kind="owner_changed").get()
        self.assertEqual(change.recipient, self.dev)
        afflux.name = "AFFLUX 2"
        afflux.save()
        self.assertEqual(self.tracking(metadata__kind="owner_changed").count(), 1)
        # Projet sans porteur : personne à prévenir, aucune erreur.
        dm.Risk.objects.create(workspace=self.ws, project=self.project2, title="Sans porteur")
        self.assertEqual(self.tracking(metadata__kind="new_alert").count(), 1)
