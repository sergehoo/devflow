"""
Provider Anthropic Claude pour DevFlow (PR-REC-1).

Ajouté dans la chaîne de fallback ``DeepSeek → Claude → Ollama`` pour
fournir une option payante de haute qualité (synthèse de réunion, audits
exécutifs, etc.) en complément de DeepSeek.

Configuration :
    ANTHROPIC_API_KEY        (obligatoire pour activer)
    ANTHROPIC_MODEL          (default "claude-sonnet-4-5-20250929")
    ANTHROPIC_BASE_URL       (override pour proxy/test)

Coût indicatif (modèle Sonnet 4.5, juin 2026) :
    Input  : ~3 $/M tokens
    Output : ~15 $/M tokens
"""

from __future__ import annotations

import json
import logging
from typing import Any

from django.conf import settings

from .base import AIMessage, AIProvider, AIResponse

logger = logging.getLogger(__name__)


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ):
        self.api_key = api_key or getattr(settings, "ANTHROPIC_API_KEY", "")
        self.model = model or getattr(
            settings, "ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929",
        )
        self.base_url = base_url or getattr(settings, "ANTHROPIC_BASE_URL", "") or None
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from anthropic import Anthropic
            kwargs = {"api_key": self.api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = Anthropic(**kwargs)
        except Exception as exc:  # pragma: no cover
            logger.exception("Anthropic client init failed: %s", exc)
            self._client = None
        return self._client

    def is_available(self) -> bool:
        return bool(self.api_key)

    def supports_json_mode(self) -> bool:
        # Anthropic ne supporte pas response_format json_object natif.
        # On le simule via prompt instruction si demandé par le caller.
        return False

    def generate(
        self,
        messages: list[AIMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        json_mode: bool = False,
        **kwargs: Any,
    ) -> AIResponse:
        client = self._get_client()
        if client is None:
            raise RuntimeError("Anthropic client not initialised")

        # L'API Anthropic distingue system (top-level) du chat history.
        # On extrait le 1er message system s'il existe, sinon vide.
        system_parts = [m.content for m in messages if m.role == "system"]
        system_prompt = "\n\n".join(system_parts) if system_parts else ""
        if json_mode:
            system_prompt += (
                "\n\nRéponds UNIQUEMENT par un objet JSON valide, sans bloc "
                "markdown ni commentaire."
            )

        # Convertit user/assistant en format Claude
        claude_messages = []
        for m in messages:
            if m.role == "system":
                continue
            role = "user" if m.role == "user" else "assistant"
            claude_messages.append({"role": role, "content": m.content})

        # Anthropic exige max_tokens explicite
        eff_max = max_tokens or 2048

        try:
            response = client.messages.create(
                model=self.model,
                system=system_prompt or None,
                messages=claude_messages,
                temperature=temperature,
                max_tokens=eff_max,
            )
        except Exception:
            raise

        # response.content est une liste de blocs ; on concatène les text blocks
        text_parts = []
        for block in getattr(response, "content", []) or []:
            if getattr(block, "type", None) == "text":
                text_parts.append(getattr(block, "text", "") or "")
        text = "\n".join(text_parts).strip()

        usage = getattr(response, "usage", None)
        tokens = 0
        if usage:
            tokens = (getattr(usage, "input_tokens", 0) or 0) + \
                     (getattr(usage, "output_tokens", 0) or 0)

        return AIResponse(
            text=text,
            raw=response,
            tokens_used=tokens,
            provider=self.name,
            model=self.model,
        )

    @staticmethod
    def parse_json(response: AIResponse) -> dict:
        """Helper identique au DeepSeek pour parser le JSON tolérant."""
        text = (response.text or "").strip()
        if text.startswith("```"):
            text = text.split("```", 2)[-1]
            if text.startswith("json"):
                text = text[4:]
            text = text.rsplit("```", 1)[0]
        try:
            return json.loads(text)
        except Exception as exc:
            logger.warning("Anthropic JSON parse failed: %s", exc)
            return {}
