"""
Provider DeepSeek pour DevFlow — Phase 4 (PR17).

DeepSeek expose une API 100 % compatible avec le protocole OpenAI Chat
Completions (https://api.deepseek.com/v1). On réutilise donc le SDK
``openai`` officiel en pointant simplement ``base_url`` vers DeepSeek.

Modèles supportés (DeepSeek 2026) :
  * ``deepseek-chat``     — généraliste (V3), default pour DevFlow
  * ``deepseek-reasoner`` — raisonnement (R1), pour audits / risk analysis
  * ``deepseek-coder``    — spécialisé code

Configuration via settings (lisibles aussi via os.getenv pour la prod) :
  * DEEPSEEK_API_KEY         (obligatoire pour activer le provider)
  * AI_DEEPSEEK_MODEL        (default "deepseek-chat")
  * AI_DEEPSEEK_BASE_URL     (default "https://api.deepseek.com/v1")
  * AI_BACKEND="deepseek"    (force ce provider) ou "auto" (chaîne fallback)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from django.conf import settings

from .base import AIMessage, AIProvider, AIResponse

logger = logging.getLogger(__name__)


class DeepSeekProvider(AIProvider):
    name = "deepseek"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ):
        self.api_key = api_key or getattr(settings, "DEEPSEEK_API_KEY", "")
        self.model = model or getattr(
            settings, "AI_DEEPSEEK_MODEL", "deepseek-chat",
        )
        self.base_url = base_url or getattr(
            settings, "AI_DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1",
        )
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            # DeepSeek est compatible 100% avec le SDK OpenAI — on l'utilise
            # tel quel en redirigeant juste base_url.
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )
        except Exception as exc:  # pragma: no cover
            logger.exception("DeepSeek client init failed: %s", exc)
            self._client = None
        return self._client

    def is_available(self) -> bool:
        """
        Le provider est utilisable si on a une clé API configurée.
        On ne pingue pas l'endpoint à chaque appel (perf). L'appel
        ``generate`` lève proprement si l'API est down ; les services
        métier ont déjà un fallback heuristique.
        """
        return bool(self.api_key)

    def supports_json_mode(self) -> bool:
        # DeepSeek v3 (deepseek-chat) supporte response_format json_object
        # exactement comme OpenAI gpt-4o. Le reasoner ne le supporte pas
        # toujours — on reste prudent et on laisse ce flag à True : les
        # services métier ont un parse_json tolérant aux artefacts markdown.
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
            raise RuntimeError("DeepSeek client not initialised")

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

    def generate_stream(
        self,
        messages: list[AIMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        **kwargs: Any,
    ):
        """
        Phase 4 (PR20) — Génère en streaming SSE.

        Yield des chunks de texte au fur et à mesure. Le caller construit
        les events SSE (``data: {chunk}\\n\\n``). Si le client se déconnecte,
        on log et on s'arrête.
        """
        client = self._get_client()
        if client is None:
            raise RuntimeError("DeepSeek client not initialised")

        oai_messages = [{"role": m.role, "content": m.content} for m in messages]
        request: dict[str, Any] = {
            "model": self.model,
            "messages": oai_messages,
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens:
            request["max_tokens"] = max_tokens

        try:
            stream = client.chat.completions.create(**request)
            for chunk in stream:
                try:
                    delta = chunk.choices[0].delta
                    content = getattr(delta, "content", None)
                    if content:
                        yield content
                except Exception:
                    continue
        except Exception as exc:
            logger.warning("DeepSeek streaming failed: %s", exc)
            raise

    @staticmethod
    def parse_json(response: AIResponse) -> dict:
        """
        Helper de parsing JSON robuste. Identique au parser OpenAI :
        tolère les artefacts markdown (```json ... ```) qu'un modèle
        peut renvoyer même en mode JSON strict.
        """
        text = (response.text or "").strip()
        if text.startswith("```"):
            # Coupe la première fence + la dernière
            text = text.split("```", 2)[-1]
            if text.startswith("json"):
                text = text[4:]
            text = text.rsplit("```", 1)[0]
        try:
            return json.loads(text)
        except Exception as exc:
            logger.warning("DeepSeek JSON parse failed: %s", exc)
            return {}
