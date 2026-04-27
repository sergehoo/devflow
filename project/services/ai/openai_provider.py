"""Provider OpenAI pour DevFlow."""

from __future__ import annotations

import json
import logging
from typing import Any

from django.conf import settings

from .base import AIMessage, AIProvider, AIResponse

logger = logging.getLogger(__name__)


class OpenAIProvider(AIProvider):
    name = "openai"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ):
        self.api_key = api_key or getattr(settings, "OPENAI_API_KEY", "")
        self.model = model or getattr(settings, "AI_OPENAI_MODEL", "gpt-4o-mini")
        self.base_url = base_url or getattr(settings, "AI_OPENAI_BASE_URL", None)
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI

            kwargs: dict[str, Any] = {"api_key": self.api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = OpenAI(**kwargs)
        except Exception as exc:  # pragma: no cover
            logger.exception("OpenAI client init failed: %s", exc)
            self._client = None
        return self._client

    def is_available(self) -> bool:
        return bool(self.api_key)

    def supports_json_mode(self) -> bool:
        return True

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
            raise RuntimeError("OpenAI client not initialised")

        oai_messages = [{"role": m.role, "content": m.content} for m in messages]

        request: dict[str, Any] = {
            "model": self.model,
            "messages": oai_messages,
            "temperature": temperature,
        }
        if max_tokens:
            request["max_tokens"] = max_tokens
        if json_mode:
            request["response_format"] = {"type": "json_object"}

        completion = client.chat.completions.create(**request)
        text = completion.choices[0].message.content or ""

        usage = getattr(completion, "usage", None)
        tokens = getattr(usage, "total_tokens", 0) if usage else 0

        return AIResponse(
            text=text,
            raw=completion,
            tokens_used=tokens,
            provider=self.name,
            model=self.model,
        )

    @staticmethod
    def parse_json(response: AIResponse) -> dict:
        """Helper pour parser un AIResponse JSON sans planter sur des artefacts."""
        text = (response.text or "").strip()
        if text.startswith("```"):
            text = text.split("```", 2)[-1]
            if text.startswith("json"):
                text = text[4:]
            text = text.rsplit("```", 1)[0]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}
