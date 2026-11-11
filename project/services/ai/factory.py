"""
Factory : choisit le provider IA actif selon ``settings.AI_BACKEND``.

Valeurs supportées :
- "auto" (défaut)      → chaîne ``AI_FALLBACK_CHAIN`` (cf. ci-dessous).
                         Recommandé en production.
- "deepseek" / "openai" / "anthropic" / "local"
                       → ce fournisseur seul, sans bascule
                         (alias : "claude" = anthropic, "ollama" = local).
- "none"               → aucun provider : les services IA appliquent leurs
                         heuristiques déterministes (tests, audits).

Chaîne de bascule (mode "auto") :
    AI_FALLBACK_CHAIN="deepseek,openai,anthropic,local"   # défaut
    Liste ordonnée, par préférence décroissante. Les noms inconnus sont
    ignorés (WARNING) ; les fournisseurs sans configuration valide (clé API
    ou URL absente) sont écartés dès la construction.

    - aucun fournisseur configuré → ``_NullProvider`` (heuristiques) ;
    - un seul                    → ce provider, retourné tel quel ;
    - plusieurs                  → ``FallbackChainProvider`` : bascule à
      l'exécution, uniquement pour les erreurs éligibles
      (cf. ``fallback.is_fallback_eligible``).
"""

from __future__ import annotations

import logging

from django.conf import settings

from .anthropic_provider import AnthropicProvider
from .base import AIProvider, ProviderUnavailableError
from .deepseek_provider import DeepSeekProvider
from .fallback import FallbackChainProvider
from .local_provider import LocalProvider
from .openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)


class _NullProvider(AIProvider):
    name = "none"

    def is_available(self) -> bool:
        return False

    def generate(self, messages, *, temperature=0.2, max_tokens=None, json_mode=False, **kwargs):
        raise ProviderUnavailableError("Aucun provider IA configuré (AI_BACKEND / AI_FALLBACK_CHAIN).")


# Mapping nom → classe pour parser AI_FALLBACK_CHAIN proprement
_PROVIDER_CLASSES = {
    "deepseek": DeepSeekProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "claude": AnthropicProvider,  # alias
    "local": LocalProvider,
    "ollama": LocalProvider,  # alias — Ollama est un cas particulier de Local
}


DEFAULT_FALLBACK_CHAIN = ("deepseek", "openai", "anthropic", "local")


def fallback_chain_names() -> list[str]:
    """Noms demandés par ``AI_FALLBACK_CHAIN`` (chaîne CSV ou liste), sinon le défaut."""
    raw = getattr(settings, "AI_FALLBACK_CHAIN", None)
    items = raw.split(",") if isinstance(raw, str) else list(raw or [])
    names = [str(item).strip().lower() for item in items if str(item).strip()]
    return names or list(DEFAULT_FALLBACK_CHAIN)


def configured_providers() -> list[AIProvider]:
    """
    Providers de la chaîne réellement utilisables, dans l'ordre de préférence.

    Sont écartés : les noms inconnus, les doublons (alias compris) et les
    fournisseurs sans configuration valide (``is_available() == False``).
    """
    providers: list[AIProvider] = []
    seen: set[type] = set()
    for name in fallback_chain_names():
        provider_cls = _PROVIDER_CLASSES.get(name)
        if provider_cls is None:
            logger.warning("AI_FALLBACK_CHAIN: provider inconnu '%s' — ignoré", name)
            continue
        if provider_cls in seen:
            continue
        seen.add(provider_cls)
        try:
            provider = provider_cls()
            available = provider.is_available()
        except Exception:  # pragma: no cover — configuration invalide d'un fournisseur
            logger.exception("AI_FALLBACK_CHAIN: échec d'initialisation de '%s' — ignoré", name)
            continue
        if not available:
            logger.debug("AI_FALLBACK_CHAIN: '%s' non configuré — ignoré", name)
            continue
        providers.append(provider)
    return providers


def get_ai_provider(prefer: str | None = None) -> AIProvider:
    backend = (prefer or getattr(settings, "AI_BACKEND", "auto") or "auto").strip().lower()

    if backend == "none":
        return _NullProvider()
    if backend != "auto":
        provider_cls = _PROVIDER_CLASSES.get(backend)
        if provider_cls is not None:
            return provider_cls()
        logger.warning("AI_BACKEND inconnu '%s' — mode auto appliqué", backend)

    providers = configured_providers()
    if not providers:
        return _NullProvider()
    if len(providers) == 1:
        return providers[0]
    return FallbackChainProvider(providers, name="auto")
