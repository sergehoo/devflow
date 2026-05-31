"""
Service d'invitation workspace : génération de liens publics et envoi d'email.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.urls import reverse

logger = logging.getLogger(__name__)


def build_invitation_url(invitation, request=None) -> str:
    """Construit l'URL absolue d'acceptation depuis la requête (host correct)."""
    path = reverse("workspace_invitation_public_accept", args=[invitation.token])
    if request is not None:
        return request.build_absolute_uri(path)
    base = getattr(settings, "SITE_URL", "http://localhost:8000").rstrip("/")
    return f"{base}{path}"


def send_invitation_email(invitation, request=None) -> bool:
    """
    Planifie l'envoi de l'email d'invitation via Celery (Phase 0).

    L'URL d'acceptation est calculée ICI (côté requête HTTP) pour avoir le
    bon host (`request.build_absolute_uri`), puis passée à la task qui
    fait l'envoi SMTP en arrière-plan — la requête HTTP n'est plus bloquée.

    Retourne :
      * True  : la task a été planifiée correctement
      * False : pas d'email destinataire, ou échec définitif du planning
    """
    if not invitation.email:
        return False

    accept_url = build_invitation_url(invitation, request=request)

    # Import local pour éviter tout cycle d'import au démarrage.
    try:
        from project.tasks import send_invitation_email_task

        send_invitation_email_task.delay(invitation.pk, accept_url)
        return True
    except Exception as exc:
        logger.exception(
            "Failed to enqueue invitation email for invitation %s: %s",
            invitation.pk, exc,
        )
        return False
