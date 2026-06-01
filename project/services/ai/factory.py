"""
Factory : choisit le provider IA actif selon ``settings.AI_BACKEND``.

Valeurs supportées :
- "deepseek"           → toujours DeepSeek seul (pas de fallback)
- "openai"             → toujours OpenAI seul
- "local"              → toujours endpoint local (Ollama, vLLM…) seul
- "auto" (default)     → chaîne fallback automatique avec bascule
                         transparente runtime : DeepSeek → Ollama/Local
                         → (Null si tout est down). En cas d'erreur SDK ou
                         de timeout sur DeepSeek, le caller obtient quand
                         même une réponse via Ollama, sans changement côté
                         service métier. Recommandé en prod.
- "none"               → aucun provider, services IA retombent sur heuristiques

Variable d'environnement avancée :
    AI_FALLBACK_CHAIN="deepseek,openai,local"
    Liste personnalisée des providers à inclure dans la chaîne, dans l'ordre
    de préférence. Utilisé uniquement si AI_BACKEND="auto".
    Si non défini, la chaîne par défaut est : deepseek → local.

NB : le mode "auto" utilise ``FallbackChainProvider`` qui catch les
exceptions de chaque provider et bascule. C'est différent du comportement
historique où on retournait un seul provider sélectionné par
``is_available()`` (pas de bascule runtime).
"""

from __future__ import annotations

import logging

from django.conf import settings

from .base import AIProvider
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
        raise RuntimeError("AI backend disabled (settings.AI_BACKEND='none')")


# Mapping nom → classe pour parser AI_FALLBACK_CHAIN proprement
_PROVIDER_CLASSES = {
    "deepseek": DeepSeekProvider,
    "openai": OpenAIProvider,
    "local": LocalProvider,
    "ollama": LocalProvider,  # alias — Ollama est un cas particulier de Local
}


def _build_fallback_chain() -> FallbackChainProvider:
    """
    Construit la chaîne de fallback à partir de ``AI_FALLBACK_CHAIN`` ou
    de la valeur par défaut DeepSeek → Local (Ollama).

    Tous les providers de la chaîne sont instanciés. ``FallbackChainProvider``
    se chargera lui-même de skipper ceux qui ne sont pas disponibles
    (``is_available() == False``) et de basculer en cas d'erreur runtime.
    """
    chain_setting = getattr(settings, "AI_FALLBACK_CHAIN", "")
    if chain_setting:
        names = [n.strip().lower() for n in str(chain_setting).split(",") if n.strip()]
    else:
        # Default DevFlow : DeepSeek principal, Ollama secours.
        names = ["deepseek", "local"]

    providers: list[AIProvider] = []
    seen = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        provider_cls = _PROVIDER_CLASSES.get(name)
        if provider_cls is None:
            logger.warning(
                "AI_FALLBACK_CHAIN: provider inconnu '%s' — ignoré", name,
            )
            continue
        try:
            providers.append(provider_cls())
        except Exception as exc:  # pragma: no cover
            logger.exception(
                "AI_FALLBACK_CHAIN: échec instanciation %s : %s", name, exc,
            )

    if not providers:
        logger.warning(
            "AI_FALLBACK_CHAIN: aucun provider valide — chaîne vide, services "
            "IA retomberont sur l'heuristique.",
        )

    return FallbackChainProvider(providers, name="auto")


def get_ai_provider(prefer: str | None = None) -> AIProvider:
    backend = (prefer or getattr(settings, "AI_BACKEND", "auto") or "auto").lower()

    if backend == "deepseek":
        return DeepSeekProvider()
    if backend == "openai":
        return OpenAIProvider()
    if backend == "local":
        return LocalProvider()
    if backend == "none":
        return _NullProvider()

    # auto — chaîne de fallback runtime (bascule sur erreur, pas juste
    # sélection à l'init).
    chain = _build_fallback_chain()
    if chain.is_available():
        return chain
    return _NullProvider()
