"""
Webhooks sortants du ticketing : signés HMAC, livrés hors transaction (Celery),
nouvelles tentatives avec backoff, protection SSRF, journal des livraisons.

Aucun webhook ne bloque une opération métier : la livraison est planifiée
après ``commit`` ; broker indisponible → reprise par le balayage périodique.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import socket
import time
from datetime import timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from project import models as dm

logger = logging.getLogger(__name__)

EVENTS = ["ticket.created", "ticket.assigned", "ticket.updated", "ticket.commented",
          "ticket.resolved", "ticket.closed", "ticket.reopened"]
BACKOFF_SECONDS = [60, 300, 1800, 7200, 43200]  # 1 min, 5 min, 30 min, 2 h, 12 h
MAX_ATTEMPTS = len(BACKOFF_SECONDS) + 1
D = dm.TicketWebhookDelivery.Status


class UnsafeDestination(Exception):
    pass


def check_destination(url: str) -> None:
    """HTTPS obligatoire (HTTP toléré en DEBUG) ; adresses privées, locales et réservées refusées."""
    parts = urlsplit(url or "")
    if parts.scheme != "https" and not (settings.DEBUG and parts.scheme == "http"):
        raise UnsafeDestination("Le webhook doit utiliser HTTPS.")
    if not parts.hostname:
        raise UnsafeDestination("URL de webhook invalide.")
    if getattr(settings, "TICKET_WEBHOOK_ALLOW_PRIVATE", False):
        return
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeDestination(f"Hôte introuvable : {parts.hostname}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise UnsafeDestination("Destination interdite (adresse privée ou locale).")


def sign(secret: str, timestamp: str, body: bytes) -> str:
    return hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


def _schedule(pk: int, countdown: int = 0) -> None:
    try:
        from project.tasks import deliver_ticket_webhook_task

        deliver_ticket_webhook_task.apply_async(args=[pk], countdown=countdown)
    except Exception:  # broker indisponible : retry_due() reprendra la livraison
        logger.warning("ticket webhook %s non planifié (broker indisponible)", pk, exc_info=True)


def enqueue(ticket, event: str, extra: dict | None = None):
    from project.services.ticketing import public_ticket

    app = ticket.application
    if not app.webhook_url or not app.is_active or (app.webhook_events and event not in app.webhook_events):
        return None
    now = timezone.now()
    delivery = dm.TicketWebhookDelivery.objects.create(
        application=app, ticket=ticket, event=event, destination=app.webhook_url, next_attempt_at=now, payload={})
    delivery.payload = {"id": str(delivery.event_id), "event": event, "created_at": now.isoformat(),
                        "ticket": public_ticket(ticket), **(extra or {})}
    delivery.save(update_fields=["payload"])
    transaction.on_commit(lambda: _schedule(delivery.pk))
    return delivery


def deliver(pk: int) -> str:
    """Une tentative de livraison ; replanifie avec backoff en cas d'échec."""
    import requests

    from project.services.ticketing import get_secret

    with transaction.atomic():
        d = (dm.TicketWebhookDelivery.objects.select_for_update().select_related("application").filter(pk=pk).first())
        if d is None or d.status in (D.SUCCESS, D.DEAD):
            return "skip"
        if d.next_attempt_at and d.next_attempt_at > timezone.now() + timedelta(seconds=5):
            return "not-due"
        d.attempt += 1
        body = json.dumps(d.payload, separators=(",", ":"), default=str).encode()
        timestamp = str(int(time.time()))
        headers = {
            "Content-Type": "application/json", "User-Agent": "DevFlow-Webhooks/1.0",
            "X-DevFlow-Event": d.event, "X-DevFlow-Event-Id": str(d.event_id), "X-DevFlow-Delivery-Attempt": str(d.attempt),
            "X-DevFlow-Timestamp": timestamp, "X-DevFlow-Signature": f"sha256={sign(get_secret(d.application), timestamp, body)}",
        }
        ok = False
        try:
            check_destination(d.destination)
            response = requests.post(d.destination, data=body, headers=headers, timeout=(3, 10), allow_redirects=False)
            d.response_status, d.response_excerpt = response.status_code, (response.text or "")[:300]
            ok = 200 <= response.status_code < 300
            d.error = "" if ok else f"HTTP {response.status_code}"
        except UnsafeDestination as exc:
            d.status, d.error, d.next_attempt_at = D.DEAD, str(exc)[:300], None
            d.save()
            return "dead"
        except requests.RequestException as exc:
            d.error = f"{type(exc).__name__}: {exc}"[:300]
        if ok:
            d.status, d.delivered_at, d.next_attempt_at = D.SUCCESS, timezone.now(), None
        elif d.attempt >= MAX_ATTEMPTS:
            d.status, d.next_attempt_at = D.DEAD, None
        else:
            delay = BACKOFF_SECONDS[d.attempt - 1]
            d.status, d.next_attempt_at = D.FAILED, timezone.now() + timedelta(seconds=delay)
        d.save()
    if d.status == D.FAILED:
        transaction.on_commit(lambda: _schedule(d.pk, BACKOFF_SECONDS[d.attempt - 1]))
    return d.status.lower()


def retry_due(now=None) -> int:
    """Balayage périodique : livraisons dues non traitées (broker perdu, redémarrage)."""
    now = now or timezone.now()
    due = dm.TicketWebhookDelivery.objects.filter(status__in=[D.PENDING, D.FAILED], next_attempt_at__lte=now - timedelta(minutes=2))
    ids = list(due.values_list("pk", flat=True)[:200])
    for pk in ids:
        _schedule(pk)
    return len(ids)


def retry_now(delivery) -> None:
    """Relance manuelle (administrateur) d'une livraison en échec ou abandonnée."""
    delivery.status, delivery.next_attempt_at = D.PENDING, timezone.now()
    if delivery.attempt >= MAX_ATTEMPTS:
        delivery.attempt = MAX_ATTEMPTS - 1
    delivery.save(update_fields=["status", "next_attempt_at", "attempt", "updated_at"])
    transaction.on_commit(lambda: _schedule(delivery.pk))
