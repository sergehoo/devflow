"""
Ticketing multicanal : création manuelle (droits, référence, audit, routage,
affectation, notifications, isolation) et canal e-mail (création, pièces
jointes, accusé de réception, réponses chaînées, expéditeur non autorisé,
doublons, réponses automatiques, échecs SMTP/IMAP, webhook entrant, isolation).

Aucun appel réseau réel : IMAP / SMTP / DNS simulés, e-mails en mémoire.

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_ticketing_channels
"""

import hashlib
import hmac
import imaplib
import json
import smtplib
import time
from datetime import timedelta
from email.message import EmailMessage
from unittest import mock

from django.core import mail as django_mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone

from project import models as dm
from project.services import ticketing as svc
from project.services import ticketing_email as mail
from project.tests_ticketing import PNG, TicketingFixture

M = dm.TicketEmailMessage


def raw_email(*, sender="client@acme.test", to="support@alpha.test", subject="Connexion impossible", body="Je ne peux plus me connecter.",
              html=None, message_id=None, in_reply_to=None, references=None, headers=None, files=()):
    msg = EmailMessage()
    msg["From"] = f"Client Acme <{sender}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = message_id or f"<{time.time_ns()}@acme.test>"
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    for k, v in (headers or {}).items():
        msg[k] = v
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    for name, content, maintype, subtype in files:
        msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=name)
    return msg.as_bytes()


class ChannelFixture(TicketingFixture):
    def setUp(self):
        super().setUp()
        patcher = mock.patch("project.services.ticketing_email._schedule")
        self.mail_schedule = patcher.start()
        self.addCleanup(patcher.stop)

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.rule = dm.TicketRoutingRule.objects.create(workspace=cls.ws, name="Support", team=cls.support, auto_assign=True, position=1)
        cls.mailbox = cls.make_mailbox(cls.ws, cls.app, "support@alpha.test")
        cls.other_mailbox = cls.make_mailbox(cls.other_ws, cls.other_app, "support@beta.test")

    @staticmethod
    def make_mailbox(ws, app, address, **extra):
        box = dm.TicketMailbox(workspace=ws, application=app, name="Support", address=address, inbound_key=mail.new_inbound_key(),
                               inbound=extra.pop("inbound", "WEBHOOK"), **extra)
        mail.set_secret(box, "webhook_secret", "whsec-test")
        box.save()
        return box

    def receive(self, raw, mailbox=None):
        row, created = mail.ingest(mailbox or self.mailbox, raw)
        if created:
            mail.process(row.pk)
        row.refresh_from_db()
        return row


# ─── Création manuelle ───────────────────────────────────────────────────────

class ManualCreationTests(ChannelFixture):
    def test_owner_creates_ticket_with_reference_audit_routing_and_attachment(self):
        upload = SimpleUploadedFile("capture.png", PNG, content_type="image/png")
        res = self.api(self.owner).post("/api/v1/tickets/", {
            "application": self.app.pk, "title": "Export PDF en erreur", "description": "Erreur 500 à l'export.",
            "category": "BUG", "severity": "MAJOR", "attachments": [upload]}, format="multipart")
        self.assertEqual(res.status_code, 201, res.content)
        body = res.json()
        self.assertEqual((body["reference"], body["source"], body["priority"]), ("TCK-00001", "MANUAL", "P2"))
        self.assertEqual(body["created_by"]["id"], self.owner.pk)
        self.assertEqual(body["project"]["id"], self.project.pk)  # projet de l'application par défaut
        self.assertEqual(len(body["attachments"]), 1)
        ticket = dm.Ticket.objects.get(pk=body["id"])
        self.assertEqual(ticket.team, self.support)
        self.assertIn(ticket.assignee, (self.agent1, self.agent2))  # règle de routage avec affectation automatique
        created = ticket.events.get(action="created")
        self.assertEqual((created.origin, created.actor), ("UI", self.owner))
        self.assertTrue(dm.Notification.objects.filter(recipient=ticket.assignee, metadata__ticket_id=ticket.pk).exists())
        second = self.api(self.owner).post("/api/v1/tickets/", {"application": self.app.pk, "title": "Deuxième"}, format="json")
        self.assertEqual(second.json()["reference"], "TCK-00002")

    def test_manual_assignment_requires_assign_right_and_eligible_agent(self):
        payload = {"application": self.app.pk, "title": "Accès refusé", "team": self.support.pk, "assignee": self.agent2.pk}
        res = self.api(self.pm).post("/api/v1/tickets/", payload, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual((res.json()["assignee"]["id"], res.json()["status"]), (self.agent2.pk, "ASSIGNED"))
        self.assertTrue(dm.TicketEvent.objects.filter(ticket_id=res.json()["id"], action="assigned",
                                                      new_value__reason="Affectation à la création").exists())
        self.assertEqual(self.api(self.outsider).post("/api/v1/tickets/", payload, format="json").status_code, 403)
        bad = self.api(self.pm).post("/api/v1/tickets/", {**payload, "assignee": self.outsider.pk}, format="json")
        self.assertEqual(bad.status_code, 400)

    def test_team_queue_notifies_team_agents_in_realtime(self):
        self.rule.auto_assign = False
        self.rule.save()
        with mock.patch("project.services.realtime.push_to_users") as push, self.captureOnCommitCallbacks(execute=True):
            res = self.api(self.owner).post("/api/v1/tickets/", {"application": self.app.pk, "title": "File support"}, format="json")
        ticket = dm.Ticket.objects.get(pk=res.json()["id"])
        self.assertEqual((ticket.team, ticket.assignee, ticket.status), (self.support, None, "QUALIFIED"))
        notified = set(dm.Notification.objects.filter(metadata__ticket_id=ticket.pk).values_list("recipient_id", flat=True))
        self.assertTrue({self.agent1.pk, self.agent2.pk, self.pm.pk} <= notified)
        self.assertTrue(any(call.args[1] == "ticket.changed" for call in push.call_args_list))

    def test_member_creates_and_follows_own_ticket_but_cannot_force_priority(self):
        self.rule.delete()
        res = self.api(self.outsider).post("/api/v1/tickets/", {"application": self.app.pk, "title": "Bug saisie"}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        detail = self.api(self.outsider).get(f"/api/v1/tickets/{res.json()['id']}/")
        self.assertEqual(detail.status_code, 200)
        self.assertTrue(detail.json()["rights"]["reply"])
        comment = self.api(self.outsider).post(f"/api/v1/tickets/{res.json()['id']}/comment/", {"body": "Précision"}, format="json")
        self.assertEqual(comment.status_code, 200, comment.content)
        forced = self.api(self.outsider).post("/api/v1/tickets/", {"application": self.app.pk, "title": "Urgent", "priority": "P1"}, format="json")
        self.assertEqual(forced.status_code, 403)
        options = self.api(self.outsider).get("/api/v1/tickets/create-options/", {"workspace": self.ws.pk}).json()
        self.assertEqual((options["can_assign"], options["can_set_priority"]), (False, False))
        self.assertEqual([a["id"] for a in options["applications"]], [self.app.pk])

    def test_validation_and_workspace_isolation(self):
        api = self.api(self.owner)
        self.assertEqual(api.post("/api/v1/tickets/", {"application": self.app.pk, "title": "x"}, format="json").status_code, 400)
        self.assertEqual(api.post("/api/v1/tickets/", {"application": self.other_app.pk, "title": "Fuite"}, format="json").status_code, 400)
        foreign_team = dm.Team.objects.create(workspace=self.other_ws, name="Beta team")
        res = api.post("/api/v1/tickets/", {"application": self.app.pk, "title": "Équipe étrangère", "team": foreign_team.pk}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(api.get("/api/v1/tickets/create-options/", {"workspace": self.other_ws.pk}).status_code, 404)
        self.assertEqual(api.get("/api/v1/tickets/agents/", {"team": foreign_team.pk}).status_code, 404)
        created = api.post("/api/v1/tickets/", {"application": self.app.pk, "title": "Interne"}, format="json").json()
        self.assertEqual(self.api(self.bob).get(f"/api/v1/tickets/{created['id']}/").status_code, 404)
        self.assertEqual(dm.Ticket.objects.filter(workspace=self.other_ws).count(), 0)


# ─── Canal e-mail ────────────────────────────────────────────────────────────

class EmailInboundTests(ChannelFixture):
    def test_new_email_creates_ticket_with_attachments_sla_and_acknowledgement(self):
        raw = raw_email(html="<p>Bonjour,<br>je ne peux plus <b>me connecter</b>.</p><script>alert(1)</script>",
                        files=[("capture.png", PNG, "image", "png"), ("virus.exe", b"MZ\x90\x00", "application", "octet-stream")])
        row = self.receive(raw)
        self.assertEqual((row.status, row.kind), ("PROCESSED", "NEW_TICKET"))
        ticket = row.ticket
        self.assertEqual((ticket.source, ticket.mailbox, ticket.application), ("EMAIL", self.mailbox, self.app))
        self.assertEqual((ticket.reporter_email, ticket.title, ticket.reference), ("client@acme.test", "Connexion impossible", "TCK-00001"))
        self.assertEqual(ticket.team, self.support)
        self.assertIsNotNone(ticket.resolution_due)
        self.assertEqual([a.original_name for a in ticket.attachments.all()], ["capture.png"])
        self.assertEqual(ticket.metadata["email"]["skipped_attachments"], ["virus.exe"])
        self.assertEqual(ticket.events.get(action="created").origin, "EMAIL")
        ack = M.objects.get(direction="OUT", kind="ACK", ticket=ticket)
        self.assertEqual((ack.status, ack.to_addresses, ack.in_reply_to), ("PENDING", "client@acme.test", row.message_id))
        self.assertEqual(mail.send(ack.pk), "sent")
        sent = django_mail.outbox[-1]
        self.assertEqual(sent.subject, "[TCK-00001] Connexion impossible")
        self.assertEqual(sent.extra_headers["Auto-Submitted"], "auto-replied")
        self.assertIn(f"tck.{ticket.pk}.{mail.thread_token(ticket.pk)}.", sent.extra_headers["Message-ID"])
        self.assertEqual(sent.reply_to, ["support@alpha.test"])

    def test_html_only_email_is_converted_to_plain_text(self):
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"], msg["Message-ID"] = "c@acme.test", "support@alpha.test", "HTML", "<h1@acme.test>"
        msg.set_content("<div>Ligne 1</div><div>Ligne &amp; 2</div><style>p{}</style><script>x()</script>", subtype="html")
        ticket = self.receive(msg.as_bytes()).ticket
        self.assertEqual(ticket.description, "Ligne 1\nLigne & 2")

    def test_reply_chain_by_headers_and_agent_reply_by_email(self):
        first = self.receive(raw_email())
        ticket = first.ticket
        ack = M.objects.get(kind="ACK", ticket=ticket)
        reply = self.receive(raw_email(subject="Re: [TCK-00001] Connexion impossible", in_reply_to=ack.message_id,
                                       references=f"{first.message_id} {ack.message_id}",
                                       body="Toujours bloqué.\n\nLe 10 nov. 2026, Support a écrit :\n> Nous avons bien reçu"))
        self.assertEqual((reply.status, reply.kind, reply.ticket), ("PROCESSED", "REPLY", ticket))
        self.assertEqual((reply.comment.body, reply.comment.visibility, reply.comment.author_id), ("Toujours bloqué.", "PUBLIC", None))
        agent = ticket.assignee
        res = self.api(agent).post(f"/api/v1/tickets/{ticket.pk}/comment/", {"body": "Réinitialisez votre mot de passe."}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        out = M.objects.get(kind="AGENT_REPLY", ticket=ticket)
        self.assertEqual((out.status, out.in_reply_to), ("PENDING", reply.message_id))
        mail.send(out.pk)
        sent = django_mail.outbox[-1]
        self.assertEqual(sent.subject, "Re: [TCK-00001] Connexion impossible")
        self.assertIn(first.message_id, sent.extra_headers["References"])
        statuses = {e["kind"]: e["status"] for e in res.json()["emails"]}
        self.assertEqual(statuses["REPLY"], "PROCESSED")
        # Réponse suivante du client sur le message de l'agent (jeton signé)
        again = self.receive(raw_email(in_reply_to=out.message_id, body="Merci, c'est réglé."))
        self.assertEqual(again.ticket, ticket)
        # Note interne : jamais envoyée par e-mail
        self.api(agent).post(f"/api/v1/tickets/{ticket.pk}/comment/", {"body": "Note privée", "visibility": "INTERNAL"}, format="json")
        self.assertEqual(M.objects.filter(kind="AGENT_REPLY", ticket=ticket).count(), 1)

    def test_agent_email_reply_stays_internal(self):
        first = self.receive(raw_email())
        ticket = first.ticket
        ack = M.objects.get(kind="ACK", ticket=ticket)
        agent = ticket.assignee
        row = self.receive(raw_email(sender=agent.email, in_reply_to=ack.message_id, body="Vu côté serveur : session expirée."))
        self.assertEqual((row.status, row.comment.visibility, row.comment.author), ("PROCESSED", "INTERNAL", agent))

    def test_unauthorized_sender_and_subject_reference_alone_are_rejected(self):
        first = self.receive(raw_email())
        ticket = first.ticket
        ack = M.objects.get(kind="ACK", ticket=ticket)
        stranger = self.receive(raw_email(sender="intrus@evil.test", in_reply_to=ack.message_id, body="Je prends la main."))
        self.assertEqual(stranger.status, "REJECTED")
        self.assertIn("non autorisé", stranger.reason)
        subject_only = self.receive(raw_email(sender="intrus@evil.test", subject="Re: [TCK-00001] Connexion impossible", body="x"))
        self.assertEqual(subject_only.status, "REJECTED")
        self.assertIn("sans en-tête", subject_only.reason)
        self.assertEqual(ticket.comments.count(), 0)
        self.assertEqual(dm.Ticket.objects.count(), 1)
        # Référence + expéditeur déclarant (client sans en-têtes de réponse) : rattaché
        legit = self.receive(raw_email(subject="[TCK-00001] complément", body="Capture en pièce jointe."))
        self.assertEqual((legit.status, legit.ticket), ("PROCESSED", ticket))

    def test_duplicate_message_is_processed_once(self):
        raw = raw_email(message_id="<dup-1@acme.test>")
        first, created = mail.ingest(self.mailbox, raw)
        second, created_again = mail.ingest(self.mailbox, raw)
        self.assertEqual((first.pk, created, created_again), (second.pk, True, False))
        self.assertEqual(mail.process(first.pk), "processed")
        self.assertEqual(mail.process(first.pk), "skip")
        self.assertEqual(dm.Ticket.objects.count(), 1)

    def test_auto_replies_bounces_lists_and_loops_never_create_tickets(self):
        cases = [
            {"headers": {"Auto-Submitted": "auto-replied"}},
            {"subject": "Réponse automatique : absent"},
            {"headers": {"Precedence": "bulk"}},
            {"headers": {"List-Id": "<news.acme.test>"}},
            {"sender": "mailer-daemon@acme.test"},
            {"sender": "support@alpha.test"},
            {"headers": {"X-DevFlow-Loop": "support@alpha.test"}},
        ]
        for case in cases:
            row = self.receive(raw_email(**case))
            self.assertEqual(row.status, "IGNORED", case)
        self.assertEqual(dm.Ticket.objects.count(), 0)
        self.assertFalse(M.objects.filter(direction="OUT").exists())

    def test_spam_blocked_senders_domains_and_rate_limit(self):
        self.assertEqual(self.receive(raw_email(headers={"X-Spam-Flag": "YES"})).status, "REJECTED")
        self.mailbox.blocked_senders = ["evil.test"]
        self.mailbox.allowed_domains = ["acme.test"]
        self.mailbox.save()
        self.assertEqual(self.receive(raw_email(sender="x@evil.test")).status, "REJECTED")
        self.assertEqual(self.receive(raw_email(sender="x@other.test")).status, "REJECTED")
        for i in range(mail.NEW_TICKETS_PER_SENDER_PER_HOUR):
            self.assertEqual(self.receive(raw_email(subject=f"Demande {i}")).status, "PROCESSED")
        flood = self.receive(raw_email(subject="Encore"))
        self.assertEqual(flood.status, "REJECTED")
        acks = M.objects.filter(direction="OUT", kind="ACK").count()
        self.assertEqual(acks, mail.ACKS_PER_SENDER_PER_HOUR)  # anti ping-pong des accusés

    def test_reply_to_closed_ticket_opens_a_follow_up(self):
        first = self.receive(raw_email())
        dm.Ticket.objects.filter(pk=first.ticket_id).update(status="CLOSED")
        ack = M.objects.get(kind="ACK", ticket_id=first.ticket_id)
        row = self.receive(raw_email(in_reply_to=ack.message_id, body="Le problème revient."))
        self.assertEqual(row.kind, "NEW_TICKET")
        self.assertNotEqual(row.ticket_id, first.ticket_id)
        self.assertIn("Suite du ticket TCK-00001", row.ticket.description)

    def test_workspace_isolation_of_conversation_tokens(self):
        foreign = svc.create_manual(self.bob, {"application": self.other_app, "title": "Ticket Beta"})
        token_id = f"<tck.{foreign.pk}.{mail.thread_token(foreign.pk)}.abcd@beta.test>"
        row = self.receive(raw_email(in_reply_to=token_id, body="Tentative"))
        self.assertNotEqual(row.ticket_id, foreign.pk)
        self.assertEqual(row.ticket.workspace, self.ws)
        self.assertEqual(foreign.comments.count(), 0)

    def test_processing_failure_rolls_back_and_retries_then_gives_up(self):
        row, _ = mail.ingest(self.mailbox, raw_email())
        with mock.patch("project.services.ticketing._create", side_effect=RuntimeError("db down")):
            self.assertEqual(mail.process(row.pk), "failed")
            row.refresh_from_db()
            self.assertEqual((row.attempt, row.status), (1, "FAILED"))
            for _ in range(mail.MAX_ATTEMPTS - 1):
                mail.process(row.pk)
        row.refresh_from_db()
        self.assertEqual(row.status, "DEAD")
        self.assertEqual(dm.Ticket.objects.count(), 0)
        mail.reprocess(row)
        self.assertEqual(mail.process(row.pk), "processed")
        self.assertEqual(dm.Ticket.objects.count(), 1)


class EmailOutboundTests(ChannelFixture):
    def test_smtp_failures_retry_with_backoff_then_dead_without_leaking_password(self):
        self.mailbox.smtp_host, self.mailbox.smtp_username = "smtp.alpha.test", "support@alpha.test"
        mail.set_secret(self.mailbox, "smtp_password", "S3cr3t-pass")
        self.mailbox.save()
        ticket = self.receive(raw_email()).ticket
        ack = M.objects.get(kind="ACK", ticket=ticket)
        with mock.patch.object(mail, "smtp_connection", side_effect=OSError("connexion refusée S3cr3t-pass")):
            self.assertEqual(mail.send(ack.pk), "failed")
            ack.refresh_from_db()
            self.assertAlmostEqual((ack.next_attempt_at - timezone.now()).total_seconds(), 60, delta=5)
            self.assertNotIn("S3cr3t-pass", ack.reason)
            for _ in range(mail.MAX_ATTEMPTS - 1):
                mail.send(ack.pk)
        ack.refresh_from_db()
        self.assertEqual(ack.status, "DEAD")
        self.assertTrue(ticket.events.filter(action="email_failed").exists())

    def test_authentication_error_is_permanent(self):
        ticket = self.receive(raw_email()).ticket
        ack = M.objects.get(kind="ACK", ticket=ticket)
        with mock.patch.object(mail, "smtp_connection", side_effect=smtplib.SMTPAuthenticationError(535, b"bad credentials")):
            self.assertEqual(mail.send(ack.pk), "dead")

    def test_header_injection_is_neutralized(self):
        folded = raw_email(subject="PLACEHOLDER").replace(b"Subject: PLACEHOLDER", b"Subject: Bonjour\n Bcc: victime@evil.test")
        ticket = self.receive(folded).ticket
        dm.Ticket.objects.filter(pk=ticket.pk).update(title="Bonjour\r\nBcc: victime@evil.test")
        ticket.refresh_from_db()
        ack = mail.queue_ack(ticket, M.objects.get(direction="IN", ticket=ticket))
        self.assertEqual(mail.send(ack.pk), "sent")
        headers = django_mail.outbox[-1].message()
        self.assertEqual(headers.get_all("Bcc"), None)
        self.assertNotIn("\n", headers["Subject"])


class FakeImap:
    """IMAP minimal simulé : 2 messages, UIDVALIDITY 7."""

    instances = []

    def __init__(self, host, port, ssl_context=None, timeout=None):
        self.store = {1: raw_email(message_id="<imap-1@acme.test>", subject="Un"),
                      2: raw_email(message_id="<imap-2@acme.test>", subject="Deux")}
        self.untagged_responses = {}
        self.flags = []
        FakeImap.instances.append(self)

    def login(self, user, password):
        if password != "imap-pass":
            raise imaplib.IMAP4.error(f"[AUTHENTICATIONFAILED] invalid {password}")

    def select(self, folder, readonly=False):
        self.untagged_responses["UIDVALIDITY"] = [b"7"]
        return "OK", [b"2"]

    def uid(self, command, *args):
        if command == "SEARCH":
            low = int(args[1].split()[1].split(":")[0])
            return "OK", [" ".join(str(u) for u in self.store if u >= low).encode()]
        if command == "FETCH":
            uid, what = int(args[0]), args[1]
            if what == "(RFC822.SIZE)":
                return "OK", [f"1 (UID {uid} RFC822.SIZE {len(self.store[uid])})".encode()]
            return "OK", [(f"1 (UID {uid} BODY[] {{{len(self.store[uid])}}}".encode(), self.store[uid]), b")"]
        if command == "STORE":
            self.flags.append(int(args[0]))
            return "OK", []
        raise AssertionError(command)

    def logout(self):
        return "BYE", []


@override_settings(TICKET_MAIL_ALLOW_PRIVATE_HOSTS=True)
class ImapTests(ChannelFixture):
    def setUp(self):
        super().setUp()
        FakeImap.instances = []
        self.box = self.make_mailbox(self.ws, self.app, "imap@alpha.test", inbound="IMAP", imap_host="imap.alpha.test",
                                     imap_username="imap@alpha.test")
        mail.set_secret(self.box, "imap_password", "imap-pass")
        self.box.save()

    def test_poll_stores_messages_then_advances_and_is_idempotent(self):
        with mock.patch("imaplib.IMAP4_SSL", FakeImap):
            stats = mail.poll(self.box)
            self.box.refresh_from_db()
            self.assertEqual((stats["fetched"], stats["new"], self.box.last_uid, self.box.uid_validity), (2, 2, 2, 7))
            self.assertEqual(FakeImap.instances[0].flags, [1, 2])  # \Seen seulement après stockage
            self.assertEqual(M.objects.filter(mailbox=self.box, status="RECEIVED").count(), 2)
            self.assertEqual(mail.poll(self.box)["fetched"], 0)
        self.assertIsNotNone(self.box.last_success_at)
        self.assertEqual(self.mail_schedule.call_count, 0)  # traitement planifié après commit (hors test)

    def test_poll_failures_are_sanitized_backed_off_and_alerted(self):
        mail.set_secret(self.box, "imap_password", "wrong-pass")
        self.box.save()
        with mock.patch("imaplib.IMAP4_SSL", FakeImap):
            for _ in range(mail.ALERT_AFTER_FAILURES):
                mail.poll(self.box)
                self.box.refresh_from_db()
        self.assertEqual(self.box.consecutive_failures, mail.ALERT_AFTER_FAILURES)
        self.assertNotIn("wrong-pass", self.box.last_error)
        self.assertGreater(self.box.next_poll_at, timezone.now())
        self.assertIsNotNone(self.box.alert_sent_at)
        self.assertTrue(dm.Notification.objects.filter(recipient=self.owner, metadata__kind="ticket_mailbox").exists())
        mail.set_secret(self.box, "imap_password", "imap-pass")
        self.box.save()
        with mock.patch("imaplib.IMAP4_SSL", FakeImap):
            mail.poll(self.box)
        self.box.refresh_from_db()
        self.assertEqual((self.box.consecutive_failures, self.box.alert_sent_at), (0, None))

    def test_private_hosts_are_refused_by_default(self):
        with override_settings(TICKET_MAIL_ALLOW_PRIVATE_HOSTS=False), \
                mock.patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("10.0.0.8", 993))]), \
                mock.patch("imaplib.IMAP4_SSL", FakeImap):
            result = mail.test_connection(self.box)
        self.assertFalse(result["imap"]["ok"])
        self.assertIn("interdit", result["imap"]["detail"])
        self.assertEqual(FakeImap.instances, [])


class MailboxApiTests(ChannelFixture):
    def test_admin_configures_mailbox_and_secrets_are_never_returned(self):
        payload = {"workspace": self.ws.pk, "application": self.app.pk, "name": "Support client", "address": "Help@Alpha.test",
                   "inbound": "IMAP", "imap_host": "imap.alpha.test", "imap_username": "help", "imap_password": "imap-pass",
                   "allowed_domains": ["acme.test"]}
        res = self.api(self.owner).post("/api/v1/ticket-mailboxes/", json.dumps(payload), content_type="application/json")
        self.assertEqual(res.status_code, 201, res.content)
        body = res.json()
        self.assertNotIn("imap_password", body)
        self.assertNotIn("imap-pass", res.content.decode())
        self.assertTrue(body["has_imap_password"])
        self.assertEqual(body["address"], "help@alpha.test")
        box = dm.TicketMailbox.objects.get(pk=body["id"])
        self.assertNotIn("imap-pass", box.imap_password_encrypted)
        self.assertEqual(mail.get_secret(box, "imap_password"), "imap-pass")
        listing = self.api(self.owner).get("/api/v1/ticket-mailboxes/", {"workspace": self.ws.pk}).content.decode()
        self.assertNotIn("imap-pass", listing)
        self.assertNotIn("whsec-test", listing)
        with mock.patch.object(mail, "test_connection", return_value={"imap": {"ok": True, "detail": "OK"}, "smtp": None}):
            self.assertEqual(self.api(self.owner).post(f"/api/v1/ticket-mailboxes/{box.pk}/test/").json()["imap"]["ok"], True)
        missing = self.api(self.owner).post("/api/v1/ticket-mailboxes/", json.dumps({**payload, "address": "x@alpha.test", "imap_password": ""}),
                                            content_type="application/json")
        self.assertEqual(missing.status_code, 400)

    def test_non_admins_and_other_tenants_cannot_reach_mailboxes(self):
        self.assertEqual(self.api(self.pm).get("/api/v1/ticket-mailboxes/").json()["count"], 0)
        self.assertEqual(self.api(self.pm).get(f"/api/v1/ticket-mailboxes/{self.mailbox.pk}/").status_code, 404)
        res = self.api(self.pm).post("/api/v1/ticket-mailboxes/", {"workspace": self.ws.pk, "application": self.app.pk, "name": "X",
                                                                  "address": "x@alpha.test", "inbound": "WEBHOOK"}, format="json")
        self.assertEqual(res.status_code, 403)
        self.assertEqual(self.api(self.bob).get(f"/api/v1/ticket-mailboxes/{self.mailbox.pk}/messages/").status_code, 404)
        foreign = self.api(self.owner).post("/api/v1/ticket-mailboxes/", {"workspace": self.ws.pk, "application": self.other_app.pk,
                                                                         "name": "X", "address": "y@alpha.test", "inbound": "WEBHOOK"}, format="json")
        self.assertEqual(foreign.status_code, 400)

    def test_message_history_and_reprocess_queue(self):
        rejected = self.receive(raw_email(headers={"X-Spam-Flag": "YES"}))
        history = self.api(self.owner).get(f"/api/v1/ticket-mailboxes/{self.mailbox.pk}/messages/", {"status": "REJECTED"}).json()
        self.assertEqual([m["id"] for m in history["results"]], [rejected.pk])
        self.assertTrue(history["results"][0]["can_reprocess"])
        res = self.api(self.owner).post(f"/api/v1/ticket-mailboxes/{self.mailbox.pk}/messages/{rejected.pk}/reprocess/")
        self.assertEqual(res.status_code, 200)
        rejected.refresh_from_db()
        self.assertEqual(rejected.status, "RECEIVED")


class InboundWebhookTests(ChannelFixture):
    def post(self, body, secret="whsec-test", ts=None, key=None):
        ts = str(ts or int(time.time()))
        sig = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
        return self.client.post(f"/api/v1/integrations/mail/{key or self.mailbox.inbound_key}/", data=body,
                                content_type="message/rfc822", HTTP_X_DEVFLOW_TIMESTAMP=ts, HTTP_X_DEVFLOW_SIGNATURE=f"sha256={sig}")

    def test_signed_raw_message_is_accepted_once(self):
        body = raw_email(message_id="<hook-1@acme.test>")
        res = self.post(body)
        self.assertEqual(res.status_code, 202, res.content)
        self.assertFalse(res.json()["duplicate"])
        self.assertEqual(M.objects.filter(mailbox=self.mailbox, message_id="<hook-1@acme.test>").count(), 1)
        self.assertEqual(self.post(body).status_code, 401)  # même signature : rejeu
        self.assertTrue(self.post(body, ts=int(time.time()) - 1).json()["duplicate"])

    def test_invalid_signature_stale_timestamp_and_unknown_key(self):
        body = raw_email()
        self.assertEqual(self.post(body, secret="wrong").status_code, 401)
        self.assertEqual(self.post(body, ts=int(time.time()) - 3600).status_code, 401)
        self.assertEqual(self.post(body, key="mbx_unknown").status_code, 404)
        self.mailbox.is_active = False
        self.mailbox.save()
        self.assertEqual(self.post(body).status_code, 404)
        self.assertFalse(M.objects.exists())
