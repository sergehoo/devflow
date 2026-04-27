"""
Factory : choisit le provider IA actif selon `settings.AI_BACKEND`.

Valeurs supportées :
- "openai" → toujours OpenAI
- "local"  → toujours endpoint local (Ollama, vLLM...)
- "auto"   → OpenAI si dispo, sinon local. (recommandé en prod)
- "none"   → aucun provider, les services IA retombent sur heuristiques
"""

from __future__ import annotations

import logging

from django.conf import settings

from .base import AIProvider
from .local_provider import LocalProvider
from .openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)


class _NullProvider(AIProvider):
    name = "none"

    def is_available(self) -> bool:
        return False

    def generate(self, messages, *, temperature=0.2, max_tokens=None, json_mode=False, **kwargs):
        raise RuntimeError("AI backend disabled (settings.AI_BACKEND='none')")


def get_ai_provider(prefer: str | None = None) -> AIProvider:
    backend = (prefer or getattr(settings, "AI_BACKEND", "auto") or "auto").lower()

    if backend == "openai":
        return OpenAIProvider()
    if backend == "local":
        return LocalProvider()
    if backend == "none":
        return _NullProvider()

    # auto
    openai_provider = OpenAIProvider()
    if openai_provider.is_available():
        return openai_provider

    local_provider = LocalProvider()
    if local_provider.is_available():
        return local_provider

    return _NullProvider()
