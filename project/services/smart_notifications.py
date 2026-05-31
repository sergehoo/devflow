"""
DevFlow — Service Notifications intelligentes (Phase 5, PR21).

Trois services :

  1. NotificationPreferenceService.get_or_create(user)
     Auto-seed des préférences au premier usage.

  2. SmartNotificationDispatcher.dispatch(notification)
     Décide en temps réel :
       * doit-on envoyer un email maintenant (canal + quiet hours + frequency) ?
       * doit-on attendre le prochain digest ?
       * faut-il regrouper avec d'autres notifs en attente ?

  3. NotificationDigestBuilder.build_for(user, frequency, period_start, period_end)
     Construit le payload du digest (top types, top projets, top actions).
     Utilisé par la tâche Celery quotidienne.

Aucun appel IA — purement déterministe.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from project import models as dm

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Service 1 — Préférences
# ---------------------------------------------------------------------------
class NotificationPreferenceService:
    @classmethod
    def get_or_create(cls, user) -> dm.NotificationPreference:
        prefs, _ = dm.NotificationPreference.objects.get_or_create(user=user)
        return prefs


# ---------------------------------------------------------------------------
# Service 2 — Dispatcher temps réel
# ---------------------------------------------------------------------------
class SmartNotificationDispatcher:
    """
    Décide quoi faire d'une Notification fraîchement créée :
      * In-app : toujours créée (c'est déjà fait par le caller)
      * Email immédiat : ssi channel_email=True ET frequency=IMMEDIATE
                         ET pas en quiet hours (sauf priority_type)
      * Sinon : on laisse le digest accumuler — pas d'action ici.

    À appeler depuis le signal post_save Notification ou côté
    notify_task_assignment / notify_pm_task_overdue.
    """

    @classmethod
    def should_send_email_now(
        cls,
        notification: dm.Notification,
        *,
        now: datetime | None = None,
    ) -> bool:
        user = getattr(notification, "recipient", None)
        if user is None or not getattr(user, "email", None):
            return False

        prefs = NotificationPreferenceService.get_or_create(user)

        # Désactivé globalement
        if prefs.notify_frequency == "DISABLED":
            return False

        # Canal email coupé
        if not prefs.channel_email:
            return False

        # Type prioritaire → bypass tout (quiet hours, frequency)
        notif_type = getattr(notification, "notification_type", "")
        priority_types = prefs.priority_types or []
        if notif_type in priority_types:
            return True

        # En mode HOURLY/DAILY → on laisse le digest s'en charger
        if prefs.notify_frequency in ("HOURLY", "DAILY"):
            return False

        # IMMEDIATE → respecte les quiet hours
        if prefs.is_quiet_hour(now=now or timezone.localtime()):
            return False

        return True


# ---------------------------------------------------------------------------
# Service 3 — Builder de digest
# ---------------------------------------------------------------------------
class NotificationDigestBuilder:
    """
    Construit le payload du digest pour un user, sur une période donnée.

    Payload structuré (JSON) :
      {
        "user_id": ..., "frequency": "DAILY",
        "period_start": "...", "period_end": "...",
        "total": 27,
        "by_type": [{"type": "TASK", "count": 12, "label": "Tâches"}, ...],
        "by_project": [{"project_id": 1, "name": "X", "count": 8}, ...],
        "highlights": [
          {"title": "Tâche assignée : ...", "url": "/tasks/42/"}, ...
        ]
      }

    Volontairement compact : conçu pour rentrer dans un email court ou une
    page récap. Les highlights sont les 5 notifications les plus récentes
    parmi les non-lues.
    """

    MAX_HIGHLIGHTS = 5
    MAX_TYPES = 6
    MAX_PROJECTS = 5

    @classmethod
    def build_for(
        cls,
        user,
        *,
        period_start: datetime,
        period_end: datetime,
        frequency: str = "DAILY",
        include_read: bool = False,
    ) -> dict:
        qs = dm.Notification.objects.filter(
            recipient=user,
            created_at__gte=period_start,
            created_at__lt=period_end,
        )
        if not include_read:
            qs = qs.filter(is_read=False)
        qs = qs.select_related("workspace").order_by("-created_at")

        notifications = list(qs)
        total = len(notifications)

        # Par type
        type_counts = Counter(n.notification_type for n in notifications)
        type_labels = dict(dm.Notification.NotificationType.choices)
        by_type = [
            {
                "type": t,
                "label": type_labels.get(t, t),
                "count": c,
            }
            for t, c in type_counts.most_common(cls.MAX_TYPES)
        ]

        # Par projet (via metadata.project_id quand présent)
        project_counts: dict[int, int] = defaultdict(int)
        for n in notifications:
            md = n.metadata or {}
            pid = md.get("project_id")
            if pid:
                try:
                    project_counts[int(pid)] += 1
                except (TypeError, ValueError):
                    continue

        # Résout les noms en 1 seule requête
        project_names = {}
        if project_counts:
            project_names = dict(
                dm.Project.objects.filter(pk__in=project_counts.keys())
                .values_list("pk", "name")
            )
        by_project = sorted(
            ({"project_id": pid, "name": project_names.get(pid, "—"), "count": c}
             for pid, c in project_counts.items()),
            key=lambda r: -r["count"],
        )[:cls.MAX_PROJECTS]

        # Highlights : 5 plus récentes
        highlights = [
            {
                "title": n.title,
                "body": (n.body or "")[:140],
                "type": n.notification_type,
                "url": n.url,
                "created_at": n.created_at.isoformat(),
            }
            for n in notifications[:cls.MAX_HIGHLIGHTS]
        ]

        return {
            "user_id": user.pk,
            "frequency": frequency,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "total": total,
            "by_type": by_type,
            "by_project": by_project,
            "highlights": highlights,
        }

    @classmethod
    def persist(
        cls,
        user,
        payload: dict,
        *,
        period_start: datetime,
        period_end: datetime,
        frequency: str = "DAILY",
    ) -> dm.NotificationDigest:
        return dm.NotificationDigest.objects.create(
            user=user,
            frequency=frequency,
            period_start=period_start,
            period_end=period_end,
            notifications_count=payload.get("total", 0),
            payload=payload,
        )


# ---------------------------------------------------------------------------
# Helper : envoi email digest (utilisé par la tâche Celery)
# ---------------------------------------------------------------------------
def send_digest_email_sync(user, digest: dm.NotificationDigest) -> bool:
    """
    Envoi synchrone de l'email digest. Appelé depuis une tâche Celery —
    on est déjà hors-requête HTTP, donc OK.

    Retourne True si l'email a été envoyé.
    """
    from django.conf import settings
    from django.core.mail import send_mail
    from django.template.loader import render_to_string

    if not user.email or digest.notifications_count == 0:
        return False

    ctx = {
        "user": user,
        "digest": digest,
        "payload": digest.payload,
        "site_url": getattr(settings, "SITE_URL", "").rstrip("/"),
    }
    subject = f"[Dev'Flow] Récap {digest.payload.get('total', 0)} notification(s)"

    try:
        message_txt = render_to_string("emails/notification_digest.txt", ctx)
    except Exception:
        # Fallback texte brut si template absent (probable au premier déploiement)
        highlights = "\n".join(
            f"- {h['title']}" for h in digest.payload.get("highlights", [])
        )
        message_txt = (
            f"Bonjour {user.first_name or user.username},\n\n"
            f"Récapitulatif de {digest.notifications_count} notification(s) "
            f"de la période :\n\n{highlights}\n\n"
            f"Voir toutes vos notifications : "
            f"{getattr(settings, 'SITE_URL', '').rstrip('/')}/notifications/"
        )

    try:
        message_html = render_to_string("emails/notification_digest.html", ctx)
    except Exception:
        message_html = None

    sent = send_mail(
        subject=subject,
        message=message_txt,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[user.email],
        html_message=message_html,
        fail_silently=True,
    )
    if sent:
        digest.sent_at = timezone.now()
        digest.sent_via_email = True
        digest.save(update_fields=["sent_at", "sent_via_email", "updated_at"])
        return True
    return False
