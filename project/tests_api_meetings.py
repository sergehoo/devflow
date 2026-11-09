"""
Chantier « meetings » — API JSON des réunions, séries, décisions et
enregistrements pour le frontend React (``project/api/views_meetings.py``).

Isolation workspace (404 cross-tenant sur chaque endpoint par PK), droits
(présences), throttle IA, envois par Celery uniquement, non-régression des
pages historiques après extraction de leurs contextes.

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_api_meetings
"""

import shutil
import tempfile
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone

from project import models as dm
from project.tests_legacy_rights import LegacyFixture


class MeetingFixture(LegacyFixture):
    def setUp(self):
        super().setUp()
        cache.clear()  # compteurs du throttle IA
        now = timezone.now()
        self.meeting = dm.ProjectMeeting.objects.create(
            workspace=self.ws, project=self.project, title="Comité Portail",
            scheduled_at=now + timedelta(days=1), organizer=self.pm, created_by=self.pm,
            notes="Action : préparer la démo", external_participants="Client — client@ext.test",
        )
        self.meeting.internal_participants.set([self.pm, self.dev, self.peer])
        for u in (self.pm, self.dev, self.peer):
            dm.MeetingParticipation.objects.create(meeting=self.meeting, user=u)
        self.past = dm.ProjectMeeting.objects.create(
            workspace=self.ws, project=self.project2, title="Rétro", scheduled_at=now - timedelta(days=2),
        )
        self.foreign = dm.ProjectMeeting.objects.create(
            workspace=self.other, project=self.foreign_project, title="Secret", scheduled_at=now,
        )
        self.recording = dm.MeetingRecording.objects.create(
            workspace=self.ws, meeting=self.meeting, recorded_by=self.pm,
            status=dm.MeetingRecording.Status.WAITING_SPEAKER_MAPPING, full_transcript="A: bonjour",
        )
        dm.DetectedSpeaker.objects.create(recording=self.recording, speaker_label="A", total_segments=1)
        dm.SpeakerSegment.objects.create(recording=self.recording, speaker_label="A", start_seconds=0,
                                         end_seconds=2, text="bonjour")
        self.foreign_recording = dm.MeetingRecording.objects.create(
            workspace=self.other, meeting=self.foreign, status=dm.MeetingRecording.Status.COMPLETED,
        )

    def post(self, user, url, data=None, **extra):
        return self.api(user).post(url, data or {"next": "/"}, format="multipart", **extra)


class MeetingReadTests(MeetingFixture):
    def test_list_is_scoped_sorted_and_filterable(self):
        data = self.api(self.dev).get("/api/v1/meetings/").json()
        titles = [r["title"] for r in data["results"]]
        self.assertEqual(titles, ["Comité Portail", "Rétro"])  # à venir puis passées
        self.assertEqual([r["is_past"] for r in data["results"]], [False, True])
        self.assertNotIn("Secret", titles)
        self.assertTrue(any(c["value"] == "FOLLOW_UP" for c in data["type_choices"]))
        filtered = self.api(self.dev).get("/api/v1/meetings/", {"project": self.project2.pk}).json()
        self.assertEqual([r["title"] for r in filtered["results"]], ["Rétro"])
        self.assertEqual(filtered["current_project"], {"id": self.project2.pk, "name": "Interne"})
        # Projet d'un autre tenant : jamais résolu.
        foreign = self.api(self.dev).get("/api/v1/meetings/", {"project": self.foreign_project.pk}).json()
        self.assertIsNone(foreign["current_project"])
        self.assertEqual(foreign["results"], [])

    def test_detail_exposes_full_sheet(self):
        dm.MeetingAgendaItem.objects.create(meeting=self.meeting, title="Budget", position=1, owner=self.dev)
        self.meeting.projects.set([self.project])
        dm.MeetingProjectReview.objects.create(meeting=self.meeting, project=self.project, position=1)
        data = self.api(self.dev).get(f"/api/v1/meetings/{self.meeting.pk}/").json()
        self.assertEqual(data["title"], "Comité Portail")
        self.assertEqual(data["agenda_items"][0]["owner"]["id"], self.dev.pk)
        self.assertEqual(data["my_participation"]["rsvp_status"], "INVITED")
        self.assertFalse(data["can_mark_attendance"])
        self.assertEqual(data["participations_stats"]["pending"], 3)
        self.assertIn("préparer", data["notes_html"])
        self.assertEqual(data["recordings"][0]["id"], self.recording.pk)
        self.assertEqual(data["downloads"]["pdf"], f"/meetings/{self.meeting.pk}/minutes.pdf")
        reviews = data["reviews"]
        self.assertEqual(reviews["prefix"], "project_reviews")
        self.assertEqual(reviews["management"]["project_reviews-TOTAL_FORMS"], 1)
        names = {f["name"]: f for f in reviews["forms"][0]["fields"]}
        self.assertEqual(names["project"]["type"], "hidden")
        self.assertIn("DELETE", names)
        self.assertTrue(self.api(self.pm).get(f"/api/v1/meetings/{self.meeting.pk}/").json()["can_mark_attendance"])

    def test_cross_tenant_objects_return_404(self):
        bob = self.api(self.bob)
        m, r = self.meeting.pk, self.recording.pk
        item = dm.MeetingAgendaItem.objects.create(meeting=self.meeting, title="Budget", position=1)
        action = dm.MeetingActionItem.objects.create(meeting=self.meeting, title="Démo")
        series = dm.MeetingSeries.objects.create(workspace=self.ws, name="Hebdo", time_local="09:00",
                                                 start_date=timezone.localdate(), weekday=0)
        for url in (f"/api/v1/meetings/{m}/", f"/api/v1/meetings/series/{series.pk}/",
                    f"/api/v1/meetings/recordings/{r}/", f"/api/v1/meetings/recordings/{r}/status/"):
            self.assertEqual(bob.get(url).status_code, 404, url)
        posts = [
            f"/api/v1/meetings/{m}/rsvp/", f"/api/v1/meetings/{m}/confirm-presence/",
            f"/api/v1/meetings/{m}/attendance/", f"/api/v1/meetings/{m}/agenda/",
            f"/api/v1/meetings/{m}/agenda/reorder/", f"/api/v1/meetings/{m}/agenda/{item.pk}/",
            f"/api/v1/meetings/{m}/agenda/{item.pk}/delete/", f"/api/v1/meetings/{m}/actions/",
            f"/api/v1/meetings/actions/{action.pk}/convert/", f"/api/v1/meetings/{m}/reviews/",
            f"/api/v1/meetings/{m}/send-minutes/", f"/api/v1/meetings/{m}/ai-process/",
            f"/api/v1/meetings/{m}/ai-summary/",
            f"/api/v1/meetings/recordings/{r}/speakers/", f"/api/v1/meetings/recordings/{r}/confirm-speakers/",
            f"/api/v1/meetings/recordings/{r}/regenerate/", f"/api/v1/meetings/recordings/{r}/delete/",
            f"/api/v1/meetings/recordings/{r}/decisions/", f"/api/v1/meetings/recordings/{r}/actions/",
            f"/api/v1/meetings/recordings/{r}/suggestions/", f"/api/v1/meetings/recordings/{r}/send-minutes/",
        ]
        with mock.patch("project.tasks.send_meeting_minutes_email_async.delay") as d1, \
                mock.patch("project.tasks.send_recording_minutes_email_async.delay") as d2:
            for url in posts:
                self.assertEqual(self.post(self.bob, url, {"title": "x", "order": str(item.pk)}).status_code, 404, url)
        d1.assert_not_called()
        d2.assert_not_called()
        self.assertTrue(dm.MeetingRecording.objects.filter(pk=r).exists())
        self.assertTrue(dm.MeetingAgendaItem.objects.filter(pk=item.pk, title="Budget").exists())
        # Et dans l'autre sens : le dev de W1 n'atteint pas les objets de W2.
        self.assertEqual(self.api(self.dev).get(f"/api/v1/meetings/{self.foreign.pk}/").status_code, 404)
        self.assertEqual(self.api(self.dev).get(f"/api/v1/meetings/recordings/{self.foreign_recording.pk}/").status_code, 404)

    def test_dashboard_decisions_and_series(self):
        dm.MeetingDecision.objects.create(workspace=self.ws, meeting=self.meeting, title="Go prod",
                                          status=dm.MeetingDecision.Status.EXECUTED)
        dm.MeetingDecision.objects.create(workspace=self.other, title="Décision secrète")
        dash = self.api(self.dev).get("/api/v1/meetings/dashboard/").json()
        self.assertEqual([m["title"] for m in dash["upcoming"]], ["Comité Portail"])
        self.assertEqual(dash["execution_rate"], 100.0)
        self.assertTrue(dash["calendar"])
        decisions = self.api(self.dev).get("/api/v1/meetings/decisions/").json()
        self.assertEqual([d["title"] for d in decisions["results"]], ["Go prod"])
        self.assertEqual(decisions["results"][0]["meeting"]["id"], self.meeting.pk)
        filtered = self.api(self.dev).get("/api/v1/meetings/decisions/", {"status": "PENDING"}).json()
        self.assertEqual(filtered["results"], [])

    def test_series_create_through_bridge_detail_and_regenerate(self):
        payload = {"name": "Comité hebdo", "meeting_type": "FOLLOW_UP", "recurrence": "WEEKLY", "weekday": 0,
                   "time_local": "09:30", "duration_minutes": 60, "start_date": timezone.localdate().isoformat(),
                   "is_active": "on"}
        res = self.api(self.pm).post("/api/v1/forms/meeting-series/", payload, format="multipart")
        self.assertEqual(res.status_code, 201, res.content)  # identifiant renvoyé (self.object)
        series_id = res.json()["id"]
        detail = self.api(self.dev).get(f"/api/v1/meetings/series/{series_id}/").json()
        self.assertEqual(detail["name"], "Comité hebdo")
        self.assertTrue(detail["upcoming"])
        listing = self.api(self.dev).get("/api/v1/meetings/series/").json()
        self.assertEqual([s["name"] for s in listing["results"]], ["Comité hebdo"])
        regen = self.api(self.pm).post(f"/api/v1/resources/meeting-series/{series_id}/actions/regenerate/",
                                       {"next": "/"}, format="multipart")
        self.assertEqual(regen.status_code, 200)


class MeetingWriteTests(MeetingFixture):
    def test_agenda_crud_and_reorder(self):
        base = f"/api/v1/meetings/{self.meeting.pk}/agenda/"
        self.assertEqual(self.post(self.dev, base, {"title": ""}).status_code, 400)
        self.assertEqual(self.post(self.dev, base, {"title": "Budget", "owner": self.dev.pk, "duration_minutes": 10}).status_code, 200)
        self.assertEqual(self.post(self.dev, base, {"title": "Planning", "owner": self.bob.pk}).status_code, 200)
        first, second = dm.MeetingAgendaItem.objects.filter(meeting=self.meeting).order_by("position")
        self.assertIsNone(second.owner_id)  # owner hors workspace ignoré
        res = self.post(self.dev, f"{base}reorder/", {"order": f"{second.pk},{first.pk}"})
        self.assertEqual(res.json(), {"ok": True, "updated": 2})
        res = self.post(self.dev, f"{base}{first.pk}/", {"status": "IN_PROGRESS", "notes": "En cours"})
        self.assertEqual(res.status_code, 200)
        first.refresh_from_db()
        self.assertEqual((first.status, first.position, first.notes), ("IN_PROGRESS", 2, "En cours"))
        self.assertIsNotNone(first.started_at)
        self.assertEqual(self.post(self.dev, f"{base}{first.pk}/delete/").status_code, 200)
        self.assertFalse(dm.MeetingAgendaItem.objects.filter(pk=first.pk).exists())

    def test_rsvp_presence_and_attendance_rights(self):
        url = f"/api/v1/meetings/{self.meeting.pk}"
        self.assertEqual(self.post(self.dev, f"{url}/rsvp/", {"rsvp_status": "ACCEPTED"}).status_code, 200)
        self.assertEqual(self.post(self.dev, f"{url}/rsvp/", {"rsvp_status": "PIRATE"}).status_code, 400)
        self.assertEqual(self.post(self.outsider, f"{url}/rsvp/", {"rsvp_status": "ACCEPTED"}).status_code, 400)  # non invité
        self.assertEqual(self.post(self.dev, f"{url}/confirm-presence/").status_code, 200)
        p = dm.MeetingParticipation.objects.get(meeting=self.meeting, user=self.dev)
        self.assertEqual((p.rsvp_status, p.attendance_status, p.self_confirmed), ("ACCEPTED", "PRESENT", True))
        # Pointage : organisateur uniquement (le dev reçoit un refus, rien ne change).
        res = self.post(self.dev, f"{url}/attendance/", {f"attendance_{self.peer.pk}": "ABSENT"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(dm.MeetingParticipation.objects.get(meeting=self.meeting, user=self.peer).attendance_status, "UNKNOWN")
        res = self.post(self.pm, f"{url}/attendance/", {f"attendance_{self.peer.pk}": "ABSENT"})
        self.assertEqual(res.status_code, 200)
        peer = dm.MeetingParticipation.objects.get(meeting=self.meeting, user=self.peer)
        self.assertEqual((peer.attendance_status, peer.attendance_marked_by_id), ("ABSENT", self.pm.pk))

    def test_action_items_create_and_convert(self):
        url = f"/api/v1/meetings/{self.meeting.pk}/actions/"
        # Le formulaire rapide n'envoie pas ``status`` : statut par défaut.
        self.assertEqual(self.post(self.dev, url, {"title": "Préparer la démo", "priority": "HIGH"}).status_code, 200)
        self.assertEqual(self.post(self.dev, url, {"title": "Pirate", "priority": "LOW", "owner": self.bob.pk}).status_code, 400)
        self.assertEqual(self.post(self.dev, url, {"title": "Doc", "priority": "LOW", "owner": self.dev.pk}).status_code, 200)
        item = dm.MeetingActionItem.objects.get(meeting=self.meeting, title="Préparer la démo")
        self.assertEqual(item.status, "OPEN")
        self.assertFalse(dm.MeetingActionItem.objects.filter(title="Pirate").exists())
        # RBAC : un MEMBER (sans task.create, pas responsable du projet) ne convertit pas.
        detail = self.api(self.dev).get(f"/api/v1/meetings/{self.meeting.pk}/").json()
        self.assertFalse(detail["can_convert_actions"])
        res = self.post(self.dev, f"/api/v1/meetings/actions/{item.pk}/convert/")
        self.assertEqual(res.status_code, 400)
        item.refresh_from_db()
        self.assertIsNone(item.converted_task_id)
        self.assertTrue(self.api(self.pm).get(f"/api/v1/meetings/{self.meeting.pk}/").json()["can_convert_actions"])
        res = self.post(self.pm, f"/api/v1/meetings/actions/{item.pk}/convert/")
        self.assertEqual(res.status_code, 200)
        item.refresh_from_db()
        self.assertIsNotNone(item.converted_task_id)
        self.assertEqual(item.converted_task.project_id, self.project.pk)
        self.assertEqual(item.converted_task.workspace_id, self.ws.pk)

    def test_reviews_formset_save(self):
        self.meeting.projects.set([self.project])
        review = dm.MeetingProjectReview.objects.create(meeting=self.meeting, project=self.project, position=1)
        reviews = self.api(self.dev).get(f"/api/v1/meetings/{self.meeting.pk}/").json()["reviews"]
        form = reviews["forms"][0]
        data = dict(reviews["management"])
        for f in form["fields"]:
            if f["value"] not in (None, "") and f["type"] != "checkbox":
                data[f"{form['prefix']}-{f['name']}"] = f["value"]
        data.update({f"{form['prefix']}-status_snapshot": "AT_RISK", f"{form['prefix']}-progress_pct": 40,
                     f"{form['prefix']}-blockers": "Recette"})
        self.assertEqual(self.post(self.dev, f"/api/v1/meetings/{self.meeting.pk}/reviews/", data).status_code, 200)
        review.refresh_from_db()
        self.assertEqual((review.status_snapshot, review.progress_pct, review.blockers), ("AT_RISK", 40, "Recette"))

    def test_send_minutes_goes_through_celery_only(self):
        url = f"/api/v1/meetings/{self.meeting.pk}/send-minutes/"
        with mock.patch("project.tasks.send_meeting_minutes_email_async.delay") as delay:
            self.assertEqual(self.post(self.dev, url).status_code, 200)
        delay.assert_called_once_with(self.meeting.pk, True)
        with mock.patch("project.tasks.send_meeting_minutes_email_async.delay", side_effect=OSError("broker")):
            self.assertEqual(self.post(self.dev, url).status_code, 503)
        self.assertEqual(len(mail.outbox), 0)  # jamais d'envoi synchrone

    @override_settings(DEVFLOW_AI_RATE_LIMIT="2/min", AI_BACKEND="none")
    def test_ai_actions_are_throttled_and_use_heuristics(self):
        url = f"/api/v1/meetings/{self.meeting.pk}/ai-process/"
        res = self.post(self.dev, url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertTrue(res.json()["ok"])
        # NullProvider : pas de résumé IA → refus explicite (aucun appel réseau).
        self.assertEqual(self.post(self.dev, f"/api/v1/meetings/{self.meeting.pk}/ai-summary/").status_code, 400)
        self.assertEqual(self.post(self.dev, url, HTTP_X_REQUESTED_WITH="XMLHttpRequest").status_code, 429)


class RecordingApiTests(MeetingFixture):
    def test_detail_status_and_speaker_mapping(self):
        status = self.api(self.dev).get(f"/api/v1/meetings/recordings/{self.recording.pk}/status/").json()
        self.assertEqual((status["status"], status["progress_percent"], status["is_final"]),
                         ("waiting_speaker_mapping", 70, False))
        data = self.api(self.dev).get(f"/api/v1/meetings/recordings/{self.recording.pk}/").json()
        self.assertEqual(data["speakers"][0]["label"], "A")
        self.assertFalse(data["all_mapped"])
        self.assertIn(str(self.dev.pk), [p["id"] for p in data["participants"]])
        self.assertEqual(data["segments"][0]["text"], "bonjour")
        url = f"/api/v1/meetings/recordings/{self.recording.pk}"
        # Participant d'un autre tenant refusé par le service de mapping.
        self.assertEqual(self.post(self.dev, f"{url}/speakers/", {"speaker_A": self.bob.pk}).status_code, 400)
        self.assertEqual(self.post(self.dev, f"{url}/speakers/", {"speaker_A": self.dev.pk}).status_code, 200)
        data = self.api(self.dev).get(f"{url}/").json()
        self.assertTrue(data["all_mapped"])
        self.assertEqual(data["segments"][0]["speaker"], "dev")
        with mock.patch("project.tasks.finalize_recording_task.delay") as delay:
            self.assertEqual(self.post(self.dev, f"{url}/confirm-speakers/").status_code, 200)
        delay.assert_called_once_with(self.recording.pk)
        self.recording.refresh_from_db()
        self.assertEqual(self.recording.status, "generating_summary")

    def test_extractions_accept_create_and_convert(self):
        url = f"/api/v1/meetings/recordings/{self.recording.pk}"
        K = dm.RecordingAIExtraction.Kind
        dec = dm.RecordingAIExtraction.objects.create(recording=self.recording, kind=K.DECISION, title="Go")
        act = dm.RecordingAIExtraction.objects.create(recording=self.recording, kind=K.ACTION, title="Relancer", priority_hint="haute")
        task = dm.RecordingAIExtraction.objects.create(recording=self.recording, kind=K.TASK_SUGGESTION, title="Écrire la doc",
                                                       priority_hint="high", assignee_hint="dev")
        self.assertEqual(self.post(self.dev, f"{url}/decisions/", {"accept_decision": [dec.pk]}).status_code, 200)
        self.assertEqual(self.post(self.dev, f"{url}/actions/", {"accept_action": [act.pk]}).status_code, 200)
        # RBAC : le MEMBER ne crée pas de tâche depuis une suggestion IA.
        rights = self.api(self.dev).get(f"{url}/").json()
        self.assertEqual((rights["can_create_tasks"], rights["can_create_projects"]), (False, False))
        self.assertEqual(self.post(self.dev, f"{url}/suggestions/", {"accept_suggestion": [task.pk]}).status_code, 400)
        task.refresh_from_db()
        self.assertFalse(task.is_accepted)
        self.assertFalse(dm.Task.objects.filter(title="Écrire la doc").exists())
        self.assertEqual(self.post(self.pm, f"{url}/suggestions/", {"accept_suggestion": [task.pk]}).status_code, 200)
        dec.refresh_from_db()
        act.refresh_from_db()
        task.refresh_from_db()
        self.assertTrue(dec.is_accepted and act.is_accepted and task.is_accepted)
        self.assertEqual(act.created_action_item.priority, "HIGH")
        created = dm.Task.objects.get(title="Écrire la doc")
        self.assertEqual((created.project_id, created.assignee_id, created.reporter_id), (self.project.pk, self.dev.pk, self.pm.pk))

    def test_project_suggestion_requires_project_create(self):
        url = f"/api/v1/meetings/recordings/{self.recording.pk}"
        K = dm.RecordingAIExtraction.Kind
        sug = dm.RecordingAIExtraction.objects.create(recording=self.recording, kind=K.PROJECT_SUGGESTION, title="Projet IA")
        # MEMBER (peer) : pas de project.create → refus, rien n'est créé.
        self.assertEqual(self.post(self.peer, f"{url}/suggestions/", {"accept_suggestion": [sug.pk]}).status_code, 400)
        self.assertFalse(dm.Project.objects.filter(name="Projet IA").exists())
        # Responsable d'un projet mais MEMBER : toujours pas de création de projet.
        self.assertEqual(self.post(self.outsider, f"{url}/suggestions/", {"accept_suggestion": [sug.pk]}).status_code, 400)
        self.assertTrue(self.api(self.pm).get(f"{url}/").json()["can_create_projects"])
        self.assertEqual(self.post(self.pm, f"{url}/suggestions/", {"accept_suggestion": [sug.pk]}).status_code, 200)
        self.assertTrue(dm.Project.objects.filter(name="Projet IA", workspace=self.ws).exists())

    def test_regenerate_is_throttled_and_delete(self):
        url = f"/api/v1/meetings/recordings/{self.recording.pk}"
        with override_settings(DEVFLOW_AI_RATE_LIMIT="1/min"), \
                mock.patch("project.tasks.finalize_recording_task.delay") as delay:
            self.assertEqual(self.post(self.dev, f"{url}/regenerate/").status_code, 200)
            self.assertEqual(self.post(self.dev, f"{url}/regenerate/").status_code, 429)
        delay.assert_called_once()
        self.assertEqual(self.post(self.dev, f"{url}/delete/").status_code, 200)
        self.assertFalse(dm.MeetingRecording.objects.filter(pk=self.recording.pk).exists())

    def test_send_recording_minutes_via_celery(self):
        url = f"/api/v1/meetings/recordings/{self.recording.pk}/send-minutes/"
        with mock.patch("project.tasks.send_recording_minutes_email_async.delay") as delay:
            res = self.post(self.dev, url, {"extra_emails": "a@b.test, pas-un-mail"})
        self.assertEqual(res.status_code, 200)
        delay.assert_called_once_with(self.recording.pk, ["a@b.test"], True)
        self.assertEqual(len(mail.outbox), 0)
        # Sans aucun destinataire : refus explicite.
        lonely = dm.ProjectMeeting.objects.create(workspace=self.ws, title="Solo", scheduled_at=timezone.now())
        rec = dm.MeetingRecording.objects.create(workspace=self.ws, meeting=lonely)
        with mock.patch("project.tasks.send_recording_minutes_email_async.delay") as delay:
            self.assertEqual(self.post(self.dev, f"/api/v1/meetings/recordings/{rec.pk}/send-minutes/").status_code, 400)
        delay.assert_not_called()

    def test_upload_endpoint_reused_by_react_is_scoped(self):
        audio = SimpleUploadedFile("recording.webm", b"\x1aE\xdf\xa3fake", content_type="audio/webm")
        client = self.web(self.bob)
        with mock.patch("project.tasks.process_recording_task.delay") as delay:
            res = client.post(f"/api/v1/meetings/{self.meeting.pk}/recordings/upload/", {"audio": audio})
        self.assertEqual(res.status_code, 404)
        delay.assert_not_called()

    def test_upload_is_throttled_for_both_interfaces(self):
        from django.urls import resolve

        url = f"/api/v1/meetings/{self.meeting.pk}/recordings/upload/"
        # La route API (throttlée) recouvre la route historique ``api_recording_upload``.
        self.assertEqual(resolve(url).url_name, "api-meeting-recording-upload")
        media = tempfile.mkdtemp(prefix="devflow-rec-tests-")
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        client = self.web(self.dev)  # session, comme React et l'ancien widget

        def upload():
            audio = SimpleUploadedFile("recording.webm", b"\x1aE\xdf\xa3fake", content_type="audio/webm")
            return client.post(url, {"audio": audio, "duration_seconds": "12", "consent_acknowledged": "true"})

        with override_settings(DEVFLOW_AI_RATE_LIMIT="1/min", MEDIA_ROOT=media), \
                mock.patch("project.tasks.process_recording_task.delay") as delay:
            first = upload()
            self.assertEqual(first.status_code, 202, first.content)
            self.assertEqual(upload().status_code, 429)
        delay.assert_called_once_with(int(first.json()["recording_id"]))
        created = dm.MeetingRecording.objects.get(pk=first.json()["recording_id"])
        self.assertEqual((created.meeting_id, created.recorded_by_id, created.consent_acknowledged),
                         (self.meeting.pk, self.dev.pk, True))
        self.assertEqual(dm.MeetingRecording.objects.filter(meeting=self.meeting).count(), 2)  # fixture + 1


class MeetingFormsScopingTests(MeetingFixture):
    """
    SECURITY — ``ProjectMeetingForm`` / ``MeetingSeriesForm`` / revues : le workspace
    courant était retiré des kwargs avant ``StyledModelForm`` (qui le remettait à
    ``None``) → projets, sprints et personnes de tous les tenants proposés et acceptés.
    """

    @staticmethod
    def choices(schema, name):
        field = next(f for f in schema["fields"] if f["name"] == name)
        return {c["value"] for c in field.get("choices", []) if c["value"]}

    def test_meeting_form_choices_are_workspace_scoped(self):
        schema = self.api(self.dev).get("/api/v1/forms/meeting/").json()
        self.assertIn(str(self.project.pk), self.choices(schema, "project"))
        self.assertNotIn(str(self.foreign_project.pk), self.choices(schema, "project"))
        self.assertNotIn(str(self.foreign_project.pk), self.choices(schema, "projects"))
        self.assertNotIn(str(self.bob.pk), self.choices(schema, "internal_participants"))
        self.assertNotIn(str(self.bob.pk), self.choices(schema, "organizer"))
        # Création : tous les membres du workspace invités par défaut (comportement prévu).
        invited = next(f for f in schema["fields"] if f["name"] == "internal_participants")["value"]
        self.assertIn(self.dev.pk, invited)
        self.assertNotIn(self.bob.pk, invited)

    def test_meeting_form_rejects_foreign_project_and_people(self):
        base = {"title": "Pirate", "meeting_type": "FOLLOW_UP", "status": "PLANNED",
                "scheduled_at": "2030-01-01T10:00", "duration_minutes": 60}
        for extra in ({"project": self.foreign_project.pk}, {"projects": [self.foreign_project.pk]},
                      {"internal_participants": [self.bob.pk]}, {"organizer": self.bob.pk}):
            res = self.api(self.dev).post("/api/v1/forms/meeting/", {**base, **extra}, format="multipart")
            self.assertEqual(res.status_code, 400, extra)
        self.assertFalse(dm.ProjectMeeting.objects.filter(title="Pirate").exists())
        res = self.api(self.dev).post("/api/v1/forms/meeting/", {**base, "project": self.project.pk,
                                                                 "internal_participants": [self.dev.pk]}, format="multipart")
        self.assertEqual(res.status_code, 201, res.content)
        created = dm.ProjectMeeting.objects.get(pk=res.json()["id"])
        self.assertEqual(list(created.participations.values_list("user_id", flat=True)), [self.dev.pk])

    def test_series_and_review_forms_are_scoped(self):
        schema = self.api(self.dev).get("/api/v1/forms/meeting-series/").json()
        self.assertNotIn(str(self.bob.pk), self.choices(schema, "default_participants"))
        self.assertNotIn(str(self.foreign_project.pk), self.choices(schema, "default_projects"))
        self.meeting.projects.set([self.project])
        dm.MeetingProjectReview.objects.create(meeting=self.meeting, project=self.project, position=1)
        form = self.api(self.dev).get(f"/api/v1/meetings/{self.meeting.pk}/").json()["reviews"]["forms"][0]
        presenters = {c["value"] for c in next(f for f in form["fields"] if f["name"] == "presented_by")["choices"] if c["value"]}
        self.assertIn(str(self.dev.pk), presenters)
        self.assertNotIn(str(self.bob.pk), presenters)


class SharedAIQuotaTests(MeetingFixture):
    """Le quota IA est commun aux routes historiques et à l'API (même compteur)."""

    @override_settings(DEVFLOW_AI_RATE_LIMIT="1/min", AI_BACKEND="none")
    def test_legacy_ai_views_share_the_api_quota(self):
        web = self.web(self.dev)
        with mock.patch("project.views_meeting.MeetingIntelligenceService.full_process") as full:
            self.assertEqual(web.post(f"/meetings/{self.meeting.pk}/ai-summary/").status_code, 302)  # quota consommé
            res = web.post(f"/meetings/{self.meeting.pk}/ai-process/")
            self.assertEqual(res.status_code, 302)
            res = web.post(f"/meetings/{self.meeting.pk}/ai-process/", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
            self.assertEqual(res.status_code, 429)
        full.assert_not_called()
        # Même compteur côté API.
        self.assertEqual(self.post(self.dev, f"/api/v1/meetings/{self.meeting.pk}/ai-summary/").status_code, 429)

    @override_settings(DEVFLOW_AI_RATE_LIMIT="1/min")
    def test_api_consumption_limits_legacy_recording_views(self):
        self.recording.status = dm.MeetingRecording.Status.COMPLETED
        self.recording.save(update_fields=["status"])
        with mock.patch("project.tasks.finalize_recording_task.delay") as delay:
            url = f"/api/v1/meetings/recordings/{self.recording.pk}/regenerate/"
            self.assertEqual(self.post(self.dev, url).status_code, 200)  # 1 seul comptage (pont)
            web = self.web(self.dev)
            self.assertEqual(web.post(f"/recordings/{self.recording.pk}/regenerate-summary/").status_code, 302)
            self.assertEqual(web.post(f"/recordings/{self.recording.pk}/confirm-speakers/").status_code, 302)
        delay.assert_called_once_with(self.recording.pk)
        # Un autre utilisateur garde son propre quota.
        with mock.patch("project.tasks.finalize_recording_task.delay") as delay:
            self.assertEqual(self.web(self.pm).post(f"/recordings/{self.recording.pk}/regenerate-summary/").status_code, 302)
        delay.assert_called_once_with(self.recording.pk)


class LegacyEmailsAreAsyncTests(MeetingFixture):
    """AGENTS.md n°6 : plus aucun envoi SMTP synchrone depuis les vues historiques."""

    def test_meeting_minutes_without_celery_do_not_send_synchronously(self):
        web = self.web(self.dev)
        with mock.patch("project.tasks.send_meeting_minutes_email_async.delay", side_effect=OSError("broker")), \
                mock.patch("project.services.meeting.MeetingService.send_minutes_email") as sync:
            self.assertEqual(web.post(f"/meetings/{self.meeting.pk}/send-minutes/").status_code, 302)
            # Même chemin via la ressource générique (action « send-minutes »).
            res = self.post(self.dev, f"/api/v1/resources/meeting/{self.meeting.pk}/actions/send-minutes/")
            self.assertEqual(res.status_code, 400)
        sync.assert_not_called()
        self.assertEqual(len(mail.outbox), 0)

    def test_recording_minutes_are_dispatched_to_celery(self):
        url = f"/meetings/{self.meeting.pk}/recordings/{self.recording.pk}/send-minutes/"
        with mock.patch("project.tasks.send_recording_minutes_email_async.delay") as delay, \
                mock.patch("project.services.recording.export.send_recording_email") as sync:
            self.assertEqual(self.web(self.dev).post(url, {"extra_emails": "a@b.test"}).status_code, 302)
        delay.assert_called_once_with(self.recording.pk, ["a@b.test"], True)
        sync.assert_not_called()
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(self.web(self.bob).post(url).status_code, 404)


class NoWorkspaceUserTests(MeetingFixture):
    """
    SECURITY — compte authentifié sans workspace (inscription ouverte, aucun
    profil créé en multi-tenant) : jamais de projets / personnes d'autres tenants.
    """

    def setUp(self):
        super().setUp()
        self.lonely = get_user_model().objects.create_user("lonely", "lonely@x.test", "pw")

    def test_create_forms_are_unreachable(self):
        api = self.api(self.lonely)
        for url in ("/api/v1/forms/meeting/", "/api/v1/forms/meeting-series/"):
            self.assertEqual(api.get(url).status_code, 404, url)
            res = api.post(url, {"title": "x", "name": "x", "project": self.foreign_project.pk}, format="multipart")
            self.assertEqual(res.status_code, 404, url)
        web = self.web(self.lonely)
        self.assertEqual(web.get("/meetings/create/").status_code, 404)
        self.assertEqual(web.get("/meetings/series/create/").status_code, 404)
        self.assertEqual(dm.ProjectMeeting.objects.filter(title="x").count(), 0)

    def test_forms_fail_closed_without_workspace(self):
        from project.forms_meeting import MeetingProjectReviewForm, MeetingSeriesForm, ProjectMeetingForm

        for form, names in (
            (ProjectMeetingForm(), ("project", "projects", "sprint", "internal_participants", "organizer")),
            (MeetingSeriesForm(), ("default_projects", "default_participants", "organizer")),
            (MeetingProjectReviewForm(), ("project", "presented_by")),
        ):
            for name in names:
                self.assertFalse(form.fields[name].queryset.exists(), f"{type(form).__name__}.{name}")
        # Avec un workspace : choix limités à ce workspace (non-régression).
        form = ProjectMeetingForm(current_workspace=self.ws)
        self.assertEqual(set(form.fields["project"].queryset.values_list("workspace_id", flat=True)), {self.ws.pk})


class LegacyPagesStillRenderTests(MeetingFixture):
    """Non-régression : les pages historiques rendent toujours après extraction de leurs contextes."""

    def test_pages(self):
        web = self.web(self.dev)
        for url in ("/meetings/dashboard/", "/meetings/decisions/", f"/meetings/{self.meeting.pk}/",
                    f"/meetings/{self.meeting.pk}/recordings/{self.recording.pk}/speakers/",
                    f"/meetings/{self.meeting.pk}/recordings/{self.recording.pk}/summary/"):
            self.assertEqual(web.get(url).status_code, 200, url)
        self.assertEqual(web.get(f"/meetings/{self.foreign.pk}/recordings/{self.foreign_recording.pk}/summary/").status_code, 404)

    def test_legacy_quick_action_form_now_works(self):
        res = self.web(self.dev).post(f"/meetings/{self.meeting.pk}/actions/create/",
                                      {"title": "Depuis l'ancienne fiche", "priority": "MEDIUM"})
        self.assertEqual(res.status_code, 302)
        self.assertTrue(dm.MeetingActionItem.objects.filter(title="Depuis l'ancienne fiche", status="OPEN").exists())


class AudioRangeAndFilterTests(MeetingFixture):
    """Lecture audio par plages (Safari/iOS, déplacement) et filtre ?project invalide."""

    def test_audio_stream_honours_range_requests(self):
        from django.core.files.base import ContentFile
        from django.urls import reverse

        media = tempfile.mkdtemp(prefix="devflow-rec-tests-")
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        with override_settings(MEDIA_ROOT=media):
            self.recording.audio_file.save("t.webm", ContentFile(b"0123456789"), save=True)
            url = reverse("recording_stream_audio", args=[self.recording.pk])
            web = self.web(self.dev)
            read = lambda r: b"".join(r.streaming_content)  # noqa: E731
            full = web.get(url)
            self.assertEqual((full.status_code, read(full)), (200, b"0123456789"))
            part = web.get(url, HTTP_RANGE="bytes=2-5")
            self.assertEqual((part.status_code, part["Content-Range"], read(part)), (206, "bytes 2-5/10", b"2345"))
            tail = web.get(url, HTTP_RANGE="bytes=-3")
            self.assertEqual((tail.status_code, read(tail)), (206, b"789"))
            self.assertEqual(web.get(url, HTTP_RANGE="bytes=20-").status_code, 416)
            self.assertIn(self.web(self.bob).get(url, HTTP_RANGE="bytes=0-1").status_code, (401, 403, 404))

    def test_non_numeric_project_filter_is_empty_not_500(self):
        res = self.api(self.dev).get("/api/v1/meetings/?project=abc")
        self.assertEqual(res.status_code, 200)


class StaleMessagesTests(MeetingFixture):
    """Un message d'erreur laissé par une vue historique (export / envoi en échec) ne fait
    plus échouer l'action suivante exécutée par le pont React."""

    def test_bridge_ignores_messages_left_by_previous_request(self):
        web = self.web(self.dev)
        with mock.patch("project.tasks.send_meeting_minutes_email_async.delay", side_effect=OSError("broker")):
            self.assertEqual(web.post(f"/meetings/{self.meeting.pk}/send-minutes/").status_code, 302)  # message en attente
        res = web.post(f"/api/v1/actions/task-done/{self.task.pk}/", {"next": "/"})
        self.assertEqual(res.status_code, 200, res.content)
        self.assertFalse(any("indisponible" in m for m in res.json().get("messages", [])))
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, dm.Task.Status.DONE)
