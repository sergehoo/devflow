"""
Ticketing multi-applications : API d'intégration (HMAC, idempotence, quotas),
isolation multi-tenant, routage, affectation, workflow, SLA, commentaires,
pièces jointes, webhooks (signature, backoff, SSRF), permissions, notifications,
tâches liées.

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_ticketing
"""

import json
import shutil
import socket
import tempfile
import time
from datetime import datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from project import models as dm
from project.services import ticketing as svc
from project.services import ticketing_webhooks as hooks

URL = "/api/v1/integrations/tickets/"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
PUBLIC_IP = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
PRIVATE_IP = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443))]


class TicketingFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        mk = lambda name: User.objects.create_user(name, f"{name}@x.test", "pw", first_name=name.title())  # noqa: E731
        cls.owner, cls.pm, cls.agent1, cls.agent2, cls.outsider, cls.bob = (
            mk(n) for n in ("owner", "pm", "agent1", "agent2", "outsider", "bob"))
        cls.ws = dm.Workspace.objects.create(name="Alpha", owner=cls.owner)
        cls.other_ws = dm.Workspace.objects.create(name="Beta", owner=cls.bob)
        cls.support = dm.Team.objects.create(workspace=cls.ws, name="Support N1", lead=cls.pm)
        for user, ws, team in ((cls.owner, cls.ws, None), (cls.pm, cls.ws, None), (cls.agent1, cls.ws, cls.support),
                               (cls.agent2, cls.ws, cls.support), (cls.outsider, cls.ws, None), (cls.bob, cls.other_ws, None)):
            dm.UserProfile.objects.update_or_create(user=user, defaults={"workspace": ws})
            dm.TeamMembership.objects.create(user=user, workspace=ws, team=team)
        dm.WorkspaceRoleAssignment.objects.create(user=cls.pm, workspace=cls.ws, role="PROJECT_MANAGER")
        cls.project = dm.Project.objects.create(workspace=cls.ws, name="Portail")
        cls.app, cls.secret = cls.make_app(cls.ws, "portail", project=cls.project)
        cls.other_app, cls.other_secret = cls.make_app(cls.other_ws, "secret-app")

    @staticmethod
    def make_app(ws, code, **extra):
        key_id, secret = svc.new_credentials()
        app = dm.ExternalApplication(workspace=ws, name=code.title(), code=code, key_id=key_id, **extra)
        svc.set_secret(app, secret)
        app.save()
        return app, secret

    def setUp(self):
        cache.clear()
        self.media = tempfile.mkdtemp(prefix="devflow-tickets-")
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        patcher = override_settings(MEDIA_ROOT=self.media)
        patcher.enable()
        self.addCleanup(patcher.disable)
        schedule = mock.patch("project.services.ticketing_webhooks._schedule")
        self.schedule = schedule.start()
        self.addCleanup(schedule.stop)

    # ── Helpers ──
    def signed(self, method, path, body=b"", app=None, secret=None, ts=None, **extra):
        app, secret = app or self.app, secret or self.secret
        ts = str(ts or int(time.time()))
        sig = svc.signature(secret, ts, method, path, body)
        headers = {"HTTP_X_DEVFLOW_APP": app.key_id, "HTTP_X_DEVFLOW_TIMESTAMP": ts, "HTTP_X_DEVFLOW_SIGNATURE": f"sha256={sig}", **extra}
        if method == "GET":
            return self.client.get(path, **headers)
        return self.client.post(path, data=body, content_type="application/json", **headers)

    def create(self, external_id="EXT-1", app=None, secret=None, **fields):
        payload = {"external_id": external_id, "title": "Paiement bloqué", "severity": "MAJOR", "category": "BUG",
                   "reporter": {"id": "u-42", "name": "Awa", "email": "awa@client.test"}, **fields}
        return self.signed("POST", URL, json.dumps(payload).encode(), app=app, secret=secret)

    def ticket(self, external_id="EXT-1"):
        return dm.Ticket.objects.get(application=self.app, external_id=external_id)

    def api(self, user):
        self.client.force_login(user)
        return self.client


class IntegrationApiTests(TicketingFixture):
    def test_hmac_and_dedicated_credentials_authenticate_and_invalid_ones_are_rejected(self):
        res = self.create()
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual((res.json()["reference"], res.json()["status"]), ("TCK-00001", "NEW"))
        self.assertNotIn(self.secret, res.content.decode())
        body = json.dumps({"external_id": "EXT-2", "title": "Autre"}).encode()
        bad = self.signed("POST", URL, body, secret="dfs_mauvais")
        self.assertEqual(bad.status_code, 401)
        self.assertEqual(self.signed("POST", URL, body, ts=int(time.time()) - 3600).status_code, 401)  # hors fenêtre
        ts = str(int(time.time()))
        headers = {"HTTP_X_DEVFLOW_APP": self.app.key_id, "HTTP_X_DEVFLOW_TIMESTAMP": ts,
                   "HTTP_X_DEVFLOW_SIGNATURE": svc.signature(self.secret, ts, "POST", URL, body)}
        self.assertEqual(self.client.post(URL, body, content_type="application/json", **headers).status_code, 201)
        self.assertEqual(self.client.post(URL, body, content_type="application/json", **headers).status_code, 401)  # rejeu
        cred = {"HTTP_AUTHORIZATION": f"DevFlowApp {self.app.key_id}:{self.secret}"}
        self.assertEqual(self.client.get(URL, **cred).status_code, 200)
        self.assertEqual(self.client.get(URL, HTTP_AUTHORIZATION=f"DevFlowApp {self.app.key_id}:faux").status_code, 401)
        self.assertEqual(self.client.get(URL).status_code, 401)  # aucune session acceptée sur l'intégration
        self.app.status = "SUSPENDED"
        self.app.save()
        self.assertEqual(self.client.get(URL, **cred).status_code, 401)

    def test_idempotency_key_and_duplicate_protection(self):
        payload = json.dumps({"external_id": "EXT-9", "title": "Écran blanc"}).encode()
        now = int(time.time())
        r1 = self.signed("POST", URL, payload, ts=now, HTTP_IDEMPOTENCY_KEY="key-1")
        r2 = self.signed("POST", URL, payload, ts=now + 1, HTTP_IDEMPOTENCY_KEY="key-1")  # nouvel essai = nouvelle signature
        self.assertEqual((r1.status_code, r2.status_code), (201, 200))
        self.assertEqual(r1.json()["reference"], r2.json()["reference"])
        self.assertTrue(r2.json()["duplicate"])
        self.assertEqual(self.signed("POST", URL, payload, ts=now + 2).status_code, 200)  # même external_id
        other = json.dumps({"external_id": "EXT-10", "title": "Autre"}).encode()
        self.assertEqual(self.signed("POST", URL, other, ts=now + 3, HTTP_IDEMPOTENCY_KEY="key-1").status_code, 422)
        self.assertEqual(dm.Ticket.objects.filter(application=self.app).count(), 1)

    def test_strict_validation_and_sanitization(self):
        self.assertEqual(self.create(external_id="bad id!").status_code, 400)
        self.assertEqual(self.create(external_id="E-3", severity="APOCALYPSE").status_code, 400)
        res = self.create(external_id="E-4", url="https://app.test/pay?step=2&token=abc&session_id=s#frag",
                          metadata={"browser": "Firefox", "password": "x", "nested": {"api_key": "k", "screen": "1080p"}})
        self.assertEqual(res.status_code, 201)
        t = self.ticket("E-4")
        self.assertEqual(t.url, "https://app.test/pay?step=2")
        self.assertEqual(t.metadata, {"browser": "Firefox", "nested": {"screen": "1080p"}})
        self.assertEqual(self.create(external_id="E-5", metadata={"blob": ["x" * 400] * 30}).status_code, 400)

    def test_rate_limit_and_daily_quota(self):
        self.app.rate_limit_per_minute = 2
        self.app.daily_ticket_quota = 1
        self.app.save()
        self.assertEqual(self.create("Q-1").status_code, 201)
        self.assertEqual(self.create("Q-2").status_code, 429)  # quota journalier
        self.assertEqual(self.create("Q-3").status_code, 429)  # débit

    def test_isolation_between_applications_and_tenants(self):
        self.create()
        t = self.ticket()
        self.assertEqual(self.signed("GET", f"{URL}EXT-1/", app=self.other_app, secret=self.other_secret).status_code, 404)
        self.assertEqual(self.api(self.bob).get(f"/api/v1/tickets/{t.pk}/").status_code, 404)
        self.assertEqual(self.api(self.bob).get("/api/v1/tickets/").json()["results"], [])

    def test_public_history_hides_internal_comments_and_attachments(self):
        self.create()
        t = self.ticket()
        svc.add_comment(t, body="Note interne : client difficile", visibility="INTERNAL", user=self.owner)
        svc.add_comment(t, body="Nous analysons le problème.", visibility="PUBLIC", user=self.owner)
        res = self.signed("GET", f"{URL}EXT-1/").json()
        bodies = [c["body"] for c in res["comments"]]
        self.assertEqual(bodies, ["Nous analysons le problème."])
        self.assertEqual(res["comments"][0]["author"], {"type": "agent", "name": "Support"})
        self.assertNotIn("Note interne", json.dumps(res))

    def test_external_comment_with_attachment_and_mime_validation(self):
        self.create()
        url = f"{URL}EXT-1/comments/"
        ts = str(int(time.time()))
        upload = SimpleUploadedFile("capture.png", PNG, content_type="image/png")
        res = self.client.post(url, {"body": "Voici la capture", "author": json.dumps({"id": "u-42", "name": "Awa"}),
                                     "attachments": upload},
                               HTTP_AUTHORIZATION=f"DevFlowApp {self.app.key_id}:{self.secret}", HTTP_X_DEVFLOW_TIMESTAMP=ts)
        self.assertEqual(res.status_code, 201, res.content)
        t = self.ticket()
        self.assertEqual(t.attachments.get().visibility, "PUBLIC")
        fake = SimpleUploadedFile("capture.png", b"MZ\x90\x00not-a-png", content_type="image/png")
        bad = self.client.post(url, {"body": "Encore", "attachments": fake}, HTTP_AUTHORIZATION=f"DevFlowApp {self.app.key_id}:{self.secret}")
        self.assertEqual(bad.status_code, 400)
        exe = SimpleUploadedFile("virus.exe", b"MZ", content_type="application/x-msdownload")
        self.assertEqual(self.client.post(url, {"body": "Exe", "attachments": exe},
                                          HTTP_AUTHORIZATION=f"DevFlowApp {self.app.key_id}:{self.secret}").status_code, 400)
        dup = self.client.post(url, {"body": "Voici la capture", "author": json.dumps({"id": "u-42"})},
                               HTTP_AUTHORIZATION=f"DevFlowApp {self.app.key_id}:{self.secret}")
        self.assertEqual(dup.status_code, 409)  # anti-spam : doublon < 60 s


class RoutingAndWorkflowTests(TicketingFixture):
    def test_routing_rule_auto_assigns_least_loaded_eligible_agent(self):
        dm.TicketRoutingRule.objects.create(workspace=self.ws, name="Bugs majeurs", application=self.app, category="BUG",
                                            severity="MAJOR", team=self.support, auto_assign=True, priority_override="P1")
        busy = dm.Ticket.objects.create(workspace=self.ws, application=self.app, number=99, reference="TCK-00099",
                                        external_id="busy", title="x", assignee=self.agent1, status="IN_PROGRESS")
        self.assertTrue(busy.is_open)
        self.create()
        t = self.ticket()
        self.assertEqual((t.team_id, t.assignee_id, t.status, t.priority), (self.support.pk, self.agent2.pk, "ASSIGNED", "P1"))
        self.assertTrue(t.events.filter(action="assigned").exists())

    def test_unmatched_ticket_goes_to_unassigned_queue(self):
        self.create()
        t = self.ticket()
        self.assertEqual((t.team_id, t.assignee_id, t.status), (None, None, "NEW"))
        self.assertTrue(t.events.filter(action="unassigned_queue").exists())

    def test_manual_assignment_checks_team_membership_and_rights(self):
        self.create()
        t = self.ticket()
        url = f"/api/v1/tickets/{t.pk}/assign/"
        res = self.api(self.pm).post(url, {"team": self.support.pk, "assignee": self.outsider.pk}, content_type="application/json")
        self.assertEqual(res.status_code, 400)  # hors de l'équipe
        self.assertEqual(self.api(self.agent1).post(url, {"team": self.support.pk, "assignee": self.agent2.pk},
                                                    content_type="application/json").status_code, 404)  # pas encore visible
        res = self.api(self.pm).post(url, {"team": self.support.pk}, content_type="application/json")
        self.assertEqual(res.json()["status"], "QUALIFIED")
        self.assertEqual(self.api(self.agent1).post(url, {"team": self.support.pk, "assignee": self.agent2.pk},
                                                    content_type="application/json").status_code, 403)
        res = self.api(self.agent1).post(url, {"team": self.support.pk, "assignee": self.agent1.pk}, content_type="application/json")
        self.assertEqual((res.status_code, res.json()["assignee"]["id"], res.json()["status"]), (200, self.agent1.pk, "ASSIGNED"))

    def test_transitions_are_validated_and_reopen_from_external_comment(self):
        self.create()
        t = self.ticket()
        svc.assign(t, actor=self.pm, team_id=self.support.pk, assignee_id=self.agent1.pk)
        url = f"/api/v1/tickets/{t.pk}/transition/"
        agent = self.api(self.agent1)
        self.assertEqual(agent.post(url, {"status": "CLOSED"}, content_type="application/json").status_code, 409)
        self.assertEqual(agent.post(url, {"status": "CANCELLED", "note": "x"}, content_type="application/json").status_code, 403)
        for target in ("IN_PROGRESS", "WAITING", "IN_PROGRESS", "RESOLVED"):
            res = agent.post(url, {"status": target, "note": "Corrigé en v2.1" if target == "RESOLVED" else ""}, content_type="application/json")
            self.assertEqual(res.status_code, 200, (target, res.content))
        t.refresh_from_db()
        self.assertIsNotNone(t.first_response_at)
        self.assertIsNotNone(t.resolved_at)
        svc.add_comment(t, body="Toujours en panne", external={"id": "u-42", "name": "Awa"})
        t.refresh_from_db()
        self.assertEqual((t.status, t.reopened_count), ("IN_PROGRESS", 1))
        self.assertEqual(self.api(self.pm).post(url, {"status": "CANCELLED"}, content_type="application/json").status_code, 400)
        events = list(dm.TicketWebhookDelivery.objects.values_list("event", flat=True))
        self.assertEqual(events, [])  # aucune URL de webhook : rien n'est mis en file


class SlaTests(TicketingFixture):
    def test_business_hours_deadline_skips_nights_and_weekends(self):
        policy = dm.TicketSLAPolicy.objects.create(workspace=self.ws, name="Ouvré", business_days=[0, 1, 2, 3, 4],
                                                   business_start="08:00", business_end="18:00", timezone="UTC")
        friday_17h = datetime(2026, 11, 6, 17, 0, tzinfo=ZoneInfo("UTC"))
        due = svc.add_business_minutes(friday_17h, 120, policy)
        self.assertEqual(due, datetime(2026, 11, 9, 9, 0, tzinfo=ZoneInfo("UTC")))  # lundi 9 h
        self.assertEqual(svc.add_business_minutes(friday_17h, 30, None), friday_17h + timedelta(minutes=30))

    def test_waiting_pauses_sla_and_breach_escalates_with_notifications(self):
        self.create()
        t = self.ticket()
        svc.assign(t, actor=self.pm, team_id=self.support.pk, assignee_id=self.agent1.pk)
        svc.transition(t, "WAITING", actor=self.agent1)
        due_before = t.resolution_due
        dm.Ticket.objects.filter(pk=t.pk).update(sla_paused_at=timezone.now() - timedelta(hours=2))
        t.refresh_from_db()
        svc.transition(t, "IN_PROGRESS", actor=self.agent1)
        self.assertAlmostEqual((t.resolution_due - due_before).total_seconds(), 7200, delta=5)
        dm.Ticket.objects.filter(pk=t.pk).update(resolution_due=timezone.now() - timedelta(minutes=1))
        with mock.patch("project.services.realtime.push_to_users"):
            stats = svc.check_slas()
        t.refresh_from_db()
        self.assertEqual(stats["breached"], 1)
        self.assertTrue(t.resolution_breached)
        self.assertEqual(t.escalation_level, 1)
        self.assertTrue(dm.Notification.objects.filter(recipient=self.owner, title__contains="Escalade").exists())
        self.assertEqual(svc.check_slas()["breached"], 0)  # pas de double escalade

    def test_warning_before_breach(self):
        self.create()
        t = self.ticket()
        svc.assign(t, actor=self.pm, team_id=self.support.pk, assignee_id=self.agent1.pk)
        dm.Ticket.objects.filter(pk=t.pk).update(created_at=timezone.now() - timedelta(hours=9),
                                                 resolution_due=timezone.now() + timedelta(hours=1))
        self.assertEqual(svc.check_slas()["warned"], 1)
        self.assertTrue(dm.Notification.objects.filter(recipient=self.agent1, title__startswith="SLA bientôt").exists())


class WebhookTests(TicketingFixture):
    def setUp(self):
        super().setUp()
        self.app.webhook_url = "https://hooks.client.test/devflow"
        self.app.save()

    def deliver(self, response=None, error=None, ips=PUBLIC_IP):
        with mock.patch("socket.getaddrinfo", return_value=ips), \
                mock.patch("requests.post", return_value=response, side_effect=error) as post:
            outcome = hooks.deliver(dm.TicketWebhookDelivery.objects.latest("pk").pk)
        return outcome, post

    def test_events_are_signed_and_retried_with_backoff(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.create()
        delivery = dm.TicketWebhookDelivery.objects.get(event="ticket.created")
        self.schedule.assert_called_with(delivery.pk)
        outcome, _ = self.deliver(mock.Mock(status_code=500, text="boom"))
        delivery.refresh_from_db()
        self.assertEqual((outcome, delivery.attempt, delivery.status), ("failed", 1, "FAILED"))
        self.assertAlmostEqual((delivery.next_attempt_at - timezone.now()).total_seconds(), 60, delta=5)
        dm.TicketWebhookDelivery.objects.filter(pk=delivery.pk).update(next_attempt_at=timezone.now())
        outcome, post = self.deliver(mock.Mock(status_code=200, text="ok"))
        self.assertEqual(outcome, "success")
        kwargs = post.call_args.kwargs
        ts, sig = kwargs["headers"]["X-DevFlow-Timestamp"], kwargs["headers"]["X-DevFlow-Signature"]
        self.assertEqual(sig, f"sha256={hooks.sign(self.secret, ts, kwargs['data'])}")
        self.assertEqual(kwargs["headers"]["X-DevFlow-Event-Id"], str(delivery.event_id))
        self.assertFalse(kwargs["allow_redirects"])

    def test_ssrf_private_destination_is_never_called(self):
        self.create()
        outcome, post = self.deliver(ips=PRIVATE_IP)
        self.assertEqual(outcome, "dead")
        post.assert_not_called()

    def test_gives_up_after_max_attempts(self):
        self.create()
        delivery = dm.TicketWebhookDelivery.objects.latest("pk")
        dm.TicketWebhookDelivery.objects.filter(pk=delivery.pk).update(attempt=hooks.MAX_ATTEMPTS - 1)
        outcome, _ = self.deliver(mock.Mock(status_code=503, text=""))
        self.assertEqual(outcome, "dead")

    def test_webhook_failure_never_blocks_ticket_creation(self):
        self.schedule.stop()  # vrai _schedule, broker en panne
        with mock.patch("project.tasks.deliver_ticket_webhook_task.apply_async", side_effect=RuntimeError("broker down")), \
                self.captureOnCommitCallbacks(execute=True):
            res = self.create("W-2")
        self.schedule.start()
        self.assertEqual(res.status_code, 201)
        self.assertEqual(dm.TicketWebhookDelivery.objects.get().status, "PENDING")  # repris par retry_due()


class InternalApiAndPermissionTests(TicketingFixture):
    def test_member_sees_only_team_or_assigned_tickets_and_cannot_admin(self):
        self.create("A")
        self.create("B")
        a, b = self.ticket("A"), self.ticket("B")
        svc.assign(a, actor=self.pm, team_id=self.support.pk)
        ids = [r["id"] for r in self.api(self.agent1).get("/api/v1/tickets/").json()["results"]]
        self.assertEqual(ids, [a.pk])
        self.assertEqual(self.api(self.outsider).get(f"/api/v1/tickets/{b.pk}/").status_code, 404)
        self.assertEqual(len(self.api(self.pm).get("/api/v1/tickets/").json()["results"]), 2)
        payload = {"workspace": self.ws.pk, "name": "Mobile", "code": "mobile"}
        self.assertEqual(self.api(self.pm).post("/api/v1/ticket-applications/", payload, content_type="application/json").status_code, 403)
        self.assertEqual(self.api(self.agent1).get("/api/v1/ticket-applications/").json()["results"], [])

    def test_owner_manages_applications_and_secret_is_shown_once(self):
        payload = {"workspace": self.ws.pk, "name": "Mobile", "code": "mobile", "teams": [self.support.pk],
                   "webhook_events": ["ticket.created"]}
        res = self.api(self.owner).post("/api/v1/ticket-applications/", payload, content_type="application/json")
        self.assertEqual(res.status_code, 201, res.content)
        secret, app_id = res.json()["secret"], res.json()["id"]
        detail = self.api(self.owner).get(f"/api/v1/ticket-applications/{app_id}/").json()
        self.assertNotIn("secret", detail)
        self.assertNotIn(secret, json.dumps(detail))
        rotated = self.api(self.owner).post(f"/api/v1/ticket-applications/{app_id}/rotate-secret/").json()
        self.assertNotEqual(rotated["secret"], secret)
        bad = dict(payload, code="mobile2", webhook_url="http://10.0.0.1/hook")
        self.assertEqual(self.api(self.owner).post("/api/v1/ticket-applications/", bad, content_type="application/json").status_code, 400)
        foreign = dict(payload, code="x", teams=[], project=None, workspace=self.other_ws.pk)
        self.assertIn(self.api(self.owner).post("/api/v1/ticket-applications/", foreign, content_type="application/json").status_code, (400, 403))

    def test_assignment_notifies_in_realtime_and_dashboard_counts(self):
        self.create()
        t = self.ticket()
        with mock.patch("project.services.realtime.push_to_users") as push, self.captureOnCommitCallbacks(execute=True):
            self.api(self.pm).post(f"/api/v1/tickets/{t.pk}/assign/", {"team": self.support.pk, "assignee": self.agent1.pk},
                                   content_type="application/json")
        self.assertTrue(dm.Notification.objects.filter(recipient=self.agent1, url=f"/tickets/{t.pk}/").exists())
        self.assertTrue(any(call.args[1] == "ticket.changed" for call in push.call_args_list))
        board = self.api(self.pm).get("/api/v1/tickets/dashboard/", {"workspace": self.ws.pk}).json()
        self.assertEqual((board["open"], board["unassigned"]), (1, 0))

    def test_create_linked_task_and_one_way_status_sync(self):
        self.create()
        t = self.ticket()
        svc.assign(t, actor=self.pm, team_id=self.support.pk, assignee_id=self.agent1.pk)
        res = self.api(self.agent1).post(f"/api/v1/tickets/{t.pk}/create-task/", {}, content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content)
        task = dm.Task.objects.get(pk=res.json()["task_id"])
        self.assertEqual((task.project_id, task.assignee_id), (self.project.pk, self.agent1.pk))
        self.assertEqual(self.api(self.agent1).post(f"/api/v1/tickets/{t.pk}/create-task/", {}, content_type="application/json").status_code, 409)
        task.status = dm.Task.Status.DONE
        task.save()
        t.refresh_from_db()
        self.assertEqual(t.status, "RESOLVED")
        task.refresh_from_db()
        self.assertEqual(task.status, dm.Task.Status.DONE)

    def test_internal_attachment_download_is_permission_checked(self):
        self.create()
        t = self.ticket()
        svc.assign(t, actor=self.pm, team_id=self.support.pk, assignee_id=self.agent1.pk)
        client = self.api(self.agent1)
        res = client.post(f"/api/v1/tickets/{t.pk}/comment/", {"body": "Logs serveur", "visibility": "INTERNAL",
                                                               "attachments": SimpleUploadedFile("logs.txt", b"ERROR 500", content_type="text/plain")})
        self.assertEqual(res.status_code, 200, res.content)
        att = t.attachments.get()
        self.assertEqual(att.visibility, "INTERNAL")
        self.assertEqual(client.get(att_url := f"/api/v1/tickets/{t.pk}/attachments/{att.pk}/").status_code, 200)
        self.assertEqual(self.api(self.outsider).get(att_url).status_code, 404)
        self.assertEqual(self.api(self.bob).get(att_url).status_code, 404)
        from project.views_media import user_can_access_media
        self.assertTrue(user_can_access_media(self.agent1, att.file.name))
        self.assertFalse(user_can_access_media(self.outsider, att.file.name))
        self.assertNotIn("ERROR 500", json.dumps(self.signed("GET", f"{URL}EXT-1/").json()))
