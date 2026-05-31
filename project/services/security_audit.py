"""
DevFlow — Service d'audit sécurité (PR24).

API publique :
    SecurityAuditService.log(
        event_type, action,
        user=None, workspace=None,
        target=None, request=None,
        severity="INFO", success=True, metadata=None, error_message="",
    )

Capture les événements critiques pour traçabilité et conformité.
Best-effort : ne lève jamais — un échec d'audit ne doit pas casser
l'opération métier en cours.
"""

from __future__ import annotations

import logging
from typing import Any

from django.contrib.auth.signals import (
    user_logged_in,
    user_logged_out,
    user_login_failed,
)
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from project import models as dm

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Service principal
# ---------------------------------------------------------------------------
class SecurityAuditService:
    """API centrale pour logger un événement de sécurité."""

    @classmethod
    def log(
        cls,
        event_type: str,
        action: str,
        *,
        user=None,
        workspace=None,
        target=None,
        request=None,
        severity: str = "INFO",
        success: bool = True,
        metadata: dict | None = None,
        error_message: str = "",
    ) -> dm.SecurityAuditLog | None:
        try:
            # Infos target
            target_type = ""
            target_id = None
            target_repr = ""
            if target is not None:
                target_type = type(target).__name__
                target_id = getattr(target, "pk", None) or getattr(target, "id", None)
                target_repr = str(target)[:200]

            # Workspace inféré du target si non fourni
            if workspace is None and target is not None:
                workspace = getattr(target, "workspace", None)
                if workspace is None:
                    for attr in ("project", "team", "task", "sprint"):
                        related = getattr(target, attr, None)
                        if related and getattr(related, "workspace", None):
                            workspace = related.workspace
                            break

            # Infos request
            ip = ua = path = method = ""
            if request is not None:
                ip = cls._get_client_ip(request) or ""
                ua = (request.META.get("HTTP_USER_AGENT") or "")[:500]
                path = (request.path or "")[:500]
                method = (request.method or "")[:10]

            entry = dm.SecurityAuditLog.objects.create(
                user=user if (user and getattr(user, "is_authenticated", False)) else None,
                workspace=workspace,
                event_type=event_type,
                severity=severity,
                action=action,
                target_type=target_type,
                target_id=target_id,
                target_repr=target_repr,
                ip_address=ip or None,
                user_agent=ua,
                request_path=path,
                request_method=method,
                metadata=metadata or {},
                success=success,
                error_message=error_message[:1000] if error_message else "",
            )
            return entry
        except Exception as exc:
            # Best-effort : on log mais on ne casse JAMAIS l'op métier
            logger.warning("SecurityAuditService.log failed: %s", exc)
            return None

    @staticmethod
    def _get_client_ip(request) -> str | None:
        """Récupère l'IP client en respectant X-Forwarded-For."""
        xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if xff:
            return xff.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")


# ---------------------------------------------------------------------------
# Signaux automatiques — login / logout / login failed
# ---------------------------------------------------------------------------
@receiver(user_logged_in)
def _on_login(sender, request=None, user=None, **kwargs):
    SecurityAuditService.log(
        event_type=dm.SecurityAuditLog.EventType.LOGIN,
        action="auth.login",
        user=user,
        request=request,
        severity=dm.SecurityAuditLog.Severity.INFO,
    )


@receiver(user_logged_out)
def _on_logout(sender, request=None, user=None, **kwargs):
    SecurityAuditService.log(
        event_type=dm.SecurityAuditLog.EventType.LOGOUT,
        action="auth.logout",
        user=user,
        request=request,
        severity=dm.SecurityAuditLog.Severity.INFO,
    )


@receiver(user_login_failed)
def _on_login_failed(sender, credentials=None, request=None, **kwargs):
    username = (credentials or {}).get("username", "")[:80] if credentials else ""
    SecurityAuditService.log(
        event_type=dm.SecurityAuditLog.EventType.LOGIN_FAILED,
        action="auth.login_failed",
        request=request,
        severity=dm.SecurityAuditLog.Severity.WARNING,
        success=False,
        metadata={"username": username},
    )


# ---------------------------------------------------------------------------
# Signaux automatiques — CRUD sensibles
# ---------------------------------------------------------------------------
# Modèles surveillés en CRUD. On audite uniquement create/delete pour ne pas
# spammer (update fréquent → réservé aux changements de rôle).
_AUDIT_CREATE_DELETE = (
    "Workspace",
    "Project",
    "ProjectBudget",
    "Invoice",
    "BillingRate",
    "APIKey",
    "Webhook",
    "Integration",
)


@receiver(post_save)
def _on_sensitive_create(sender, instance, created, **kwargs):
    if not created:
        return
    name = sender.__name__
    if name not in _AUDIT_CREATE_DELETE:
        return
    try:
        SecurityAuditService.log(
            event_type=dm.SecurityAuditLog.EventType.CREATE,
            action=f"{name.lower()}.create",
            target=instance,
            severity=dm.SecurityAuditLog.Severity.INFO,
        )
    except Exception:
        pass


@receiver(post_delete)
def _on_sensitive_delete(sender, instance, **kwargs):
    name = sender.__name__
    if name not in _AUDIT_CREATE_DELETE:
        return
    try:
        SecurityAuditService.log(
            event_type=dm.SecurityAuditLog.EventType.DELETE,
            action=f"{name.lower()}.delete",
            target=instance,
            severity=dm.SecurityAuditLog.Severity.WARNING,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Signal automatique — changement de rôle RBAC
# ---------------------------------------------------------------------------
@receiver(post_save, sender=dm.WorkspaceRoleAssignment)
def _on_role_change(sender, instance, created, **kwargs):
    try:
        SecurityAuditService.log(
            event_type=dm.SecurityAuditLog.EventType.ROLE_CHANGE,
            action=("rbac.role.create" if created else "rbac.role.update"),
            user=instance.assigned_by,
            workspace=instance.workspace,
            target=instance,
            severity=dm.SecurityAuditLog.Severity.WARNING,
            metadata={
                "target_user_id": instance.user_id,
                "role": instance.role,
            },
        )
    except Exception:
        pass


@receiver(post_delete, sender=dm.WorkspaceRoleAssignment)
def _on_role_removed(sender, instance, **kwargs):
    try:
        SecurityAuditService.log(
            event_type=dm.SecurityAuditLog.EventType.ROLE_CHANGE,
            action="rbac.role.remove",
            workspace=instance.workspace,
            target=instance,
            severity=dm.SecurityAuditLog.Severity.WARNING,
            metadata={
                "target_user_id": instance.user_id,
                "previous_role": instance.role,
            },
        )
    except Exception:
        pass
