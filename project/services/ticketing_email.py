"""
Ticketing — canal e-mail (réception IMAP / webhook fournisseur, envoi SMTP).

Entrant : ``ingest`` stocke durablement le message brut (dédupliqué par boîte
+ Message-ID) AVANT tout traitement ; ``process`` est asynchrone (Celery),
idempotent et rejouable : nouveau ticket, réponse rattachée, ou file de rejet.
Le rattachement à un ticket repose sur un jeton signé (Message-ID DevFlow) ou
un Message-ID connu de la boîte ; la référence dans l'objet n'est jamais
suffisante seule (l'expéditeur doit être le déclarant du ticket).

Sortant : accusés de réception et réponses d'agents journalisés
(``TicketEmailMessage`` OUT), envoyés après ``commit`` avec retry + backoff.

Sécurité : TLS obligatoire (SSL ou STARTTLS, certificat vérifié), identifiants
chiffrés (Fernet) jamais renvoyés au frontend ni journalisés, hôtes privés
refusés (SSRF), HTML converti en texte, pièces jointes filtrées (types, contenu,
taille), réponses automatiques et boucles ignorées, anti-spam par expéditeur.
"""

from __future__ import annotations

import email
import email.policy
import hashlib
import hmac
import html
import imaplib
import ipaddress
import logging
import mimetypes
import re
import secrets
import smtplib
import socket
import ssl
from datetime import timedelta
from email.utils import formataddr, getaddresses, parseaddr

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.utils import timezone

from project import models as dm
from project.services import ticketing as svc

logger = logging.getLogger("devflow.ticketing.email")

M = dm.TicketEmailMessage
MS, MK = M.Status, M.Kind
BACKOFF_SECONDS = [60, 300, 1800, 7200]  # 1 min, 5 min, 30 min, 2 h
MAX_ATTEMPTS = len(BACKOFF_SECONDS) + 1
IMAP_BATCH = 50
MAX_FILES = 10
NEW_TICKETS_PER_SENDER_PER_HOUR = 10
ACKS_PER_SENDER_PER_HOUR = 5
ALERT_AFTER_FAILURES = 3
DANGEROUS_EXT = {
    ".exe", ".bat", ".cmd", ".com", ".scr", ".pif", ".js", ".jse", ".vbs", ".vbe", ".wsf", ".jar", ".msi", ".ps1",
    ".sh", ".hta", ".lnk", ".iso", ".img", ".dll", ".apk", ".html", ".htm", ".svg", ".xhtml", ".reg", ".cpl",
}
AUTO_LOCALPARTS = {"mailer-daemon", "postmaster", "noreply", "no-reply", "donotreply", "do-not-reply", "bounce", "bounces"}
REF_RE = re.compile(r"\[(TCK-\d{5,})\]")
MSGID_RE = re.compile(r"<[^<>\s]{1,250}>")
TOKEN_RE = re.compile(r"tck\.(\d+)\.([0-9a-f]{20})\.")
AUTO_SUBJECT = re.compile(r"(?i)^\s*(?:réponse automatique|automatic reply|auto(?:matic)?[ -]?reply|out of (?:the )?office|absence)\b")


class TemporaryMailError(Exception):
    """Erreur passagère (réseau, serveur) : nouvel essai avec backoff."""


def max_raw_bytes() -> int:
    return int(getattr(settings, "TICKET_MAIL_MAX_MB", 25)) * 1024 * 1024


# ─── Secrets ─────────────────────────────────────────────────────────────────

SECRET_FIELDS = {"imap_password": "imap_password_encrypted", "smtp_password": "smtp_password_encrypted",
                 "webhook_secret": "webhook_secret_encrypted"}


def set_secret(mailbox: dm.TicketMailbox, name: str, value: str) -> None:
    setattr(mailbox, SECRET_FIELDS[name], svc._fernet().encrypt(value.encode()).decode() if value else "")


def get_secret(mailbox: dm.TicketMailbox, name: str) -> str:
    token = getattr(mailbox, SECRET_FIELDS[name])
    return svc._fernet().decrypt(token.encode()).decode() if token else ""


def new_inbound_key() -> str:
    return f"mbx_{secrets.token_hex(12)}"


def rotate_webhook_secret(mailbox: dm.TicketMailbox) -> str:
    secret = f"dfm_{secrets.token_urlsafe(32)}"
    set_secret(mailbox, "webhook_secret", secret)
    mailbox.save(update_fields=["webhook_secret_encrypted", "updated_at"])
    return secret


def safe_error(exc: Exception, mailbox: dm.TicketMailbox | None = None) -> str:
    """Message d'erreur journalisable : type + texte borné, mots de passe masqués."""
    text = f"{type(exc).__name__}: {exc}"
    if mailbox is not None:
        for name in ("imap_password", "smtp_password"):
            try:
                secret = get_secret(mailbox, name)
            except Exception:
                secret = ""
            if secret:
                text = text.replace(secret, "***")
    return text.replace("\r", " ").replace("\n", " ")[:300]


def check_host(host: str, port: int) -> None:
    """Hôte de messagerie public uniquement (protection SSRF), sauf autorisation explicite."""
    if not host or not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", host):
        raise TemporaryMailError("Nom d'hôte invalide.")
    if getattr(settings, "TICKET_MAIL_ALLOW_PRIVATE_HOSTS", False):
        return
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise TemporaryMailError(f"Hôte introuvable : {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise ValueError("Serveur de messagerie interdit (adresse privée ou locale).")


# ─── Jeton de conversation ───────────────────────────────────────────────────

def thread_token(ticket_id: int) -> str:
    material = getattr(settings, "TICKETING_ENCRYPTION_KEY", "") or settings.SECRET_KEY
    key = hashlib.sha256(f"devflow-ticket-thread:{material}".encode()).digest()
    return hmac.new(key, str(ticket_id).encode(), hashlib.sha256).hexdigest()[:20]


def make_message_id(ticket: dm.Ticket | None, mailbox: dm.TicketMailbox) -> str:
    domain = mailbox.address.rsplit("@", 1)[-1]
    prefix = f"tck.{ticket.pk}.{thread_token(ticket.pk)}." if ticket else "devflow."
    return f"<{prefix}{secrets.token_hex(8)}@{domain}>"


def ticket_from_tokens(text: str, workspace_id: int) -> dm.Ticket | None:
    for match in TOKEN_RE.finditer(text or ""):
        ticket_id, token = int(match[1]), match[2]
        if hmac.compare_digest(token, thread_token(ticket_id)):
            ticket = dm.Ticket.objects.filter(pk=ticket_id, workspace_id=workspace_id).first()
            if ticket:
                return ticket
    return None


# ─── Analyse et nettoyage ────────────────────────────────────────────────────

def one_line(value, limit: int = 255) -> str:
    """En-tête sur une ligne (aucune injection CR/LF), borné."""
    return re.sub(r"[\r\n\t]+", " ", str(value or "")).strip()[:limit]


def parse(raw: bytes):
    return email.message_from_bytes(raw, policy=email.policy.default)


def normalize_message_id(value: str, raw: bytes = b"") -> str:
    found = MSGID_RE.search(str(value or ""))
    if found:
        return found[0][:255]
    return f"<sha256.{hashlib.sha256(raw).hexdigest()[:40]}@devflow.local>"


def sender_of(msg) -> tuple[str, str]:
    """Expéditeur (From) : identité utilisée pour les autorisations et les réponses."""
    name, addr = parseaddr(str(msg.get("From") or ""))
    addr = (addr or "").strip().lower()
    try:
        validate_email(addr)
    except ValidationError:
        addr = ""
    return one_line(name, 150), addr


BLOCK_TAGS = re.compile(r"(?i)<\s*(br|/p|/div|/li|/tr|/h[1-6]|/blockquote)\b[^>]*>")
DROP_BLOCKS = re.compile(r"(?is)<(script|style|head|title)\b.*?</\1\s*>")
TAG = re.compile(r"(?s)<[^>]+>")


def html_to_text(value: str) -> str:
    """HTML entrant → texte brut (aucune balise conservée : rendu sans risque XSS)."""
    text = DROP_BLOCKS.sub(" ", value or "")
    text = re.sub(r"(?is)<blockquote\b.*?</blockquote\s*>", "\n", text)  # citations Outlook / Gmail
    text = BLOCK_TAGS.sub("\n", text)
    text = re.sub(r"(?i)<li\b[^>]*>", "\n• ", text)
    text = html.unescape(TAG.sub("", text)).replace("\xa0", " ")
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


QUOTE_HEADERS = re.compile(
    r"(?im)^(?:>?\s*)(?:le .{3,120} a écrit\s*:|on .{3,160} wrote\s*:|-{2,}\s*(?:original message|message d'origine|message transféré)"
    r"|de\s*:\s.+\n(?:.*\n){0,3}?\s*(?:envoyé|date)\s*:|from\s*:\s.+\n(?:.*\n){0,3}?\s*(?:sent|date)\s*:)")
SIGNATURE = re.compile(r"(?m)^(?:-- ?$|envoyé de mon (?:iphone|ipad|android|mobile)|sent from my (?:iphone|ipad|android|mobile)|"
                       r"get outlook for (?:ios|android))", re.I)


def clean_text(text: str, *, strip_quotes: bool) -> str:
    """Retire la signature (et, pour une réponse, l'historique cité)."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if strip_quotes:
        cut = QUOTE_HEADERS.search(text)
        if cut:
            text = text[:cut.start()]
        text = "\n".join(line for line in text.split("\n") if not line.lstrip().startswith(">"))
    sig = SIGNATURE.search(text)
    if sig:
        text = text[:sig.start()]
    return re.sub(r"\n{3,}", "\n\n", text).strip()[:20_000]


def body_text(msg) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        content = part.get_content()
    except (LookupError, UnicodeDecodeError, AssertionError):
        payload = part.get_payload(decode=True) or b""
        content = payload.decode("utf-8", errors="replace")
    if not isinstance(content, str):
        return ""
    return html_to_text(content) if part.get_content_type() == "text/html" else content


def attachments(msg, max_mb: int) -> tuple[list, list[str]]:
    """Pièces jointes acceptées (types sûrs, contenu cohérent, taille) et noms des pièces refusées."""
    kept, skipped = [], []
    for part in msg.iter_attachments():
        name = one_line(part.get_filename() or "piece-jointe", 200) or "piece-jointe"
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        if part.get_content_disposition() == "inline" and len(payload) < 10 * 1024 and part.get_content_maintype() == "image":
            continue  # logos de signature
        ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
        mime = part.get_content_type().lower()
        if mime == "application/octet-stream":
            mime = (mimetypes.guess_type(name)[0] or mime).lower()
        if ext in DANGEROUS_EXT or len(kept) >= MAX_FILES:
            skipped.append(name)
            continue
        upload = SimpleUploadedFile(name, payload, content_type=mime)
        try:
            svc.validate_upload(upload, max_mb)
        except svc.TicketError:
            skipped.append(name)
            continue
        kept.append(upload)
    return kept, skipped


def auto_reason(msg, mailbox: dm.TicketMailbox, sender: str) -> str:
    """Réponses automatiques, rebonds, listes de diffusion et boucles : jamais de ticket ni d'accusé."""
    auto = str(msg.get("Auto-Submitted") or "").strip().lower()
    if auto and auto != "no":
        return "Réponse automatique (Auto-Submitted)."
    if msg.get("X-Autoreply") or msg.get("X-Autorespond") or AUTO_SUBJECT.match(str(msg.get("Subject") or "")):
        return "Réponse automatique."
    if str(msg.get("Precedence") or "").strip().lower() in {"bulk", "junk", "list", "auto_reply"}:
        return "Message de masse ou automatique (Precedence)."
    if msg.get("List-Id") or msg.get("List-Unsubscribe"):
        return "Liste de diffusion."
    if str(msg.get("Return-Path") or "").strip() == "<>" or msg.get_content_type() == "multipart/report":
        return "Rapport de non-remise (rebond)."
    if msg.get("X-DevFlow-Loop"):
        return "Boucle : message émis par DevFlow."
    if sender.split("@", 1)[0] in AUTO_LOCALPARTS:
        return "Expéditeur automatique."
    if sender == mailbox.address.lower():
        return "Boucle : message émis par la boîte de support."
    return ""


def _domain_matches(sender: str, patterns) -> bool:
    domain = sender.rsplit("@", 1)[-1]
    for raw in patterns or []:
        p = str(raw).strip().lower().lstrip("@")
        if p and (sender == p or domain == p or domain.endswith("." + p)):
            return True
    return False


def spam_reason(msg, mailbox: dm.TicketMailbox, sender: str) -> str:
    if str(msg.get("X-Spam-Flag") or "").strip().upper() == "YES" or str(msg.get("X-Spam-Status") or "").lower().startswith("yes"):
        return "Message marqué comme indésirable (spam)."
    if _domain_matches(sender, mailbox.blocked_senders):
        return "Expéditeur bloqué."
    return ""


# ─── Réception : stockage durable puis traitement asynchrone ─────────────────

def _schedule(task_name: str, pk: int, countdown: int = 0) -> None:
    try:
        from project import tasks

        getattr(tasks, task_name).apply_async(args=[pk], countdown=countdown)
    except Exception:  # broker indisponible : le balayage périodique reprend
        logger.warning("ticket mail %s %s non planifié (broker indisponible)", task_name, pk, exc_info=True)


def ingest(mailbox: dm.TicketMailbox, raw: bytes, *, fallback_id: str = "", size: int | None = None) -> tuple[dm.TicketEmailMessage, bool]:
    """
    Enregistre le message brut (idempotent). Renvoie (message, nouveau).
    ``size`` : taille annoncée par le serveur quand seuls les en-têtes ont été lus
    (message trop volumineux, rejeté sans téléchargement).
    """
    size = len(raw) if size is None else size
    msg = parse(raw if size <= max_raw_bytes() else raw[:256 * 1024])
    message_id = normalize_message_id(msg.get("Message-ID") or fallback_id, raw)
    existing = M.objects.filter(mailbox=mailbox, direction=M.Direction.INBOUND, message_id=message_id).first()
    if existing:
        return existing, False
    name, sender = sender_of(msg)
    row = M(mailbox=mailbox, direction=M.Direction.INBOUND, status=MS.RECEIVED, message_id=message_id,
            in_reply_to=one_line(msg.get("In-Reply-To"), 255), references=one_line(msg.get("References"), 4000),
            from_address=sender, from_name=name, subject=one_line(msg.get("Subject"), 255), size=size,
            to_addresses=", ".join(a for _n, a in getaddresses([str(msg.get("To") or ""), str(msg.get("Cc") or "")]) if a)[:2000])
    if size > max_raw_bytes():
        row.status, row.reason, row.processed_at = MS.REJECTED, "Message trop volumineux.", timezone.now()
    try:
        with transaction.atomic():
            if row.status == MS.RECEIVED:
                row.raw.save("message.eml", ContentFile(raw), save=False)
            row.save()
    except IntegrityError:  # réception concurrente du même message
        return M.objects.get(mailbox=mailbox, direction=M.Direction.INBOUND, message_id=message_id), False
    if row.status == MS.RECEIVED:
        transaction.on_commit(lambda: _schedule("process_ticket_email_task", row.pk))
    return row, True


def process(pk: int) -> str:
    """Traite un message reçu (idempotent : seuls RECEIVED / FAILED sont pris)."""
    with transaction.atomic():
        row = M.objects.select_for_update(of=("self",)).select_related("mailbox", "mailbox__application").filter(pk=pk).first()
        if row is None or row.direction != M.Direction.INBOUND or row.status not in (MS.RECEIVED, MS.FAILED):
            return "skip"
        row.attempt += 1
        try:
            with transaction.atomic():
                _handle(row)
        except Exception as exc:  # erreur imprévue : rien n'est créé (savepoint), nouvel essai
            logger.warning("ticket mail %s : échec du traitement (%s)", pk, type(exc).__name__, exc_info=True)
            row.reason = safe_error(exc)
            if row.attempt >= MAX_ATTEMPTS:
                row.status, row.next_attempt_at, row.processed_at = MS.DEAD, None, timezone.now()
            else:
                row.status = MS.FAILED
                row.next_attempt_at = timezone.now() + timedelta(seconds=BACKOFF_SECONDS[row.attempt - 1])
        else:
            row.processed_at, row.next_attempt_at = timezone.now(), None
        row.save()
    if row.status == MS.FAILED:
        transaction.on_commit(lambda: _schedule("process_ticket_email_task", row.pk, BACKOFF_SECONDS[row.attempt - 1]))
    return row.status.lower()


def _set(row, status, reason="", **fields):
    row.status, row.reason = status, reason[:300]
    for k, v in fields.items():
        setattr(row, k, v)


def _handle(row: dm.TicketEmailMessage) -> None:
    mailbox = row.mailbox
    row.raw.open("rb")
    try:
        raw = row.raw.read()
    finally:
        row.raw.close()
    msg = parse(raw)
    sender = row.from_address
    if not mailbox.is_active:
        return _set(row, MS.REJECTED, "Boîte désactivée.")
    if not sender:
        return _set(row, MS.REJECTED, "Adresse d'expéditeur invalide.")
    if M.objects.filter(mailbox__workspace_id=mailbox.workspace_id, direction=M.Direction.OUTBOUND, message_id=row.message_id).exists():
        return _set(row, MS.IGNORED, "Boucle : message émis par DevFlow.")
    reason = auto_reason(msg, mailbox, sender)
    if reason:
        return _set(row, MS.IGNORED, reason)
    reason = spam_reason(msg, mailbox, sender)
    if reason:
        return _set(row, MS.REJECTED, reason)
    ticket, how = match_ticket(row)
    if how == "suspicious":
        return _set(row, MS.REJECTED, "Référence de ticket dans l'objet sans en-tête de conversation ni expéditeur autorisé.",
                    kind=MK.UNKNOWN)
    if ticket is not None and ticket.status not in (dm.Ticket.Status.CLOSED, dm.Ticket.Status.CANCELLED):
        return _reply(row, msg, ticket)
    return _new_ticket(row, msg, previous=ticket)


def match_ticket(row: dm.TicketEmailMessage) -> tuple[dm.Ticket | None, str]:
    """Jeton signé, puis Message-ID connu de la boîte ; référence d'objet seulement si l'expéditeur est le déclarant."""
    mailbox = row.mailbox
    headers = f"{row.in_reply_to} {row.references}"
    ticket = ticket_from_tokens(headers, mailbox.workspace_id)
    if ticket:
        return ticket, "token"
    ids = set(MSGID_RE.findall(headers))
    if ids:
        known = (M.objects.filter(mailbox=mailbox, message_id__in=ids, ticket__isnull=False)
                 .exclude(pk=row.pk).select_related("ticket").order_by("-created_at").first())
        if known:
            return known.ticket, "headers"
    ref = REF_RE.search(row.subject or "")
    if ref:
        ticket = dm.Ticket.objects.filter(workspace_id=mailbox.workspace_id, mailbox=mailbox, reference=ref[1]).first()
        if ticket and ticket.reporter_email and ticket.reporter_email.lower() == row.from_address:
            return ticket, "subject+sender"
        if ticket:
            return None, "suspicious"
    return None, ""


def _reply(row, msg, ticket: dm.Ticket) -> None:
    from django.contrib.auth import get_user_model

    sender = row.from_address
    text = clean_text(body_text(msg), strip_quotes=True)
    agent = next((u for u in get_user_model().objects.filter(email__iexact=sender, is_active=True)
                  if svc.can_work(u, ticket)), None)
    reporter = bool(ticket.reporter_email) and ticket.reporter_email.lower() == sender
    if agent is None and not reporter:
        return _set(row, MS.REJECTED, f"Expéditeur non autorisé pour {ticket.reference}.", kind=MK.REPLY, ticket=ticket)
    limit = min(row.mailbox.max_attachment_mb, ticket.application.max_attachment_mb, int(getattr(settings, "TICKET_MAX_ATTACHMENT_MB", 20)))
    files, skipped = attachments(msg, limit)
    if skipped:
        text = f"{text}\n\n[Pièces jointes refusées : {', '.join(skipped)}]".strip()
    if not text:
        return _set(row, MS.IGNORED, "Réponse vide.", kind=MK.REPLY, ticket=ticket)
    try:
        if agent is not None:  # réponse interne d'un agent : reste privée
            comment = svc.add_comment(ticket, body=text, visibility="INTERNAL", user=agent, files=files, origin="EMAIL")
        else:
            comment = svc.add_comment(ticket, body=text, visibility="PUBLIC", files=files, origin="EMAIL",
                                      external={"id": sender, "name": row.from_name or ticket.reporter_name or sender})
    except svc.TicketError as exc:
        return _set(row, MS.REJECTED, str(exc), kind=MK.REPLY, ticket=ticket)
    _set(row, MS.PROCESSED, kind=MK.REPLY, ticket=ticket, comment=comment, body_text=text)


def _new_ticket(row, msg, previous: dm.Ticket | None = None) -> None:
    mailbox, sender = row.mailbox, row.from_address
    app = mailbox.application
    if mailbox.allowed_domains and not _domain_matches(sender, mailbox.allowed_domains):
        return _set(row, MS.REJECTED, "Domaine de l'expéditeur non autorisé.", kind=MK.NEW_TICKET)
    hour = timezone.now() - timedelta(hours=1)
    if M.objects.filter(mailbox=mailbox, from_address=sender, kind=MK.NEW_TICKET, status=MS.PROCESSED,
                        created_at__gte=hour).count() >= NEW_TICKETS_PER_SENDER_PER_HOUR:
        return _set(row, MS.REJECTED, "Trop de demandes de cet expéditeur en une heure.", kind=MK.NEW_TICKET)
    if not app.is_active:
        return _set(row, MS.REJECTED, "Application associée suspendue ou archivée.", kind=MK.NEW_TICKET)
    if dm.Ticket.objects.filter(application=app, created_at__gte=timezone.now() - timedelta(days=1)).count() >= app.daily_ticket_quota:
        return _set(row, MS.REJECTED, "Quota journalier de tickets atteint pour l'application.", kind=MK.NEW_TICKET)
    text = clean_text(body_text(msg), strip_quotes=False)
    files, skipped = attachments(msg, mailbox.max_attachment_mb)
    if previous is not None:
        text = f"Suite du ticket {previous.reference} (clôturé).\n\n{text}"
    title = re.sub(r"^(?:\s*(?:re|tr|fw|fwd|aw)\s*:\s*)+", "", row.subject or "", flags=re.I).strip() or "(sans objet)"
    external_id = "email-" + hashlib.sha256(f"{mailbox.pk}:{row.message_id}".encode()).hexdigest()[:40]
    existing = dm.Ticket.objects.filter(application=app, external_id=external_id).first()
    if existing:  # déjà créé (nouvel essai après coupure)
        return _set(row, MS.PROCESSED, kind=MK.NEW_TICKET, ticket=existing)
    category = mailbox.default_category if mailbox.default_category in dm.Ticket.Category.values else dm.Ticket.Category.QUESTION
    values = {
        "external_id": external_id, "title": title[:200], "description": text,
        "category": category, "severity": dm.Ticket.Severity.MINOR,
        "reporter_name": row.from_name or sender, "reporter_email": sender, "reporter_external_id": sender[:120],
        "project_id": mailbox.project_id or app.project_id,
        "metadata": {"email": {"mailbox": mailbox.address, "skipped_attachments": skipped[:20]}},
    }
    ticket = svc._create(app, values, files=files, source=dm.Ticket.Source.EMAIL, origin="EMAIL",
                         actor_label=row.from_name or sender, mailbox=mailbox, attach_external=row.from_name or sender)
    _set(row, MS.PROCESSED, kind=MK.NEW_TICKET, ticket=ticket, body_text=text[:20_000])
    if mailbox.auto_acknowledge:
        queue_ack(ticket, row)


# ─── Envoi ───────────────────────────────────────────────────────────────────

def _thread_ids(ticket) -> tuple[str, str]:
    """(In-Reply-To, References) : derniers messages de la conversation du ticket."""
    ids = list(M.objects.filter(ticket=ticket, mailbox=ticket.mailbox).exclude(message_id="")
               .order_by("-created_at").values_list("message_id", "direction")[:10])
    last_in = next((mid for mid, d in ids if d == M.Direction.INBOUND), ids[0][0] if ids else "")
    return last_in, " ".join(mid for mid, _d in reversed(ids))[:4000]


def _queue(ticket, *, kind: str, to: str, subject: str, body: str, comment=None, in_reply_to="", references="") -> dm.TicketEmailMessage:
    mailbox = ticket.mailbox
    row = M.objects.create(
        mailbox=mailbox, ticket=ticket, comment=comment, direction=M.Direction.OUTBOUND, kind=kind, status=MS.PENDING,
        message_id=make_message_id(ticket, mailbox), in_reply_to=in_reply_to, references=references,
        from_address=mailbox.address, from_name=one_line(mailbox.from_name or mailbox.application.name, 150),
        to_addresses=to, subject=one_line(subject, 255), body_text=body[:20_000], next_attempt_at=timezone.now())
    transaction.on_commit(lambda: _schedule("send_ticket_email_task", row.pk))
    return row


def queue_ack(ticket, inbound: dm.TicketEmailMessage):
    hour = timezone.now() - timedelta(hours=1)
    if M.objects.filter(mailbox=ticket.mailbox, direction=M.Direction.OUTBOUND, kind=MK.ACK, to_addresses=ticket.reporter_email,
                        created_at__gte=hour).count() >= ACKS_PER_SENDER_PER_HOUR:
        return None  # anti ping-pong
    name = ticket.reporter_name if ticket.reporter_name and ticket.reporter_name != ticket.reporter_email else ""
    body = (f"Bonjour{(' ' + name) if name else ''},\n\n"
            f"Nous avons bien reçu votre demande « {ticket.title} ».\n"
            f"Elle est enregistrée sous la référence {ticket.reference}.\n\n"
            "Pour la compléter, répondez simplement à cet e-mail.\n\n"
            f"— {ticket.mailbox.from_name or 'Le support'}")
    references = f"{inbound.references} {inbound.message_id}".strip()[:4000]
    return _queue(ticket, kind=MK.ACK, to=ticket.reporter_email, subject=f"[{ticket.reference}] {ticket.title}", body=body,
                  in_reply_to=inbound.message_id, references=references)


def queue_agent_reply(ticket, comment):
    in_reply_to, references = _thread_ids(ticket)
    return _queue(ticket, kind=MK.AGENT_REPLY, to=ticket.reporter_email, comment=comment,
                  subject=f"Re: [{ticket.reference}] {ticket.title}", body=comment.body,
                  in_reply_to=in_reply_to, references=references)


def smtp_connection(mailbox: dm.TicketMailbox):
    from django.core.mail import get_connection

    if not mailbox.smtp_host:
        return get_connection()
    check_host(mailbox.smtp_host, mailbox.smtp_port)
    ssl_mode = mailbox.smtp_security == dm.TicketMailbox.Security.SSL
    return get_connection(backend="django.core.mail.backends.smtp.EmailBackend", host=mailbox.smtp_host,
                          port=mailbox.smtp_port, username=mailbox.smtp_username, password=get_secret(mailbox, "smtp_password"),
                          use_ssl=ssl_mode, use_tls=not ssl_mode, timeout=20, fail_silently=False)


def build_email(row: dm.TicketEmailMessage, connection=None):
    from django.core.mail import EmailMessage

    mailbox = row.mailbox
    sender = mailbox.address if mailbox.smtp_host else settings.DEFAULT_FROM_EMAIL
    headers = {"Message-ID": row.message_id, "X-DevFlow-Loop": mailbox.address,
               "Auto-Submitted": "auto-replied" if row.kind == MK.ACK else "no"}
    if row.kind == MK.ACK:
        headers["X-Auto-Response-Suppress"] = "All"
    if row.in_reply_to:
        headers["In-Reply-To"] = one_line(row.in_reply_to, 255)
    if row.references:
        headers["References"] = one_line(row.references, 4000)
    message = EmailMessage(subject=one_line(row.subject, 255), body=row.body_text, connection=connection,
                           from_email=formataddr((one_line(row.from_name, 150), sender)), to=[row.to_addresses],
                           reply_to=[mailbox.address], headers=headers)
    if row.comment_id:
        total = 0
        for att in row.comment.attachments.filter(visibility="PUBLIC"):
            total += att.size
            if total > 10 * 1024 * 1024:
                break
            with att.file.open("rb") as fh:
                message.attach(att.original_name, fh.read(), att.mime_type)
    return message


def send(pk: int) -> str:
    """Une tentative d'envoi ; replanifie avec backoff (erreurs passagères), abandonne sinon."""
    with transaction.atomic():
        row = M.objects.select_for_update(of=("self",)).select_related("mailbox", "mailbox__application", "ticket", "comment").filter(pk=pk).first()
        if row is None or row.direction != M.Direction.OUTBOUND or row.status not in (MS.PENDING, MS.FAILED):
            return "skip"
        row.attempt += 1
        permanent = False
        try:
            validate_email(row.to_addresses)
            connection = smtp_connection(row.mailbox)
            build_email(row, connection).send(fail_silently=False)
        except (ValidationError, ValueError, smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused,
                smtplib.SMTPAuthenticationError) as exc:
            permanent, error = True, exc
        except (smtplib.SMTPException, OSError, ssl.SSLError, TemporaryMailError) as exc:
            error = exc
        else:
            error = None
        if error is None:
            row.status, row.reason, row.next_attempt_at, row.processed_at = MS.SENT, "", None, timezone.now()
        else:
            row.reason = safe_error(error, row.mailbox)
            if permanent or row.attempt >= MAX_ATTEMPTS:
                row.status, row.next_attempt_at = MS.DEAD, None
                if row.ticket_id:
                    svc.log_event(row.ticket, "email_failed", origin="SYSTEM", new={"to": row.to_addresses, "error": row.reason})
                    svc.notify(row.ticket, {row.ticket.assignee_id} - {None}, f"E-mail non délivré : {row.ticket.reference}", row.reason)
            else:
                row.status = MS.FAILED
                row.next_attempt_at = timezone.now() + timedelta(seconds=BACKOFF_SECONDS[row.attempt - 1])
        row.save()
    if row.status == MS.FAILED:
        transaction.on_commit(lambda: _schedule("send_ticket_email_task", row.pk, BACKOFF_SECONDS[row.attempt - 1]))
    return row.status.lower()


def retry_due(now=None) -> int:
    """Balayage périodique : envois et traitements dus (broker perdu, redémarrage)."""
    now = now or timezone.now()
    stale = now - timedelta(minutes=2)
    count = 0
    for pk, direction in M.objects.filter(status__in=[MS.PENDING, MS.FAILED, MS.RECEIVED]).filter(
            next_attempt_at__lte=stale).values_list("pk", "direction")[:200]:
        _schedule("send_ticket_email_task" if direction == M.Direction.OUTBOUND else "process_ticket_email_task", pk)
        count += 1
    for pk in M.objects.filter(status=MS.RECEIVED, next_attempt_at__isnull=True, created_at__lte=stale).values_list("pk", flat=True)[:200]:
        _schedule("process_ticket_email_task", pk)
        count += 1
    return count


def reprocess(row: dm.TicketEmailMessage) -> None:
    """Relance manuelle (administrateur) d'un message rejeté, ignoré ou en échec."""
    if row.direction == M.Direction.INBOUND:
        if not row.raw:
            raise svc.TicketError("Contenu du message non conservé : impossible de le retraiter.")
        row.status, task = MS.RECEIVED, "process_ticket_email_task"
    else:
        row.status, task = MS.PENDING, "send_ticket_email_task"
    row.attempt = min(row.attempt, MAX_ATTEMPTS - 1)
    row.reason, row.next_attempt_at = "", timezone.now()
    row.save(update_fields=["status", "attempt", "reason", "next_attempt_at", "updated_at"])
    transaction.on_commit(lambda: _schedule(task, row.pk))


# ─── IMAP ────────────────────────────────────────────────────────────────────

def imap_connect(mailbox: dm.TicketMailbox):
    check_host(mailbox.imap_host, mailbox.imap_port)
    context = ssl.create_default_context()
    if mailbox.imap_security == dm.TicketMailbox.Security.SSL:
        conn = imaplib.IMAP4_SSL(mailbox.imap_host, mailbox.imap_port, ssl_context=context, timeout=30)
    else:
        conn = imaplib.IMAP4(mailbox.imap_host, mailbox.imap_port, timeout=30)
        conn.starttls(ssl_context=context)
    conn.login(mailbox.imap_username, get_secret(mailbox, "imap_password"))
    return conn


def _folder(mailbox) -> str:
    name = (mailbox.imap_folder or "INBOX").replace('"', "")
    return f'"{name}"' if " " in name else name


def _uidvalidity(conn) -> int:
    value = (conn.untagged_responses.get("UIDVALIDITY") or [b"0"])[0]
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def poll(mailbox: dm.TicketMailbox) -> dict:
    """Relève les nouveaux messages (UID) ; la progression n'avance qu'après stockage durable."""
    lock = f"ticketing:mailbox:{mailbox.pk}:poll"
    if not cache.add(lock, 1, 600):
        return {"status": "locked"}
    stats = {"fetched": 0, "new": 0}
    conn = None
    try:
        conn = imap_connect(mailbox)
        typ, _ = conn.select(_folder(mailbox))
        if typ != "OK":
            raise imaplib.IMAP4.error(f"Dossier introuvable : {mailbox.imap_folder}")
        validity = _uidvalidity(conn)
        if mailbox.uid_validity and validity and validity != mailbox.uid_validity:
            mailbox.last_uid = 0  # dossier recréé : la déduplication par Message-ID évite les doublons
        mailbox.uid_validity = validity or mailbox.uid_validity
        typ, data = conn.uid("SEARCH", None, f"UID {mailbox.last_uid + 1}:*")
        uids = sorted(int(x) for x in (data[0] or b"").split() if x.isdigit() and int(x) > mailbox.last_uid)[:IMAP_BATCH]
        for uid in uids:
            typ, meta = conn.uid("FETCH", str(uid), "(RFC822.SIZE)")
            size_match = re.search(rb"RFC822\.SIZE (\d+)", b" ".join(x if isinstance(x, bytes) else b"" for x in meta or []))
            fallback = f"<imap.{validity}.{uid}@{mailbox.imap_host}>"
            if size_match and int(size_match[1]) > max_raw_bytes():
                typ, head = conn.uid("FETCH", str(uid), "(BODY.PEEK[HEADER])")
                header = next((part[1] for part in head or [] if isinstance(part, tuple) and len(part) > 1), b"")
                _, created = ingest(mailbox, header, fallback_id=fallback, size=int(size_match[1]))
            else:
                typ, payload = conn.uid("FETCH", str(uid), "(BODY.PEEK[])")
                raw = next((part[1] for part in payload or [] if isinstance(part, tuple) and len(part) > 1), None)
                if raw is None:
                    raise imaplib.IMAP4.error(f"Message UID {uid} illisible.")
                _, created = ingest(mailbox, raw, fallback_id=fallback)
            stats["fetched"] += 1
            stats["new"] += int(created)
            mailbox.last_uid = uid  # message stocké durablement : on avance
            dm.TicketMailbox.objects.filter(pk=mailbox.pk).update(last_uid=uid, uid_validity=mailbox.uid_validity)
            try:
                conn.uid("STORE", str(uid), "+FLAGS", "(\\Seen)")
            except imaplib.IMAP4.error:
                pass
        _mark_success(mailbox)
    except Exception as exc:  # réseau, TLS, authentification, serveur
        _mark_failure(mailbox, exc)
        stats["error"] = mailbox.last_error
    finally:
        if conn is not None:
            try:
                conn.logout()
            except Exception:
                pass
        cache.delete(lock)
    return stats


def _mark_success(mailbox) -> None:
    now = timezone.now()
    recovered = mailbox.alert_sent_at is not None
    dm.TicketMailbox.objects.filter(pk=mailbox.pk).update(
        last_sync_at=now, last_success_at=now, consecutive_failures=0, next_poll_at=None, alert_sent_at=None, last_error="")
    if recovered:
        _alert(mailbox, f"Réception rétablie : {mailbox.address}", "La relève des e-mails fonctionne de nouveau.")


def _mark_failure(mailbox, exc: Exception) -> None:
    now = timezone.now()
    failures = mailbox.consecutive_failures + 1
    error = safe_error(exc, mailbox)
    logger.warning("ticket mailbox %s : relève en échec (%s)", mailbox.pk, error)
    updates = {"last_sync_at": now, "last_error": error, "last_error_at": now, "consecutive_failures": failures,
               "next_poll_at": now + timedelta(minutes=min(2 ** failures, 60))}
    if failures >= ALERT_AFTER_FAILURES and mailbox.alert_sent_at is None:
        updates["alert_sent_at"] = now
        _alert(mailbox, f"Réception e-mail interrompue : {mailbox.address}",
               f"{failures} relèves consécutives en échec. Dernière erreur : {error}")
    dm.TicketMailbox.objects.filter(pk=mailbox.pk).update(**updates)
    for k, v in updates.items():
        setattr(mailbox, k, v)


def _alert(mailbox, title: str, body: str) -> None:
    """Supervision : notification au propriétaire du workspace et au responsable de l'équipe par défaut."""
    team = mailbox.application.default_team
    recipients = {mailbox.workspace.owner_id, team.lead_id if team else None} - {None}
    for uid in recipients:
        dm.Notification.objects.create(
            recipient_id=uid, workspace_id=mailbox.workspace_id, notification_type=dm.Notification.NotificationType.SYSTEM,
            title=title[:180], body=body[:500], url="/tickets/email/", metadata={"kind": "ticket_mailbox", "mailbox_id": mailbox.pk})


def poll_due(now=None) -> int:
    now = now or timezone.now()
    from django.db.models import Q

    due = dm.TicketMailbox.objects.filter(is_active=True, inbound=dm.TicketMailbox.Inbound.IMAP).exclude(imap_host="").filter(
        Q(next_poll_at__isnull=True) | Q(next_poll_at__lte=now))
    ids = list(due.values_list("pk", flat=True)[:100])
    for pk in ids:
        _schedule("poll_ticket_mailbox_task", pk)
    return len(ids)


def test_connection(mailbox: dm.TicketMailbox) -> dict:
    """Test depuis l'administration : connexion + authentification IMAP et SMTP, sans envoi."""
    result = {"imap": None, "smtp": None}
    if mailbox.inbound == dm.TicketMailbox.Inbound.IMAP:
        conn = None
        try:
            conn = imap_connect(mailbox)
            typ, _ = conn.select(_folder(mailbox), readonly=True)
            result["imap"] = {"ok": typ == "OK", "detail": "Connexion et dossier OK." if typ == "OK" else "Dossier introuvable."}
        except Exception as exc:
            result["imap"] = {"ok": False, "detail": safe_error(exc, mailbox)}
        finally:
            if conn is not None:
                try:
                    conn.logout()
                except Exception:
                    pass
    if mailbox.smtp_host:
        try:
            connection = smtp_connection(mailbox)
            connection.open()
            connection.close()
            result["smtp"] = {"ok": True, "detail": "Connexion et authentification OK."}
        except Exception as exc:
            result["smtp"] = {"ok": False, "detail": safe_error(exc, mailbox)}
    else:
        result["smtp"] = {"ok": True, "detail": "Envoi par la messagerie par défaut de DevFlow (Reply-To : adresse de la boîte)."}
    return result
