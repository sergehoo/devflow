"""
Réinitialisation du mot de passe d'un membre par un administrateur du workspace.

Deux modes, tous deux par lien sécurisé (jamais de mot de passe en clair) :
  * ``link``  — envoie un lien de réinitialisation ; l'ancien mot de passe reste
                valable tant que le membre n'en a pas choisi un nouveau ;
  * ``force`` — invalide immédiatement l'ancien mot de passe (sessions ouvertes
                déconnectées) puis envoie le lien pour en créer un nouveau.

Le lien réutilise le flux allauth (``account_reset_password_from_key``) :
jeton à usage unique, lié au hash du mot de passe et à l'email, expirant après
``PASSWORD_RESET_TIMEOUT``.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse

from project import models as dm

logger = logging.getLogger(__name__)

MODE_LINK = "link"
MODE_FORCE = "force"
THROTTLE_SECONDS = 60


class PasswordResetError(Exception):
    """Demande refusée (droits, cible invalide, anti-spam)."""


def can_manage_passwords(actor, workspace) -> bool:
    from project.services.rbac import RBACService

    return bool(workspace) and RBACService.can(actor, "members.manage", workspace=workspace)


def check_target(actor, target, workspace) -> None:
    if not can_manage_passwords(actor, workspace):
        raise PasswordResetError("Vous n'avez pas le droit de réinitialiser les mots de passe.")
    if target.pk == actor.pk:
        raise PasswordResetError("Utilisez « Mon profil » pour changer votre propre mot de passe.")
    if not target.is_active:
        raise PasswordResetError("Compte non activé : renvoyez plutôt l'invitation.")
    if not target.email:
        raise PasswordResetError("Ce membre n'a pas d'adresse email.")
    if target.is_superuser and not actor.is_superuser:
        raise PasswordResetError("Le mot de passe d'un super-administrateur ne peut pas être réinitialisé ici.")
    if workspace.owner_id == target.pk and not actor.is_superuser:
        raise PasswordResetError("Le mot de passe du propriétaire du workspace ne peut pas être réinitialisé ici.")


def build_reset_url(user, request) -> str:
    from allauth.account.forms import default_token_generator
    from allauth.account.utils import user_pk_to_url_str

    path = reverse(
        "account_reset_password_from_key",
        kwargs={"uidb36": user_pk_to_url_str(user), "key": default_token_generator.make_token(user)},
    )
    return request.build_absolute_uri(path)


def request_member_password_reset(*, actor, target, workspace, request, mode=MODE_LINK) -> None:
    """Vérifie les droits, applique le mode puis planifie l'email (Celery)."""
    if mode not in (MODE_LINK, MODE_FORCE):
        raise PasswordResetError("Mode de réinitialisation inconnu.")
    check_target(actor, target, workspace)
    if not cache.add(f"member-pwd-reset:{target.pk}", 1, THROTTLE_SECONDS):
        raise PasswordResetError("Un lien vient déjà d'être envoyé à ce membre. Réessayez dans une minute.")

    if mode == MODE_FORCE:
        target.set_unusable_password()
        target.save(update_fields=["password"])

    reset_url = build_reset_url(target, request)  # après le changement : jeton lié au nouvel état

    from project.services.security_audit import SecurityAuditService

    SecurityAuditService.log(
        event_type=dm.SecurityAuditLog.EventType.UPDATE,
        action=f"member.password_reset.{mode}",
        user=actor, workspace=workspace, target=target, request=request,
        severity=(
            dm.SecurityAuditLog.Severity.WARNING if mode == MODE_FORCE
            else dm.SecurityAuditLog.Severity.INFO
        ),
        metadata={"target_user_id": target.pk, "mode": mode},
    )

    from project.tasks import send_member_password_reset_email_task

    try:
        send_member_password_reset_email_task.delay(
            target.pk, reset_url, mode == MODE_FORCE,
            actor.get_full_name() or actor.get_username(), workspace.name,
        )
    except Exception as exc:
        logger.exception("Password reset email enqueue failed for user %s", target.pk)
        raise PasswordResetError(
            "Lien généré mais l'email n'a pas pu être planifié (file Celery indisponible)."
        ) from exc


def reset_link_validity_hours() -> int:
    return max(1, int(getattr(settings, "PASSWORD_RESET_TIMEOUT", 86400)) // 3600)
