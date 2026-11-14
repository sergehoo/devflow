"""
Collecte de tickets SANS API côté application : formulaire existant (SDK JS),
widget « Signaler un problème » (balise script) et formulaire public hébergé
(``/support/app/<slug>/``). Même cœur de création que l'API, la saisie et l'e-mail
(``ticketing._create``) : numérotation, SLA, routage, notifications, webhooks.

Sécurité (aucun secret dans le navigateur) :
* **clé publique** ``dfp_…`` limitée à la soumission : elle identifie l'application,
  ne donne aucun accès en lecture et peut être renouvelée ;
* **jeton de formulaire** signé (``TimestampSigner``) délivré à l'affichage : âge
  minimum (3 s, anti-robot), maximum (2 h), usage unique (anti-rejeu) ;
* **origine** : formulaire existant et widget uniquement depuis les domaines
  autorisés (contrôle serveur de l'en-tête ``Origin`` — CORS seul ne protège pas) ;
* **anti-abus** : champ piège, débits par IP et par application, quota journalier
  existant, doublons (même déclarant + même objet sous 30 min → référence existante) ;
* **suivi** : référence + code de suivi remis une seule fois (empreinte SHA-256
  stockée) ; seul le fil PUBLIC est consultable, tentatives limitées par IP.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import uuid
from datetime import timedelta
from urllib.parse import urlsplit

from django.core import signing
from django.core.cache import cache
from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from django.utils.html import strip_tags

from project import models as dm
from project.services import ticketing as svc

logger = logging.getLogger("devflow.ticketing")
T = dm.Ticket
MODES = ("api", "form", "widget", "hosted")
BROWSER_MODES = ("form", "widget", "hosted")
SOURCE = {"form": T.Source.FORM, "widget": T.Source.WIDGET, "hosted": T.Source.PORTAL}
MODE_LABELS = {"api": "API REST", "form": "Formulaire existant", "widget": "Widget intégré", "hosted": "Formulaire public hébergé"}
TOKEN_SALT = "devflow.ticketing.public-form"
TOKEN_MIN_AGE, TOKEN_MAX_AGE = 3, 2 * 3600
MAX_FILES = 3
IP_WINDOW, IP_MAX = 600, 5            # soumissions par IP et par application / 10 min
IP_DAY_MAX = 30                       # soumissions par IP, toutes applications / 24 h
TRACK_WINDOW, TRACK_MAX = 600, 10     # tentatives de suivi par IP / 10 min
DUPLICATE_WINDOW = timedelta(minutes=30)


class PublicIntakeError(Exception):
    def __init__(self, message: str, status: int = 400, *, record: str = ""):
        super().__init__(message)
        self.message, self.status, self.record = message, status, record


# ─── Configuration de l'application ─────────────────────────────────────────

def modes(app: dm.ExternalApplication) -> dict:
    current = app.collection_modes or {}
    return {m: bool(current.get(m, m == "api")) for m in MODES}


def new_public_key() -> str:
    return f"dfp_{secrets.token_urlsafe(24)}"


def ensure_public_identity(app: dm.ExternalApplication) -> None:
    """Clé publique et adresse du formulaire attribuées au premier mode navigateur activé."""
    from django.utils.text import slugify

    if not app.public_key:
        app.public_key = new_public_key()
    if not app.public_slug:
        base = (slugify(f"{app.code}-{app.workspace_id}") or "app")[:70]
        slug, n = base, 1
        while dm.ExternalApplication.objects.filter(public_slug=slug).exclude(pk=app.pk).exists():
            n += 1
            slug = f"{base}-{n}"
        app.public_slug = slug


def normalize_origin(value: str) -> str | None:
    """``https://app.exemple.com[:port]`` (schéma + hôte), sinon ``None``."""
    parts = urlsplit((value or "").strip())
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.path not in ("", "/") or parts.query:
        return None
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{parts.hostname.lower()}{port}"


def origin_allowed(app: dm.ExternalApplication, origin: str) -> bool:
    origin = normalize_origin(origin or "")
    return bool(origin) and origin in {normalize_origin(o) for o in (app.allowed_origins or [])}


def record_error(app: dm.ExternalApplication, mode: str, reason: str) -> None:
    """Dernière erreur du canal (sans donnée personnelle), affichée dans « Modes de collecte »."""
    config = dict(app.config or {})
    errors = dict(config.get("intake_errors") or {})
    errors[mode] = {"at": timezone.now().isoformat(), "reason": reason[:200]}
    config["intake_errors"] = errors
    dm.ExternalApplication.objects.filter(pk=app.pk).update(config=config)


def app_for_key(public_key: str) -> dm.ExternalApplication | None:
    if not public_key or not public_key.startswith("dfp_") or len(public_key) > 48:
        return None
    return dm.ExternalApplication.objects.select_related("workspace").filter(public_key=public_key).first()


# ─── Jeton de formulaire ────────────────────────────────────────────────────

def issue_form_token(app: dm.ExternalApplication, mode: str) -> str:
    return signing.TimestampSigner(salt=TOKEN_SALT).sign(f"{app.pk}:{mode}:{uuid.uuid4().hex}")


def check_form_token(app: dm.ExternalApplication, mode: str, token: str) -> None:
    signer = signing.TimestampSigner(salt=TOKEN_SALT)
    try:
        value, issued = signer.unsign(token or "", max_age=TOKEN_MAX_AGE), None
    except signing.SignatureExpired:
        raise PublicIntakeError("Formulaire expiré : rechargez la page.", 400, record="jeton expiré")
    except signing.BadSignature:
        raise PublicIntakeError("Formulaire invalide : rechargez la page.", 400, record="jeton invalide")
    app_id, token_mode, _ = (value.split(":") + ["", "", ""])[:3]
    if app_id != str(app.pk) or token_mode != mode:
        raise PublicIntakeError("Formulaire invalide : rechargez la page.", 400, record="jeton d'une autre application")
    try:
        issued = signing.b62_decode(token.split(":")[-2])
    except Exception:  # format inattendu : déjà couvert par unsign
        issued = None
    if issued is not None and timezone.now().timestamp() - issued < TOKEN_MIN_AGE:
        raise PublicIntakeError("Envoi trop rapide : relisez votre signalement puis réessayez.", 400, record="envoi trop rapide (robot ?)")
    if not cache.add(f"ticketing:public:token:{hashlib.sha256(token.encode()).hexdigest()}", 1, TOKEN_MAX_AGE + 60):
        raise PublicIntakeError("Ce formulaire a déjà été envoyé.", 409, record="jeton réutilisé")


# ─── Débits ─────────────────────────────────────────────────────────────────

def _hit(key: str, window: int) -> int:
    cache.add(key, 0, window)
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, window)
        return 1


def _ip_hash(ip: str) -> str:
    return hashlib.sha256(f"devflow-public:{ip}".encode()).hexdigest()[:24]


# ─── Soumission ─────────────────────────────────────────────────────────────

def _clean(value, limit: int) -> str:
    return re.sub(r"[ \t]+\n", "\n", strip_tags(str(value or ""))).strip()[:limit]


def check_mode(app: dm.ExternalApplication, mode: str, origin: str) -> None:
    if mode not in BROWSER_MODES:
        raise PublicIntakeError("Mode de collecte inconnu.", 400)
    if not app.is_active or not modes(app)[mode]:
        raise PublicIntakeError("Ce formulaire n'est pas disponible.", 404, record="mode désactivé")
    if mode == "form" and not origin_allowed(app, origin):
        raise PublicIntakeError("Origine non autorisée pour cette application.", 403, record=f"origine refusée : {normalize_origin(origin) or 'absente'}")


def submit(app: dm.ExternalApplication, mode: str, data, files=(), *, ip: str, origin: str = "") -> dict:
    """
    Crée le ticket (ou renvoie la référence d'un doublon récent). ``data`` : QueryDict / dict.
    Renvoie ``{"reference", "status", "created", "tracking_code"?}`` — le code de suivi n'est
    remis qu'à la création (seule son empreinte est conservée).
    """
    check_mode(app, mode, origin)
    if (data.get("website") or "").strip():  # champ piège invisible pour un humain
        raise PublicIntakeError("Envoi refusé.", 400, record="champ piège rempli")
    if _hit(f"ticketing:public:ip:{app.pk}:{_ip_hash(ip)}", IP_WINDOW) > IP_MAX or \
            _hit(f"ticketing:public:ipday:{_ip_hash(ip)}", 86400) > IP_DAY_MAX:
        raise PublicIntakeError("Trop de signalements envoyés : réessayez plus tard.", 429, record="débit IP dépassé")
    check_form_token(app, mode, data.get("form_token") or "")

    title = _clean(data.get("title"), 200)
    description = _clean(data.get("description"), 10_000)
    if len(title) < 5:
        raise PublicIntakeError("Objet trop court (5 caractères minimum).", 400)
    email = (data.get("email") or "").strip()[:254]
    if email:
        try:
            validate_email(email)
        except DjangoValidationError:
            raise PublicIntakeError("Adresse e-mail invalide.", 400)
    if mode == "hosted" and not email:
        raise PublicIntakeError("Indiquez votre adresse e-mail pour être tenu informé.", 400)
    category = data.get("category") if data.get("category") in T.Category.values else T.Category.BUG
    severity = data.get("impact") if data.get("impact") in T.Severity.values else T.Severity.MINOR
    files = list(files)
    if len(files) > MAX_FILES:
        raise PublicIntakeError(f"{MAX_FILES} fichiers maximum.", 400)
    for upload in files:
        try:
            svc.validate_upload(upload, app.max_attachment_mb)
        except svc.TicketError as exc:
            raise PublicIntakeError(str(exc), 400)

    reporter_key = email.lower() or f"ip:{_ip_hash(ip)}"
    duplicate = T.objects.filter(
        application=app, status__in=T.OPEN_STATUSES, created_at__gte=timezone.now() - DUPLICATE_WINDOW,
        title__iexact=title, reporter_external_id=reporter_key[:120],
    ).order_by("-created_at").first()
    if duplicate:
        return {"reference": duplicate.reference, "status": duplicate.get_status_display(), "created": False}
    if T.objects.filter(application=app, created_at__gte=timezone.now() - timedelta(days=1)).count() >= app.daily_ticket_quota:
        raise PublicIntakeError("Le support ne peut pas recevoir de nouveau signalement aujourd'hui.", 429, record="quota journalier atteint")

    values = {
        "external_id": f"{mode}-{uuid.uuid4().hex[:20]}", "reporter_external_id": reporter_key[:120],
        "reporter_name": _clean(data.get("name"), 150), "reporter_email": email, "title": title, "description": description,
        "category": category, "severity": severity, "url": svc.sanitize_url(data.get("page_url") or ""),
        "app_version": _clean(data.get("app_version"), 40),
        "metadata": svc.bounded_metadata({"channel": mode, "language": _clean(data.get("language"), 20),
                                           "viewport": _clean(data.get("viewport"), 20)}),
    }
    ticket = svc._create(app, values, files=files, source=SOURCE[mode], origin="PUBLIC",
                         actor_label=values["reporter_name"] or MODE_LABELS[mode], attach_external=values["reporter_name"] or "Déclarant")
    code = secrets.token_urlsafe(9)
    T.objects.filter(pk=ticket.pk).update(public_token_hash=hashlib.sha256(code.encode()).hexdigest())
    logger.info("public intake: ticket %s created via %s for app %s", ticket.reference, mode, app.pk)
    return {"reference": ticket.reference, "status": ticket.get_status_display(), "created": True, "tracking_code": code}


# ─── Suivi par le déclarant ─────────────────────────────────────────────────

def track(app: dm.ExternalApplication, reference: str, code: str, *, ip: str) -> dict:
    if _hit(f"ticketing:public:track:{_ip_hash(ip)}", TRACK_WINDOW) > TRACK_MAX:
        raise PublicIntakeError("Trop de tentatives : réessayez dans quelques minutes.", 429)
    ticket = T.objects.filter(application=app, reference=(reference or "").strip().upper()[:20]).first()
    expected = ticket.public_token_hash if ticket else ""
    given = hashlib.sha256((code or "").strip().encode()).hexdigest()
    if not ticket or not expected or not hmac.compare_digest(expected, given):
        raise PublicIntakeError("Référence ou code de suivi incorrect.", 404)
    comments = ticket.comments.filter(visibility="PUBLIC").order_by("created_at")
    return {
        "reference": ticket.reference, "title": ticket.title, "status": ticket.status, "status_label": ticket.get_status_display(),
        "created_at": ticket.created_at.isoformat(), "updated_at": ticket.updated_at.isoformat(),
        "messages": [{"from": "Vous" if c.author_id is None else "Support", "body": c.body, "created_at": c.created_at.isoformat()}
                     for c in comments],
    }


# ─── Tableau de bord des canaux ─────────────────────────────────────────────

def channel_status(app: dm.ExternalApplication) -> dict:
    current = modes(app)
    errors = (app.config or {}).get("intake_errors") or {}
    sources = {"api": T.Source.API, **SOURCE}
    out = {}
    for mode in MODES:
        last = T.objects.filter(application=app, source=sources[mode]).order_by("-created_at").first()
        out[mode] = {
            "enabled": current[mode], "label": MODE_LABELS[mode],
            "last_ticket": {"id": last.pk, "reference": last.reference, "created_at": last.created_at.isoformat()} if last else None,
            "count_30d": T.objects.filter(application=app, source=sources[mode], created_at__gte=timezone.now() - timedelta(days=30)).count(),
            "last_error": errors.get(mode),
        }
    mailboxes = list(app.mailboxes.values("id", "address", "is_active", "last_success_at", "last_error"))
    last_mail = T.objects.filter(application=app, source=T.Source.EMAIL).order_by("-created_at").first()
    out["email"] = {
        "enabled": any(m["is_active"] for m in mailboxes), "label": "E-mail", "mailboxes": mailboxes,
        "last_ticket": {"id": last_mail.pk, "reference": last_mail.reference, "created_at": last_mail.created_at.isoformat()} if last_mail else None,
        "last_error": next(({"reason": m["last_error"]} for m in mailboxes if m["last_error"]), None),
    }
    return out
