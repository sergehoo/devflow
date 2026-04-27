"""
Provider local : appelle un endpoint compatible OpenAI Chat (Ollama, vLLM,
LocalAI, llama.cpp avec --api). Configurable via :

    AI_LOCAL_BASE_URL = "http://localhost:11434/v1"
    AI_LOCAL_MODEL    = "mistral:7b"
    AI_LOCAL_API_KEY  = "ollama"   # ignoré par Ollama mais requis par le SDK
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

from .base import AIMessage, AIProvider, AIResponse

logger = logging.getLogger(__name__)


class LocalProvider(AIProvider):
    name = "local"

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ):
        self.base_url = base_url or getattr(
            settings, "AI_LOCAL_BASE_URL", "http://localhost:11434/v1"
        )
        self.model = model or getattr(settings, "AI_LOCAL_MODEL", "mistral:7b")
        self.api_key = api_key or getattr(settings, "AI_LOCAL_API_KEY", "ollama")
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI

            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        except Exception as exc:  # pragma: no cover
            logger.exception("Local AI client init failed: %s", exc)
            self._client = None
        return self._client

    def is_available(self) -> bool:
        # On ne ping pas l'endpoint à chaque appel par perf — l'appel
        # `generate` traitera l'échec et le service retombera sur l'heuristique.
        return bool(self.base_url)

    def supports_json_mode(self) -> bool:
        # Ollama supporte format=json sur certains modèles, mais pas via
        # response_format. On reste prudent.
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
            raise RuntimeError("Local AI client not initialised")

        oai_messages = [{"role": m.role, "content": m.content} for m in messages]
        request: dict[str, Any] = {
            "model": self.model,
            "messages": oai_messages,
            "temperature": temperature,
        }
        if max_tokens:
            request["max_tokens"] = max_tokens

        completion = client.chat.completions.create(**request)
        text = completion.choices[0].message.content or ""

        return AIResponse(
            text=text,
            raw=completion,
            provider=self.name,
            model=self.model,
        )
