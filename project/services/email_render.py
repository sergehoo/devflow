"""
Construction des emails DevFlow « simples » (titre, message, détail, bouton)
au design commun templates/emails/notification.html, avec version texte.
"""

from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


def default_from_email() -> str:
    return (
        getattr(settings, "DEFAULT_FROM_EMAIL", None)
        or getattr(settings, "EMAIL_HOST_USER", None)
        or "noreply@devflow.local"
    )


def devflow_email(
    *, subject, title, intro, to=None, bcc=None, details="", eyebrow="Notification",
    subtitle="", badge="", critical=False, cta_url="", cta_label="Ouvrir DevFlow",
) -> EmailMultiAlternatives:
    html = render_to_string("emails/notification.html", {
        "subject": subject, "title": title, "intro": intro, "details": details,
        "eyebrow": eyebrow, "subtitle": subtitle, "badge": badge, "critical": critical,
        "cta_url": cta_url, "cta_label": cta_label,
    })
    text = "\n\n".join(part for part in (
        intro, details, f"{cta_label} : {cta_url}" if cta_url else "", "— DevFlow",
    ) if part)
    message = EmailMultiAlternatives(
        subject=subject, body=text, from_email=default_from_email(), to=to or [], bcc=bcc or [],
    )
    message.attach_alternative(html, "text/html")
    return message
