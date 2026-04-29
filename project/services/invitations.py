"""
Service d'invitation workspace : génération de liens publics et envoi d'email.
"""

from __future__ import annotations

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse


def build_invitation_url(invitation, request=None) -> str:
    """Construit l'URL absolue d'acceptation depuis la requête (host correct)."""
    path = reverse("workspace_invitation_public_accept", args=[invitation.token])
    if request is not None:
        return request.build_absolute_uri(path)
    base = getattr(settings, "SITE_URL", "http://localhost:8000").rstrip("/")
    return f"{base}{path}"


def send_invitation_email(invitation, request=None) -> bool:
    """Envoie l'email d'invitation. Retourne True si envoyé, False sinon."""
    if not invitation.email:
        return False

    accept_url = build_invitation_url(invitation, request=request)
    subject = f"[DevFlow] Vous êtes invité·e à rejoindre {invitation.workspace.name}"

    context = {
        "invitation": invitation,
        "workspace": invitation.workspace,
        "team": invitation.team,
        "invited_by": invitation.invited_by,
        "role_label": invitation.get_role_display(),
        "accept_url": accept_url,
        "expires_at": invitation.expires_at,
    }

    try:
        message_txt = render_to_string("emails/workspace_invitation.txt", context)
    except Exception:
        message_txt = (
            f"Bonjour,\n\n"
            f"{invitation.invited_by or 'Un collaborateur'} vous invite à rejoindre "
            f"le workspace {invitation.workspace.name} sur DevFlow en tant que "
            f"{invitation.get_role_display()}.\n\n"
            f"Cliquez ici pour accepter : {accept_url}\n\n"
            f"L'invitation expire le {invitation.expires_at:%d/%m/%Y}.\n"
        )

    try:
        message_html = render_to_string("emails/workspace_invitation.html", context)
    except Exception:
        message_html = None

    sent = send_mail(
        subject=subject,
        message=message_txt,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[invitation.email],
        html_message=message_html,
        fail_silently=False,
    )
    return bool(sent)
