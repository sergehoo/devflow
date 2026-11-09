"""
DevFlow REST API — Throttles (Phase 0 sécurité / coûts).

Les actions IA payantes (forecast, risk-analysis, allocation-advice,
effort-estimate) sont protégées par un rate limit dédié. Sans ce
garde-fou, un utilisateur authentifié pouvait spammer OpenAI sans coût
pour lui — facture côté hébergeur.

Le rate est configurable via ``settings.DEVFLOW_AI_RATE_LIMIT`` (au
format DRF, ex. "30/min") ; la valeur par défaut suffit pour l'usage
interactif normal et permet à un PM de déclencher plusieurs analyses
d'affilée si nécessaire.
"""

from __future__ import annotations

from django.conf import settings
from rest_framework.throttling import UserRateThrottle


class AIActionRateThrottle(UserRateThrottle):
    """Limite par utilisateur (authentifié) pour les actions IA payantes."""

    scope = "devflow_ai"

    def __init__(self):
        # Permet de surcharger le rate via settings sans toucher au code
        self.rate = getattr(settings, "DEVFLOW_AI_RATE_LIMIT", "30/min")
        super().__init__()

    def allow_request(self, request, view):
        # Marque la requête Django sous-jacente : une vue historique exécutée
        # par un pont DRF (``run_action_view``) ne recompte pas ce quota
        # (cf. ``ai_rate_limited``).
        setattr(getattr(request, "_request", request), AI_QUOTA_COUNTED_ATTR, True)
        return super().allow_request(request, view)


# ─────────────────────────────────────────────────────────────────────
# Quota IA partagé avec les vues Django historiques (chantier « meetings »)
# ─────────────────────────────────────────────────────────────────────
AI_QUOTA_COUNTED_ATTR = "_devflow_ai_quota_counted"
AI_RATE_LIMIT_MESSAGE = "Quota d'actions IA atteint — réessayez dans quelques instants."


def ai_rate_limited(request) -> bool:
    """
    Applique ``AIActionRateThrottle`` à une vue Django historique (même compteur
    de cache ``throttle_devflow_ai_<user_pk>`` que l'API) : l'ancienne et la
    nouvelle interface partagent le même quota.

    Renvoie ``True`` si l'utilisateur a dépassé son quota. Une requête déjà
    comptée par le throttle DRF (vue exécutée via un pont API) n'est pas recomptée.
    """
    django_request = getattr(request, "_request", request)
    if getattr(django_request, AI_QUOTA_COUNTED_ATTR, False):
        return False
    setattr(django_request, AI_QUOTA_COUNTED_ATTR, True)
    return not AIActionRateThrottle().allow_request(request, None)
