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
