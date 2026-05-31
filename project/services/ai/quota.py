"""
DevFlow — Services AI Quota + Prompt Library (Phase 4, PR18-19-20).

Deux services indépendants :

  1. AIQuotaService — gère ``AIUsageQuota`` (1 par workspace, mensuel).
     * ``get_or_create_quota(workspace)`` : seed à la première utilisation
     * ``can_consume(workspace, estimated_tokens)`` : True si quota dispo
     * ``record_usage(workspace, tokens_used)`` : incrémente le compteur
     * ``reset_if_period_expired(quota)`` : passe au cycle suivant si besoin

  2. AIPromptLibrary — résolution de prompts éditables côté workspace.
     * ``get_prompt(intent, workspace, default)`` : renvoie le prompt en
       priorité (workspace.is_default=True) > workspace.first() > default
     * ``render(template, **vars)`` : interpole les placeholders {key}

Aucun appel provider — purement Django ORM + str.format.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from project import models as dm

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AIQuotaService
# ---------------------------------------------------------------------------
@dataclass
class QuotaCheckResult:
    allowed: bool
    remaining: int
    used: int
    limit: int
    period_start: date
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "remaining": self.remaining,
            "used": self.used,
            "limit": self.limit,
            "period_start": self.period_start.isoformat(),
            "reason": self.reason,
        }


class AIQuotaError(Exception):
    """Levée quand le quota est dépassé et qu'on refuse l'appel."""

    def __init__(self, result: QuotaCheckResult):
        self.result = result
        super().__init__(result.reason or "AI quota exceeded.")


class AIQuotaService:
    """
    Gestion du quota mensuel de tokens IA par workspace.

    Le cycle mensuel est aligné sur ``period_start`` (jour de création
    initial). On rebascule sur le mois suivant quand ``today >= period_start + 30j``
    (approximation simple : 30 jours glissants, suffisant pour un quota
    mensuel administratif).
    """

    PERIOD_DAYS = 30

    @classmethod
    def get_or_create_quota(cls, workspace: dm.Workspace) -> dm.AIUsageQuota:
        """Crée le quota s'il n'existe pas. Idempotent."""
        quota, _ = dm.AIUsageQuota.objects.get_or_create(
            workspace=workspace,
        )
        cls.reset_if_period_expired(quota)
        return quota

    @classmethod
    def reset_if_period_expired(cls, quota: dm.AIUsageQuota) -> bool:
        """Si la période courante est dépassée, repart à zéro. Retourne True si reset."""
        today = timezone.localdate()
        if quota.period_start and today >= quota.period_start + timedelta(days=cls.PERIOD_DAYS):
            quota.monthly_tokens_used = 0
            quota.period_start = today
            quota.over_limit_notified_at = None
            quota.save(update_fields=[
                "monthly_tokens_used", "period_start",
                "over_limit_notified_at", "updated_at",
            ])
            return True
        return False

    @classmethod
    def can_consume(
        cls,
        workspace: dm.Workspace,
        estimated_tokens: int = 0,
    ) -> QuotaCheckResult:
        """
        Vérifie si on a encore du quota pour cet appel.
        Si ``estimated_tokens`` est 0 ou pas connu, on vérifie juste que
        la limite n'est pas déjà atteinte.
        """
        quota = cls.get_or_create_quota(workspace)

        if quota.is_unlimited:
            return QuotaCheckResult(
                allowed=True, remaining=10**9,
                used=quota.monthly_tokens_used,
                limit=quota.monthly_token_limit,
                period_start=quota.period_start,
            )

        remaining = quota.remaining_tokens
        projected_total = quota.monthly_tokens_used + max(estimated_tokens, 0)

        if projected_total > quota.monthly_token_limit:
            return QuotaCheckResult(
                allowed=False, remaining=remaining,
                used=quota.monthly_tokens_used,
                limit=quota.monthly_token_limit,
                period_start=quota.period_start,
                reason=(
                    f"Quota IA mensuel dépassé "
                    f"({quota.monthly_tokens_used}/{quota.monthly_token_limit}). "
                    f"Prochain reset : {quota.period_start + timedelta(days=cls.PERIOD_DAYS)}."
                ),
            )

        return QuotaCheckResult(
            allowed=True, remaining=remaining,
            used=quota.monthly_tokens_used,
            limit=quota.monthly_token_limit,
            period_start=quota.period_start,
        )

    @classmethod
    @transaction.atomic
    def record_usage(
        cls,
        workspace: dm.Workspace,
        tokens_used: int,
    ) -> dm.AIUsageQuota:
        """Incrémente le compteur de tokens après un appel provider réussi."""
        if tokens_used <= 0:
            return cls.get_or_create_quota(workspace)

        quota = dm.AIUsageQuota.objects.select_for_update().filter(
            workspace=workspace,
        ).first()
        if quota is None:
            quota = cls.get_or_create_quota(workspace)

        cls.reset_if_period_expired(quota)
        quota.monthly_tokens_used = (quota.monthly_tokens_used or 0) + int(tokens_used)
        quota.last_call_at = timezone.now()
        quota.save(update_fields=[
            "monthly_tokens_used", "last_call_at", "updated_at",
        ])
        return quota


# ---------------------------------------------------------------------------
# AIPromptLibrary
# ---------------------------------------------------------------------------
class AIPromptLibrary:
    """
    Résout les prompts à utiliser pour chaque intent.

    Priorité :
      1. AIPromptTemplate(workspace=ws, intent=intent, is_default=True)
      2. AIPromptTemplate(workspace=ws, intent=intent).first()
      3. default fourni par le caller (= prompt hardcodé legacy)

    Permet à un workspace de surcharger les prompts par défaut sans modifier
    le code (admin / page de config).
    """

    @classmethod
    def get_prompt(
        cls,
        intent: str,
        workspace: dm.Workspace | None,
        default: str,
    ) -> str:
        if workspace is None:
            return default

        try:
            template = (
                dm.AIPromptTemplate.objects
                .filter(workspace=workspace, intent=intent, is_archived=False)
                .order_by("-is_default", "-updated_at")
                .first()
            )
        except Exception as exc:
            logger.warning("AIPromptLibrary lookup failed for %s/%s: %s",
                            workspace.pk, intent, exc)
            return default

        if template and template.template:
            return template.template
        return default

    @staticmethod
    def render(template: str, **variables) -> str:
        """
        Interpole les variables dans le template. Utilise str.format-like :
        ``{project_name}`` est remplacé par variables["project_name"].

        Échec silencieux sur clé manquante (laisse {clé} brut). Volontaire :
        évite que le prompt plante en runtime si l'admin a mal édité.
        """
        if not template:
            return ""
        try:
            return template.format_map(_SafeDict(variables))
        except Exception as exc:
            logger.warning("AIPromptLibrary.render failed: %s", exc)
            return template


class _SafeDict(dict):
    """Dict qui retourne {key} pour les clés manquantes (str.format_map safe)."""
    def __missing__(self, key):
        return "{" + key + "}"
