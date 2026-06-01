"""
FallbackChainProvider — Provider IA composite qui essaie plusieurs providers
en cascade et bascule silencieusement sur le suivant en cas d'échec.

**Cas d'usage DevFlow** : DeepSeek est le provider principal (rapide, économique,
modèle de qualité). Si l'API DeepSeek est down, timeout, ou retourne une erreur
SDK, on bascule transparent sur Ollama (instance locale) pour ne JAMAIS bloquer
les services métier IA. L'utilisateur final ne voit aucune différence — seuls
les logs et les compteurs `tokens_used` du `AIResponse.metadata` indiquent
quel provider a effectivement répondu.

L'ordre par défaut en mode `AI_BACKEND="auto"` est :
    DeepSeek (primary) → Ollama/Local (fallback) → Null (heuristique)

OpenAI peut être inséré entre DeepSeek et Local via la variable d'env
``AI_FALLBACK_CHAIN="deepseek,openai,local"`` (cf. factory.py).

Décisions de design :
- Le fallback est **silencieux** : pas d'exception remontée au caller tant
  qu'au moins un provider répond. Le caller reçoit toujours un ``AIResponse``.
- Chaque échec est loggué en WARNING (provider, erreur). Si tous échouent,
  on lève la dernière exception pour que le service métier puisse retomber
  sur son heuristique (cf. ``HeuristicFallbackError``).
- Le streaming (``generate_stream``) suit le même modèle : on tente le
  premier provider, si une exception survient AVANT le premier chunk, on
  bascule. Une exception EN COURS de stream est remontée (impossible de
  rebasculer proprement sans tout réémettre).
- ``is_available()`` retourne True dès qu'UN provider est dispo — l'ordre
  de préférence est conservé pour ``generate()``.
"""

from __future__ import annotations

import logging
from typing import Any, Iterator

from .base import AIMessage, AIProvider, AIResponse

logger = logging.getLogger(__name__)


class FallbackChainProvider(AIProvider):
    """
    Wrappe une liste de providers et délègue ``generate()`` au premier qui
    répond. Bascule silencieusement sur le suivant en cas d'exception.

    Args:
        providers: Liste ordonnée de providers (primary first).
        name: Nom logique du chain (par défaut "fallback").

    Example:
        >>> from project.services.ai.deepseek_provider import DeepSeekProvider
        >>> from project.services.ai.local_provider import LocalProvider
        >>> chain = FallbackChainProvider([DeepSeekProvider(), LocalProvider()])
        >>> response = chain.generate([AIMessage("user", "Bonjour")])
        >>> response.provider  # "deepseek" ou "local" selon ce qui a marché
    """

    def __init__(self, providers: list[AIProvider], name: str = "fallback"):
        # On ne garde que les providers déclarés disponibles à l'init.
        self.providers: list[AIProvider] = [p for p in providers if p is not None]
        self.name = name

    # ------------------------------------------------------------------
    # Interface AIProvider
    # ------------------------------------------------------------------
    def is_available(self) -> bool:
        return any(p.is_available() for p in self.providers)

    def supports_json_mode(self) -> bool:
        # Vrai si au moins un provider de la chaîne le supporte.
        return any(p.supports_json_mode() for p in self.providers)

    def generate(
        self,
        messages: list[AIMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        json_mode: bool = False,
        **kwargs: Any,
    ) -> AIResponse:
        last_exc: Exception | None = None

        for idx, provider in enumerate(self.providers):
            if not provider.is_available():
                logger.debug(
                    "fallback_chain: skip %s (not available)", provider.name,
                )
                continue
            # Si le provider ne supporte pas json_mode, on le passe en False
            # pour ne pas planter le SDK — le service métier doit pouvoir
            # parser sans le flag.
            effective_json = json_mode and provider.supports_json_mode()
            try:
                response = provider.generate(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=effective_json,
                    **kwargs,
                )
                if idx > 0:
                    logger.info(
                        "fallback_chain: served by '%s' (fallback level %d)",
                        provider.name, idx,
                    )
                # Annote la réponse avec l'info de chaîne pour debugging
                if response.metadata is None:
                    response.metadata = {}
                response.metadata.setdefault("fallback_level", idx)
                response.metadata.setdefault("requested_json_mode", json_mode)
                return response
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "fallback_chain: provider '%s' failed (%s: %s) — "
                    "trying next",
                    provider.name, type(exc).__name__, exc,
                )
                continue

        # Tous les providers ont échoué (ou aucun n'était dispo) — on relève
        # la dernière exception pour que le service métier déclenche son
        # fallback heuristique.
        if last_exc is not None:
            raise last_exc
        raise RuntimeError(
            "fallback_chain: no provider available "
            f"(chain: {[p.name for p in self.providers]})"
        )

    def generate_stream(
        self,
        messages: list[AIMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> Iterator[str]:
        """
        Streaming SSE — tente le premier provider qui supporte ``generate_stream``.

        Fallback : si une exception survient AVANT le premier chunk, on
        passe au provider suivant. Une exception en cours de stream est
        remontée (re-stream propre impossible sans tout réémettre).
        """
        last_exc: Exception | None = None

        for idx, provider in enumerate(self.providers):
            if not provider.is_available():
                continue
            stream_fn = getattr(provider, "generate_stream", None)
            if stream_fn is None:
                logger.debug(
                    "fallback_chain: %s has no generate_stream — skip", provider.name,
                )
                continue

            try:
                # On amorce le stream et on yield le premier chunk avant de
                # se "verrouiller" sur ce provider. Si l'init ou le premier
                # chunk échoue, on bascule.
                stream = stream_fn(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
                first = next(stream, None)
                if first is None:
                    # Stream vide — provider considéré comme défaillant, on
                    # tente le suivant.
                    logger.warning(
                        "fallback_chain: '%s' returned empty stream — fallback",
                        provider.name,
                    )
                    continue
                if idx > 0:
                    logger.info(
                        "fallback_chain[stream]: served by '%s' (fallback %d)",
                        provider.name, idx,
                    )
                yield first
                # À partir d'ici on est "engagé" sur ce provider.
                for chunk in stream:
                    yield chunk
                return
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "fallback_chain[stream]: '%s' failed (%s: %s) — fallback",
                    provider.name, type(exc).__name__, exc,
                )
                continue

        if last_exc is not None:
            raise last_exc
        raise RuntimeError(
            "fallback_chain[stream]: no provider available "
            f"(chain: {[p.name for p in self.providers]})"
        )
