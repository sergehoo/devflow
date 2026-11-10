"""
Ticketing multi-applications — services métier (source unique des règles).

Identifiants d'intégration chiffrés, assainissement des données entrantes,
droits (RBAC + contrôle objet), SLA en heures ouvrées, routage, workflow à
transitions validées, tâches DevFlow liées, notifications temps réel, journal
d'événements. Les webhooks sortants sont dans ``ticketing_webhooks``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q
from django.utils import timezone

from project import models as dm

T = dm.Ticket
S = dm.Ticket.Status


class TicketError(Exception):
    """Règle métier refusée (traduit en 400 / 409 par l'API)."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ─── Identifiants d'intégration ──────────────────────────────────────────────

def _fernet():
    from cryptography.fernet import Fernet

    material = getattr(settings, "TICKETING_ENCRYPTION_KEY", "") or settings.SECRET_KEY
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(f"devflow-ticketing:{material}".encode()).digest()))


def new_credentials() -> tuple[str, str]:
    return f"app_{secrets.token_hex(8)}", f"dfs_{secrets.token_urlsafe(32)}"


def set_secret(app: dm.ExternalApplication, secret: str) -> None:
    app.secret_encrypted = _fernet().encrypt(secret.encode()).decode()
    app.secret_last4 = secret[-4:]


def get_secret(app: dm.ExternalApplication) -> str:
    return _fernet().decrypt(app.secret_encrypted.encode()).decode()


def rotate_secret(app: dm.ExternalApplication) -> str:
    """Nouveau secret (renvoyé une seule fois à l'administrateur)."""
    _key, secret = new_credentials()
    set_secret(app, secret)
    app.secret_rotated_at = timezone.now()
    app.save(update_fields=["secret_encrypted", "secret_last4", "secret_rotated_at", "updated_at"])
    return secret


def signature(secret: str, timestamp: str, method: str, path: str, body: bytes) -> str:
    """HMAC-SHA256 hex de « timestamp.MÉTHODE.chemin.sha256(corps) »."""
    message = f"{timestamp}.{method.upper()}.{path}.{hashlib.sha256(body or b'').hexdigest()}"
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


# ─── Assainissement ──────────────────────────────────────────────────────────

SENSITIVE_KEY = re.compile(r"pass|pwd|secret|token|auth|cookie|session|card|cvv|iban|ssn|otp|pin\b|apikey|api_key|private", re.I)
MAX_METADATA_BYTES = 8_000


def sanitize_metadata(value, depth: int = 0):
    """Contexte technique : clés sensibles retirées, profondeur et tailles bornées."""
    if depth > 4:
        return None
    if isinstance(value, dict):
        out = {}
        for k, v in list(value.items())[:50]:
            key = str(k)[:60]
            if SENSITIVE_KEY.search(key):
                continue
            out[key] = sanitize_metadata(v, depth + 1)
        return out
    if isinstance(value, list):
        return [sanitize_metadata(v, depth + 1) for v in value[:30]]
    if isinstance(value, str):
        return value[:500]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:200]


def bounded_metadata(value) -> dict:
    import json

    clean = sanitize_metadata(value if isinstance(value, dict) else {}) or {}
    if len(json.dumps(clean, default=str)) > MAX_METADATA_BYTES:
        raise TicketError("Métadonnées techniques trop volumineuses (8 Ko maximum).")
    return clean


def sanitize_url(url: str) -> str:
    """Retire fragment et paramètres de requête sensibles (jetons, codes, sessions)."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    if not url:
        return ""
    parts = urlsplit(url)
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                       if not SENSITIVE_KEY.search(k) and k.lower() not in {"code", "state", "key", "sig", "signature"}])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))[:500]


ALLOWED_MIME = {
    "image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf", "text/plain", "text/csv",
    "application/json", "application/zip", "video/mp4", "video/webm",
}
_MAGIC = {
    "image/png": [b"\x89PNG\r\n\x1a\n"], "image/jpeg": [b"\xff\xd8\xff"], "image/gif": [b"GIF87a", b"GIF89a"],
    "image/webp": [b"RIFF"], "application/pdf": [b"%PDF-"], "application/zip": [b"PK\x03\x04"],
}


def validate_upload(upload, max_mb: int) -> str:
    """Type MIME autorisé + signature binaire cohérente + taille. Renvoie le MIME retenu."""
    mime = (getattr(upload, "content_type", "") or "").split(";")[0].strip().lower()
    if mime not in ALLOWED_MIME:
        raise TicketError(f"Type de fichier non autorisé : {mime or 'inconnu'}.")
    if upload.size > max_mb * 1024 * 1024:
        raise TicketError(f"Fichier trop volumineux ({max_mb} Mo maximum).")
    head = upload.read(16)
    upload.seek(0)
    signatures = _MAGIC.get(mime)
    if signatures and not any(head.startswith(sig) for sig in signatures):
        raise TicketError("Le contenu du fichier ne correspond pas à son type.")
    if mime.startswith("text/") or mime == "application/json":
        sample = upload.read(4096)
        upload.seek(0)
        if b"\x00" in sample:
            raise TicketError("Fichier texte invalide.")
    return mime


# ─── Droits ──────────────────────────────────────────────────────────────────

def _rbac(user, action: str, workspace_id: int) -> bool:
    from project.services.rbac import RBACService

    workspace = dm.Workspace.objects.filter(pk=workspace_id).only("id", "owner_id").first()
    return workspace is not None and RBACService.can(user, action, workspace=workspace)


def user_team_ids(user, workspace_id: int) -> set[int]:
    return set(dm.TeamMembership.objects.filter(user=user, workspace_id=workspace_id, team__isnull=False)
               .exclude(status=dm.TeamMembership.Status.INACTIVE).values_list("team_id", flat=True))


def visible_tickets(user, qs=None):
    """Tickets visibles : tout le workspace avec ``ticket.view`` ; sinon ses équipes et ses affectations."""
    from project.services.rbac import rbac_workspace_ids
    from project.utils.workspaces import get_user_workspace_ids

    qs = dm.Ticket.objects.all() if qs is None else qs
    if user.is_superuser:
        return qs
    ws_ids = list(get_user_workspace_ids(user))
    full = rbac_workspace_ids(user, "ticket.view")
    team_ids = dm.TeamMembership.objects.filter(user=user, workspace_id__in=ws_ids, team__isnull=False).values("team_id")
    return qs.filter(workspace_id__in=ws_ids).filter(
        Q(workspace_id__in=full) | Q(assignee=user) | Q(team_id__in=team_ids) | Q(created_by=user))


def can_manage(user, ticket) -> bool:
    return user.is_superuser or _rbac(user, "ticket.manage", ticket.workspace_id)


def can_assign(user, ticket) -> bool:
    return user.is_superuser or _rbac(user, "ticket.assign", ticket.workspace_id)


def can_admin(user, workspace_id: int) -> bool:
    return user.is_superuser or _rbac(user, "ticket.admin", workspace_id)


def can_work(user, ticket) -> bool:
    """Traiter le ticket : gestionnaire, ou agent affecté / membre de l'équipe responsable."""
    if can_manage(user, ticket):
        return True
    if not _rbac(user, "ticket.work_assigned", ticket.workspace_id):
        return False
    return ticket.assignee_id == user.pk or (ticket.team_id is not None and ticket.team_id in user_team_ids(user, ticket.workspace_id))


def is_eligible_agent(user, team: dm.Team) -> bool:
    """Agent affectable : membre actif de l'équipe ET détenteur d'un droit ticket dans le workspace."""
    if not user or not user.is_active:
        return False
    member = dm.TeamMembership.objects.filter(user=user, team=team, workspace_id=team.workspace_id).exclude(
        status=dm.TeamMembership.Status.INACTIVE).exists()
    return member and any(_rbac(user, a, team.workspace_id) for a in ("ticket.manage", "ticket.work_assigned"))


def can_download(user, attachment: dm.TicketAttachment) -> bool:
    ticket = attachment.ticket
    if not visible_tickets(user, dm.Ticket.objects.filter(pk=ticket.pk)).exists():
        return False
    return attachment.visibility == "PUBLIC" or can_work(user, ticket) or _rbac(user, "ticket.view", ticket.workspace_id)


def can_download_path(user, path: str) -> bool:
    att = dm.TicketAttachment.objects.select_related("ticket").filter(file=path).first()
    return bool(att and user.is_authenticated and can_download(user, att))


# ─── SLA ─────────────────────────────────────────────────────────────────────

DEFAULT_TARGETS = {  # minutes : (première réponse, résolution)
    "P1": {"first_response": 30, "resolution": 240},
    "P2": {"first_response": 120, "resolution": 960},
    "P3": {"first_response": 480, "resolution": 2400},
    "P4": {"first_response": 1440, "resolution": 7200},
}
SEVERITY_PRIORITY = {"CRITICAL": "P1", "MAJOR": "P2", "MINOR": "P3", "TRIVIAL": "P4"}


def _as_time(value, fallback: str) -> time:
    if isinstance(value, time):
        return value
    try:
        return time.fromisoformat(str(value or fallback))
    except ValueError:
        return time.fromisoformat(fallback)


def add_business_minutes(start: datetime, minutes: int, policy: dm.TicketSLAPolicy | None) -> datetime:
    """Échéance en minutes ouvrées (calendrier de la politique) ; 24/7 sans politique."""
    if not policy or not policy.business_hours_only:
        return start + timedelta(minutes=minutes)
    tz = ZoneInfo(policy.timezone or "UTC")
    bs, be = _as_time(policy.business_start, "08:00"), _as_time(policy.business_end, "18:00")
    days = set(policy.business_days or [0, 1, 2, 3, 4])
    cur, remaining = start.astimezone(tz), float(minutes)
    for _ in range(800):  # garde-fou (~2 ans de jours)
        day_start = cur.replace(hour=bs.hour, minute=bs.minute, second=0, microsecond=0)
        day_end = cur.replace(hour=be.hour, minute=be.minute, second=0, microsecond=0)
        if cur.weekday() not in days or cur >= day_end or day_end <= day_start:
            cur = (cur + timedelta(days=1)).replace(hour=bs.hour, minute=bs.minute, second=0, microsecond=0)
            continue
        cur = max(cur, day_start)
        available = (day_end - cur).total_seconds() / 60
        if remaining <= available:
            return cur + timedelta(minutes=remaining)
        remaining -= available
        cur = (cur + timedelta(days=1)).replace(hour=bs.hour, minute=bs.minute, second=0, microsecond=0)
    return cur


def policy_for(app: dm.ExternalApplication) -> dm.TicketSLAPolicy | None:
    return app.sla_policy or dm.TicketSLAPolicy.objects.filter(workspace_id=app.workspace_id, is_default=True).first()


def targets_for(policy, priority: str) -> dict:
    t = ((policy.targets or {}) if policy else {}).get(priority) or DEFAULT_TARGETS[priority]
    return {"first_response": int(t.get("first_response") or DEFAULT_TARGETS[priority]["first_response"]),
            "resolution": int(t.get("resolution") or DEFAULT_TARGETS[priority]["resolution"])}


def apply_sla(ticket: dm.Ticket, start: datetime | None = None) -> None:
    start = start or ticket.created_at or timezone.now()
    t = targets_for(ticket.sla_policy, ticket.priority)
    ticket.first_response_due = add_business_minutes(start, t["first_response"], ticket.sla_policy)
    ticket.resolution_due = add_business_minutes(start, t["resolution"], ticket.sla_policy)


def sla_state(ticket: dm.Ticket) -> dict:
    now = timezone.now()

    def remaining(due, done):
        if not due or done:
            return None
        return int((due - (ticket.sla_paused_at or now)).total_seconds())

    return {
        "policy": ticket.sla_policy.name if ticket.sla_policy_id else "Délais par défaut",
        "first_response_due": ticket.first_response_due, "resolution_due": ticket.resolution_due,
        "first_response_remaining_seconds": remaining(ticket.first_response_due, ticket.first_response_at),
        "resolution_remaining_seconds": remaining(ticket.resolution_due, ticket.resolved_at),
        "paused": ticket.sla_paused_at is not None, "first_response_breached": ticket.first_response_breached,
        "resolution_breached": ticket.resolution_breached, "escalation_level": ticket.escalation_level,
    }


# ─── Événements, notifications, webhooks ────────────────────────────────────

def log_event(ticket, action: str, *, actor=None, actor_label: str = "", origin: str = "UI",
              old=None, new=None, public: bool = False) -> dm.TicketEvent:
    return dm.TicketEvent.objects.create(
        ticket=ticket, actor=actor, actor_label=actor_label or ((actor.get_full_name() or actor.get_username()) if actor else ""),
        action=action, old_value=old, new_value=new, origin=origin, is_public=public)


def _team_leads(team) -> set[int]:
    return {team.lead_id} if team and team.lead_id else set()


def notify(ticket, user_ids, title: str, body: str = "") -> None:
    """Notification in-app (poussée en temps réel par le signal existant) + rafraîchissement live."""
    from project.services.realtime import push_to_users

    ids = {int(u) for u in user_ids if u}
    for uid in ids:
        dm.Notification.objects.create(
            recipient_id=uid, workspace_id=ticket.workspace_id, notification_type=dm.Notification.NotificationType.SYSTEM,
            title=title[:180], body=body[:500], url=f"/tickets/{ticket.pk}/",
            metadata={"kind": "ticket", "ticket_id": ticket.pk, "reference": ticket.reference})
    watchers = ids | {ticket.assignee_id} | _team_leads(ticket.team)
    transaction.on_commit(lambda: push_to_users(watchers, "ticket.changed", {"id": ticket.pk, "reference": ticket.reference}))


def emit(ticket, event: str, extra: dict | None = None) -> None:
    from project.services.ticketing_webhooks import enqueue

    enqueue(ticket, event, extra)


# ─── Création (API d'intégration) ────────────────────────────────────────────

def _next_number(workspace_id: int) -> int:
    dm.Workspace.objects.select_for_update().filter(pk=workspace_id).first()  # verrou de numérotation (PostgreSQL)
    return (dm.Ticket.objects.filter(workspace_id=workspace_id).aggregate(m=Max("number"))["m"] or 0) + 1


def create_from_integration(app: dm.ExternalApplication, data: dict, files=(), idempotency_key: str = "") -> tuple[dm.Ticket, bool]:
    """Crée le ticket (ou renvoie l'existant : idempotence / doublon). Renvoie (ticket, créé)."""
    existing = dm.Ticket.objects.filter(application=app).filter(
        Q(external_id=data["external_id"]) | (Q(idempotency_key=idempotency_key) if idempotency_key else Q(pk__in=[])))
    found = existing.first()
    if found:
        if idempotency_key and found.idempotency_key == idempotency_key and found.external_id != data["external_id"]:
            raise TicketError("Idempotency-Key déjà utilisée pour un autre ticket.", 422)
        return found, False
    since = timezone.now() - timedelta(days=1)
    if dm.Ticket.objects.filter(application=app, created_at__gte=since).count() >= app.daily_ticket_quota:
        raise TicketError("Quota journalier de tickets atteint pour cette application.", 429)
    reporter = data.get("reporter") or {}
    if reporter.get("id") and dm.Ticket.objects.filter(
            application=app, reporter_external_id=reporter["id"], created_at__gte=timezone.now() - timedelta(hours=1)).count() >= 20:
        raise TicketError("Trop de tickets créés par ce déclarant en une heure.", 429)
    for upload in files:
        validate_upload(upload, app.max_attachment_mb)
    values = {
        "external_id": data["external_id"], "idempotency_key": idempotency_key,
        "reporter_external_id": str(reporter.get("id") or "")[:120], "reporter_name": str(reporter.get("name") or "")[:150],
        "reporter_email": reporter.get("email") or "", "title": data["title"], "description": data.get("description") or "",
        "category": data.get("category") or T.Category.BUG, "severity": data.get("severity") or T.Severity.MINOR,
        "environment": data.get("environment") or "", "app_version": data.get("app_version") or "",
        "url": sanitize_url(data.get("url") or ""), "metadata": bounded_metadata(data.get("metadata")),
    }
    try:
        ticket = _create(app, values, files=files, source=T.Source.API, origin="API", actor_label=app.name,
                         attach_external=values["reporter_name"] or app.name)
    except IntegrityError:
        again = dm.Ticket.objects.filter(application=app, external_id=data["external_id"]).first()
        if again:
            return again, False
        raise
    return ticket, True


def _create(app: dm.ExternalApplication, values: dict, *, files=(), source: str, origin: str, actor=None,
            actor_label: str = "", priority: str | None = None, team=None, assignee=None, mailbox=None,
            attach_external: str = "", attach_visibility: str = "PUBLIC") -> dm.Ticket:
    """
    Cœur de création commun aux trois canaux (API, saisie DevFlow, e-mail) :
    numéro et référence uniques (verrou + nouvel essai), SLA, pièces jointes,
    journal d'audit, routage (ou affectation manuelle), notifications, webhook.
    Transaction atomique : rien n'est créé si une étape échoue.
    """
    for attempt in range(3):
        try:
            with transaction.atomic():
                number = _next_number(app.workspace_id)
                severity = values.get("severity") or T.Severity.MINOR
                ticket = dm.Ticket(
                    workspace_id=app.workspace_id, application=app, number=number, reference=f"TCK-{number:05d}",
                    source=source, created_by=actor, mailbox=mailbox, sla_policy=policy_for(app),
                    **{"project_id": app.project_id, **values, "severity": severity,
                       "priority": priority or SEVERITY_PRIORITY.get(severity, "P3")})
                ticket.external_id = ticket.external_id or f"devflow-{number}"
                ticket.created_at = timezone.now()
                apply_sla(ticket, ticket.created_at)
                ticket.save()
                for upload in files:
                    _store_attachment(ticket, upload, visibility=attach_visibility, user=actor,
                                      external="" if actor else attach_external)
                log_event(ticket, "created", actor=actor, actor_label=actor_label, origin=origin,
                          new={"status": ticket.status, "source": source}, public=True)
                if team or assignee:
                    _set_assignment(ticket, team, assignee, actor=actor, reason="Affectation à la création")
                else:
                    route(ticket, keep_priority=priority is not None)
                _announce(ticket, actor)
                emit(ticket, "ticket.created")
            return ticket
        except IntegrityError:
            if values.get("external_id") and dm.Ticket.objects.filter(application=app, external_id=values["external_id"]).exists():
                raise
            if attempt == 2:
                raise
    raise TicketError("Création impossible, réessayez.", 503)


def _announce(ticket, actor=None) -> None:
    """Nouveau ticket en file d'équipe : notification temps réel aux agents éligibles de l'équipe."""
    if not ticket.team_id or ticket.assignee_id:
        return
    members = dm.TeamMembership.objects.filter(team_id=ticket.team_id, workspace_id=ticket.workspace_id).exclude(
        status__in=[dm.TeamMembership.Status.INACTIVE, dm.TeamMembership.Status.ON_LEAVE]).select_related("user")
    already = _team_leads(ticket.team) | ({actor.pk} if actor else set())
    recipients = [m.user_id for m in members[:50] if m.user_id not in already and is_eligible_agent(m.user, ticket.team)]
    if recipients:
        notify(ticket, recipients, f"Nouveau ticket {ticket.reference} dans la file {ticket.team.name}", ticket.title)


def create_manual(user, data: dict, files=()) -> dm.Ticket:
    """
    Saisie DevFlow (session authentifiée). ``data`` validé par l'API :
    application, title, description, category, severity, priority?, project?,
    team?, assignee?, reporter_name?, reporter_email?. Droits : ``ticket.create``
    (+ ``ticket.manage`` pour imposer la priorité, ``ticket.assign`` pour affecter).
    """
    from django.contrib.auth import get_user_model

    app = data["application"]
    ws_id = app.workspace_id
    if not (user.is_superuser or _rbac(user, "ticket.create", ws_id)):
        raise TicketError("Vous n'avez pas le droit de créer un ticket dans ce workspace.", 403)
    if not app.is_active:
        raise TicketError("Application suspendue ou archivée : choisissez une application active.")
    project = data.get("project")
    if project is not None and project.workspace_id != ws_id:
        raise TicketError("Projet introuvable dans ce workspace.")
    priority = data.get("priority") or None
    if priority and not (user.is_superuser or _rbac(user, "ticket.manage", ws_id)):
        raise TicketError("Seul un gestionnaire du support peut imposer la priorité.", 403)
    team, assignee = data.get("team"), None
    if data.get("assignee"):
        assignee = get_user_model().objects.filter(pk=data["assignee"]).first()
        if assignee is None:
            raise TicketError("Agent introuvable.")
    if team or assignee:
        if not (user.is_superuser or _rbac(user, "ticket.assign", ws_id)):
            raise TicketError("Vous n'avez pas le droit d'affecter un ticket : laissez le routage automatique.", 403)
        if team is None:
            raise TicketError("Choisissez l'équipe de l'agent.")
        if team.workspace_id != ws_id:
            raise TicketError("Équipe introuvable dans ce workspace.")
        if assignee and not is_eligible_agent(assignee, team):
            raise TicketError("Cet agent n'est pas un membre actif de l'équipe ou n'a pas de droit sur les tickets.")
    if dm.Ticket.objects.filter(created_by=user, created_at__gte=timezone.now() - timedelta(minutes=10)).count() >= 30:
        raise TicketError("Trop de tickets créés en peu de temps : patientez quelques minutes.", 429)
    max_mb = int(getattr(settings, "TICKET_MAX_ATTACHMENT_MB", 20))
    for upload in files:
        validate_upload(upload, max_mb)
    values = {
        "title": data["title"], "description": data.get("description") or "",
        "category": data.get("category") or T.Category.BUG, "severity": data.get("severity") or T.Severity.MINOR,
        "reporter_name": (data.get("reporter_name") or user.get_full_name() or user.get_username())[:150],
        "reporter_email": data.get("reporter_email") or "",
        "project_id": project.pk if project else app.project_id,
    }
    return _create(app, values, files=files, source=T.Source.MANUAL, origin="UI", actor=user, priority=priority,
                   team=team, assignee=assignee)


def _store_attachment(ticket, upload, *, visibility: str, user=None, external: str = "", comment=None) -> dm.TicketAttachment:
    mime = (upload.content_type or "").split(";")[0].strip().lower()
    return dm.TicketAttachment.objects.create(
        ticket=ticket, comment=comment, file=upload, original_name=(upload.name or "fichier")[-200:], mime_type=mime,
        size=upload.size, visibility=visibility, uploaded_by=user, uploaded_by_external=external[:150])


def add_attachments(ticket, files, *, user, visibility: str) -> list[dm.TicketAttachment]:
    max_mb = int(getattr(settings, "TICKET_MAX_ATTACHMENT_MB", 20))
    for upload in files:
        validate_upload(upload, max_mb)
    out = [_store_attachment(ticket, f, visibility=visibility, user=user) for f in files]
    if out:
        log_event(ticket, "attachment_added", actor=user, new={"files": [a.original_name for a in out]},
                  public=visibility == "PUBLIC")
    return out


# ─── Routage ─────────────────────────────────────────────────────────────────

def matching_rule(ticket) -> dm.TicketRoutingRule | None:
    rules = dm.TicketRoutingRule.objects.filter(workspace_id=ticket.workspace_id, is_active=True).filter(
        Q(application__isnull=True) | Q(application_id=ticket.application_id),
        Q(category="") | Q(category=ticket.category), Q(severity="") | Q(severity=ticket.severity),
    ).select_related("team").order_by("position", "id")
    return next(iter(rules), None)


def pick_agent(team) -> object | None:
    """Agent disponible le moins chargé (tickets ouverts), membre actif éligible de l'équipe."""
    from django.contrib.auth import get_user_model

    members = dm.TeamMembership.objects.filter(team=team, workspace_id=team.workspace_id).exclude(
        status__in=[dm.TeamMembership.Status.INACTIVE, dm.TeamMembership.Status.ON_LEAVE]).values_list("user_id", flat=True)
    users = (get_user_model().objects.filter(pk__in=members, is_active=True)
             .annotate(open_tickets=Count("assigned_tickets", filter=Q(assigned_tickets__status__in=T.OPEN_STATUSES)))
             .order_by("open_tickets", "pk"))
    return next((u for u in users if is_eligible_agent(u, team)), None)


def route(ticket, *, actor=None, keep_priority: bool = False) -> None:
    """Règle de routage (sinon équipe par défaut de l'application), affectation automatique éventuelle."""
    rule = matching_rule(ticket)
    team = rule.team if rule else ticket.application.default_team
    if rule and not keep_priority and rule.priority_override in dict(T.Priority.choices):
        ticket.priority = rule.priority_override
        apply_sla(ticket, ticket.created_at)
    if not team:
        ticket.save()
        log_event(ticket, "unassigned_queue", origin="SYSTEM", new={"reason": "Aucune règle ni équipe par défaut"})
        return
    agent = pick_agent(team) if rule and rule.auto_assign else None
    _set_assignment(ticket, team, agent, actor=actor, origin="SYSTEM", reason=f"Règle « {rule.name} »" if rule else "Équipe par défaut")


def _set_assignment(ticket, team, user, *, actor=None, origin="UI", reason="") -> None:
    old = {"team": ticket.team.name if ticket.team_id else None, "assignee": ticket.assignee_id}
    ticket.team, ticket.assignee = team, user
    now = timezone.now()
    if user and ticket.status in (S.NEW, S.QUALIFIED):
        ticket.status, ticket.assigned_at = S.ASSIGNED, now
        ticket.qualified_at = ticket.qualified_at or now
    elif team and ticket.status == S.NEW:
        ticket.status, ticket.qualified_at = S.QUALIFIED, now
    ticket.save()
    log_event(ticket, "assigned", actor=actor, origin=origin, old=old,
              new={"team": team.name if team else None, "assignee": user.pk if user else None, "reason": reason}, public=bool(user))
    if user:
        notify(ticket, [user.pk], f"Ticket {ticket.reference} vous est affecté", ticket.title)
        emit(ticket, "ticket.assigned")
    elif team:
        notify(ticket, _team_leads(team), f"Nouveau ticket {ticket.reference} pour {team.name}", ticket.title)


def assign(ticket, *, actor, team_id=None, assignee_id=None) -> dm.Ticket:
    """Affectation / réaffectation manuelle (droits et appartenance à l'équipe vérifiés)."""
    from django.contrib.auth import get_user_model

    if not ticket.is_open:
        raise TicketError("Ticket fermé : rouvrez-le avant de le réaffecter.", 409)
    team = dm.Team.objects.filter(pk=team_id, workspace_id=ticket.workspace_id).first() if team_id else ticket.team
    if team_id and not team:
        raise TicketError("Équipe introuvable dans ce workspace.")
    user = get_user_model().objects.filter(pk=assignee_id).first() if assignee_id else None
    if assignee_id and not user:
        raise TicketError("Agent introuvable.")
    self_take = user is not None and user.pk == actor.pk and team is not None and team.pk == ticket.team_id
    if not (can_assign(actor, ticket) or (self_take and can_work(actor, ticket))):
        raise TicketError("Vous n'avez pas le droit d'affecter ce ticket.", 403)
    if user and (not team or not is_eligible_agent(user, team)):
        raise TicketError("Cet agent n'est pas un membre actif de l'équipe ou n'a pas de droit sur les tickets.")
    _set_assignment(ticket, team, user, actor=actor, reason="Affectation manuelle")
    return ticket


# ─── Workflow ────────────────────────────────────────────────────────────────

TRANSITIONS = {
    S.NEW: {S.QUALIFIED, S.ASSIGNED, S.CANCELLED},
    S.QUALIFIED: {S.ASSIGNED, S.CANCELLED},
    S.ASSIGNED: {S.IN_PROGRESS, S.WAITING, S.RESOLVED, S.QUALIFIED, S.CANCELLED},
    S.IN_PROGRESS: {S.WAITING, S.RESOLVED, S.CANCELLED},
    S.WAITING: {S.IN_PROGRESS, S.RESOLVED, S.CANCELLED},
    S.RESOLVED: {S.CLOSED, S.IN_PROGRESS},
    S.CLOSED: {S.QUALIFIED},
    S.CANCELLED: set(),
}
MANAGER_ONLY = {S.QUALIFIED, S.CANCELLED, S.CLOSED}
WEBHOOK_FOR = {S.RESOLVED: "ticket.resolved", S.CLOSED: "ticket.closed"}


def allowed_transitions(ticket, user) -> list[str]:
    manager = can_manage(user, ticket)
    if not (manager or can_work(user, ticket)):
        return []
    out = []
    for target in TRANSITIONS.get(ticket.status, set()):
        if target in MANAGER_ONLY and not manager:
            continue
        if target in (S.ASSIGNED, S.IN_PROGRESS) and not ticket.assignee_id:
            continue
        out.append(target)
    return sorted(out, key=list(S.values).index)


def transition(ticket, to: str, *, actor=None, origin: str = "UI", note: str = "", actor_label: str = "") -> dm.Ticket:
    if to not in TRANSITIONS.get(ticket.status, set()):
        raise TicketError(f"Transition impossible : {ticket.get_status_display()} → {dict(S.choices).get(to, to)}.", 409)
    if actor is not None and to not in allowed_transitions(ticket, actor):
        raise TicketError("Vous n'avez pas le droit d'effectuer cette transition.", 403)
    if to == S.CANCELLED and not note.strip():
        raise TicketError("Indiquez le motif d'annulation.")
    now, old = timezone.now(), ticket.status
    reopened = old in (S.RESOLVED, S.CLOSED)
    if old == S.WAITING and ticket.sla_paused_at:  # reprise du SLA : décalage des échéances
        paused = now - ticket.sla_paused_at
        ticket.sla_paused_seconds += int(paused.total_seconds())
        if ticket.resolution_due:
            ticket.resolution_due += paused
        if ticket.first_response_due and not ticket.first_response_at:
            ticket.first_response_due += paused
        ticket.sla_paused_at = None
    ticket.status = to
    if to == S.WAITING:
        ticket.sla_paused_at = now
    if to in (S.IN_PROGRESS, S.WAITING, S.RESOLVED) and not ticket.first_response_at and origin not in ("API", "EMAIL"):
        ticket.first_response_at = now
    if to == S.QUALIFIED:
        ticket.qualified_at = ticket.qualified_at or now
        if reopened:
            ticket.assignee = None
    if to == S.RESOLVED:
        ticket.resolved_at = now
    if to == S.CLOSED:
        ticket.closed_at = now
    if to == S.CANCELLED:
        ticket.cancelled_at = now
    if reopened:
        ticket.reopened_count += 1
        ticket.resolved_at = ticket.closed_at = None
        ticket.resolution_breached, ticket.sla_warning_sent = False, False
        ticket.sla_policy = ticket.sla_policy or policy_for(ticket.application)
        apply_sla(ticket, now)
    ticket.save()
    log_event(ticket, "status_changed", actor=actor, actor_label=actor_label, origin=origin,
              old={"status": old}, new={"status": to, "note": note[:500]}, public=True)
    if note.strip() and to in (S.RESOLVED, S.CANCELLED, S.WAITING):
        note_comment = dm.TicketComment.objects.create(ticket=ticket, author=actor, body=note.strip(), visibility="PUBLIC",
                                                       author_external_name=actor_label if actor is None else "")
        _email_reply(ticket, note_comment)
    emit(ticket, "ticket.reopened" if reopened else WEBHOOK_FOR.get(to, "ticket.updated"))
    targets = {ticket.assignee_id} - ({actor.pk} if actor else set())
    if targets:
        notify(ticket, targets, f"{ticket.reference} : {ticket.get_status_display()}", ticket.title)
    return ticket


def update_fields(ticket, *, actor, data: dict) -> dm.Ticket:
    """Qualification : priorité, catégorie, gravité, projet (gestionnaires)."""
    if not can_manage(actor, ticket):
        raise TicketError("Vous n'avez pas le droit de qualifier ce ticket.", 403)
    changes = {}
    for field, choices in (("priority", T.Priority), ("category", T.Category), ("severity", T.Severity)):
        value = data.get(field)
        if value is not None and value != getattr(ticket, field):
            if value not in choices.values:
                raise TicketError(f"Valeur invalide pour {field}.")
            changes[field] = (getattr(ticket, field), value)
            setattr(ticket, field, value)
    if "project" in data:
        pid = data.get("project")
        project = dm.Project.objects.filter(pk=pid, workspace_id=ticket.workspace_id).first() if pid else None
        if pid and not project:
            raise TicketError("Projet introuvable dans ce workspace.")
        changes["project"] = (ticket.project_id, project.pk if project else None)
        ticket.project = project
    if not changes:
        return ticket
    if "priority" in changes and ticket.is_open:
        apply_sla(ticket, ticket.created_at)
    ticket.save()
    log_event(ticket, "updated", actor=actor, old={k: v[0] for k, v in changes.items()},
              new={k: v[1] for k, v in changes.items()}, public="priority" in changes)
    emit(ticket, "ticket.updated")
    return ticket


def add_comment(ticket, *, body: str, visibility: str = "PUBLIC", user=None, external: dict | None = None,
                files=(), origin: str | None = None) -> dm.TicketComment:
    body = (body or "").strip()
    if not body:
        raise TicketError("Le commentaire est vide.")
    if len(body) > 10_000:
        raise TicketError("Commentaire trop long (10 000 caractères maximum).")
    if visibility not in ("PUBLIC", "INTERNAL") or (external and visibility != "PUBLIC"):
        raise TicketError("Visibilité invalide.")
    if user is not None and not can_work(user, ticket) and not (
            visibility == "PUBLIC" and (can_manage(user, ticket) or ticket.created_by_id == user.pk)):
        raise TicketError("Vous n'avez pas le droit de commenter ce ticket.", 403)
    ext = external or {}
    recent = dm.TicketComment.objects.filter(ticket=ticket, body=body, created_at__gte=timezone.now() - timedelta(seconds=60))
    recent = recent.filter(author=user) if user else recent.filter(author__isnull=True, author_external_id=str(ext.get("id") or ""))
    if recent.exists():
        raise TicketError("Commentaire identique déjà envoyé.", 409)
    max_mb = ticket.application.max_attachment_mb if external else int(getattr(settings, "TICKET_MAX_ATTACHMENT_MB", 20))
    for upload in files:
        validate_upload(upload, max_mb)
    with transaction.atomic():
        comment = dm.TicketComment.objects.create(
            ticket=ticket, author=user, body=body, visibility=visibility,
            author_external_id=str(ext.get("id") or "")[:120], author_external_name=str(ext.get("name") or "")[:150])
        for upload in files:
            _store_attachment(ticket, upload, visibility=visibility, user=user,
                              external="" if user else comment.author_external_name or ticket.application.name, comment=comment)
        if user and visibility == "PUBLIC" and not ticket.first_response_at:
            ticket.first_response_at = timezone.now()
            ticket.save(update_fields=["first_response_at", "updated_at"])
        log_event(ticket, "commented", actor=user, actor_label="" if user else (ext.get("name") or ticket.application.name),
                  origin=origin or ("UI" if user else "API"), new={"visibility": visibility}, public=visibility == "PUBLIC")
        if external:  # réponse du déclarant
            if ticket.status in (S.WAITING, S.RESOLVED):
                transition(ticket, S.IN_PROGRESS, origin=origin or "API", actor_label=ext.get("name") or ticket.application.name)
            notify(ticket, {ticket.assignee_id} if ticket.assignee_id else _team_leads(ticket.team),
                   f"Réponse du déclarant sur {ticket.reference}", body[:200])
        elif visibility == "PUBLIC":
            emit(ticket, "ticket.commented", {"comment": public_comment(comment)})
            _email_reply(ticket, comment)
    return comment


def _email_reply(ticket, comment) -> None:
    """Réponse publique d'un agent sur un ticket e-mail : envoi au déclarant par la boîte configurée."""
    if ticket.mailbox_id and ticket.reporter_email and comment.author_id:
        from project.services.ticketing_email import queue_agent_reply

        queue_agent_reply(ticket, comment)


def escalate(ticket, *, actor=None, reason: str = "", origin: str = "UI") -> dm.Ticket:
    if actor is not None and not can_manage(actor, ticket) and not can_work(actor, ticket):
        raise TicketError("Vous n'avez pas le droit d'escalader ce ticket.", 403)
    if not ticket.is_open:
        raise TicketError("Seul un ticket ouvert peut être escaladé.", 409)
    ticket.escalation_level += 1
    ticket.escalated_at = timezone.now()
    ticket.save(update_fields=["escalation_level", "escalated_at", "updated_at"])
    log_event(ticket, "escalated", actor=actor, origin=origin, new={"level": ticket.escalation_level, "reason": reason[:300]})
    policy_team = ticket.sla_policy.escalation_team if ticket.sla_policy_id else None
    recipients = _team_leads(ticket.team) | _team_leads(policy_team) | {ticket.workspace.owner_id}
    notify(ticket, recipients - ({actor.pk} if actor else set()),
           f"Escalade niveau {ticket.escalation_level} : {ticket.reference}", reason or ticket.title)
    emit(ticket, "ticket.updated")
    return ticket


# ─── Intégration DevFlow : tâches ────────────────────────────────────────────

TASK_PRIORITY = {"P1": "CRITICAL", "P2": "HIGH", "P3": "MEDIUM", "P4": "LOW"}


def create_task(ticket, *, actor, project_id=None) -> dm.Task:
    if not (can_manage(actor, ticket) or can_work(actor, ticket)):
        raise TicketError("Vous n'avez pas le droit de créer une tâche depuis ce ticket.", 403)
    if ticket.task_id:
        raise TicketError("Une tâche est déjà liée à ce ticket.", 409)
    project = (dm.Project.objects.filter(pk=project_id, workspace_id=ticket.workspace_id).first() if project_id
               else ticket.project or ticket.application.project)
    if not project or project.workspace_id != ticket.workspace_id:
        raise TicketError("Associez d'abord un projet DevFlow (ticket ou application).")
    task = dm.Task.objects.create(
        workspace_id=ticket.workspace_id, project=project, title=f"[{ticket.reference}] {ticket.title}"[:200],
        description=f"Créée depuis le ticket {ticket.reference} ({ticket.application.name}).\n\n{ticket.description}"[:5000],
        assignee=ticket.assignee, reporter=actor, priority=TASK_PRIORITY.get(ticket.priority, "MEDIUM"))
    ticket.task, ticket.project = task, project
    ticket.save(update_fields=["task", "project", "updated_at"])
    log_event(ticket, "task_created", actor=actor, new={"task": task.pk, "title": task.title})
    return task


def sync_from_task(task) -> None:
    """Tâche liée terminée → tickets ouverts résolus (sens unique : aucune boucle)."""
    if task.status != dm.Task.Status.DONE:
        return
    for ticket in dm.Ticket.objects.filter(task=task, status__in=[S.ASSIGNED, S.IN_PROGRESS, S.WAITING]):
        transition(ticket, S.RESOLVED, origin="SYSTEM", actor_label="Synchronisation tâche",
                   note=f"Résolu : tâche liée « {task.title} » terminée.")


# ─── Vues publiques (API d'intégration / webhooks) ──────────────────────────

def public_comment(c: dm.TicketComment) -> dict:
    return {"id": c.pk, "body": c.body, "created_at": c.created_at.isoformat(),
            "author": {"type": "agent", "name": "Support"} if c.author_id else
            {"type": "reporter", "id": c.author_external_id, "name": c.author_external_name}}


def public_ticket(ticket: dm.Ticket, *, history: bool = False) -> dict:
    data = {
        "reference": ticket.reference, "external_id": ticket.external_id, "title": ticket.title,
        "status": ticket.status, "status_label": ticket.get_status_display(), "category": ticket.category,
        "severity": ticket.severity, "priority": ticket.priority, "assigned": bool(ticket.assignee_id),
        "created_at": ticket.created_at.isoformat(), "updated_at": ticket.updated_at.isoformat(),
        "resolved_at": ticket.resolved_at.isoformat() if ticket.resolved_at else None,
        "closed_at": ticket.closed_at.isoformat() if ticket.closed_at else None,
    }
    if history:
        data["comments"] = [public_comment(c) for c in ticket.comments.filter(visibility="PUBLIC")]
        data["events"] = [{"action": e.action, "created_at": e.created_at.isoformat(),
                           "status": (e.new_value or {}).get("status")} for e in ticket.events.filter(is_public=True)]
        data["attachments"] = [{"id": a.pk, "name": a.original_name, "mime_type": a.mime_type, "size": a.size}
                               for a in ticket.attachments.filter(visibility="PUBLIC")]
    return data


# ─── Tâches périodiques ──────────────────────────────────────────────────────

def check_slas(now: datetime | None = None) -> dict:
    """Alertes avant dépassement, dépassements, escalade automatique (Celery beat)."""
    now = now or timezone.now()
    stats = {"warned": 0, "breached": 0}
    open_qs = dm.Ticket.objects.filter(status__in=T.OPEN_STATUSES, sla_paused_at__isnull=True).select_related(
        "sla_policy", "team", "workspace", "application")
    for ticket in open_qs.filter(Q(first_response_at__isnull=True, first_response_due__lt=now, first_response_breached=False)
                                 | Q(resolution_due__lt=now, resolution_breached=False)):
        kinds = []
        if not ticket.first_response_at and ticket.first_response_due and ticket.first_response_due < now and not ticket.first_response_breached:
            ticket.first_response_breached = True
            kinds.append("première réponse")
        if ticket.resolution_due and ticket.resolution_due < now and not ticket.resolution_breached:
            ticket.resolution_breached = True
            kinds.append("résolution")
        ticket.save(update_fields=["first_response_breached", "resolution_breached", "updated_at"])
        log_event(ticket, "sla_breached", origin="SYSTEM", new={"targets": kinds})
        stats["breached"] += 1
        if not ticket.sla_policy_id or ticket.sla_policy.auto_escalate:
            escalate(ticket, origin="SYSTEM", reason=f"SLA dépassé ({', '.join(kinds)})")
        else:
            notify(ticket, {ticket.assignee_id} | _team_leads(ticket.team), f"SLA dépassé : {ticket.reference}", ", ".join(kinds))
    for ticket in open_qs.filter(sla_warning_sent=False, resolution_breached=False, resolution_due__gt=now):
        warn = (ticket.sla_policy.warn_before_percent if ticket.sla_policy_id else 80) / 100
        total = (ticket.resolution_due - ticket.created_at).total_seconds() - ticket.sla_paused_seconds
        elapsed = (now - ticket.created_at).total_seconds() - ticket.sla_paused_seconds
        if total > 0 and elapsed / total >= warn:
            ticket.sla_warning_sent = True
            ticket.save(update_fields=["sla_warning_sent", "updated_at"])
            log_event(ticket, "sla_warning", origin="SYSTEM", new={"percent": round(elapsed * 100 / total)})
            notify(ticket, {ticket.assignee_id} | _team_leads(ticket.team), f"SLA bientôt dépassé : {ticket.reference}",
                   f"Échéance de résolution : {timezone.localtime(ticket.resolution_due):%d/%m %H:%M}")
            stats["warned"] += 1
    return stats


def purge_personal_data(now: datetime | None = None) -> int:
    """Conservation configurable : anonymise le déclarant des tickets clôturés au-delà de ``retention_days``."""
    now = now or timezone.now()
    count = 0
    for app in dm.ExternalApplication.objects.filter(retention_days__isnull=False):
        count += dm.Ticket.objects.filter(application=app, status__in=[S.CLOSED, S.CANCELLED],
                                          updated_at__lt=now - timedelta(days=app.retention_days)).exclude(
            reporter_name="", reporter_email="", reporter_external_id="").update(
            reporter_name="", reporter_email="", reporter_external_id="", metadata={})
    return count
