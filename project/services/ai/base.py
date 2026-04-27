"""
Interface commune pour tous les providers IA de DevFlow.

Tous les services métier IA (estimation, prévision, risques...) utilisent
cette interface. Cela permet de basculer entre OpenAI, un modèle local
(Ollama, vLLM...), ou même un mock pour les tests, sans toucher au code
métier.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AIMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class AIResponse:
    text: str
    raw: Any = None
    tokens_used: int = 0
    provider: str = ""
    model: str = ""
    metadata: dict = field(default_factory=dict)


class AIProvider(ABC):
    """Interface minimale qu'un provider IA doit implémenter."""

    name: str = "base"

    @abstractmethod
    def generate(
        self,
        messages: list[AIMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        json_mode: bool = False,
        **kwargs: Any,
    ) -> AIResponse:
        """Génère une réponse texte (ou JSON-stringifié si `json_mode=True`)."""

    def is_available(self) -> bool:
        """Vrai si le provider est utilisable (clé API valide, endpoint up...)."""
        return True

    def supports_json_mode(self) -> bool:
        return False


class HeuristicFallbackError(RuntimeError):
    """
    Levée par les services IA quand aucun provider n'est disponible et
    qu'on doit retomber sur l'heuristique. Ce n'est PAS une vraie erreur.
    """
