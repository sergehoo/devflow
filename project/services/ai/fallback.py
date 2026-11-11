"""
FallbackChainProvider — Provider IA composite qui essaie plusieurs providers
en cascade et bascule sur le suivant quand le fournisseur courant est en
défaut (panne, quota, authentification…).

**Cas d'usage DevFlow** : DeepSeek est le provider principal. S'il est
indisponible, on bascule de façon transparente sur le fournisseur suivant de
``AI_FALLBACK_CHAIN`` (défaut : ``deepseek,openai,anthropic,local``) pour ne
pas bloquer les services métier IA. ``AIResponse.provider`` et
``AIResponse.metadata["fallback_level"]`` indiquent qui a répondu.

Décisions de design :
- La bascule n'a lieu que pour les **erreurs éligibles** (cf.
  ``is_fallback_eligible``) : celles qui tiennent au fournisseur — réseau,
  timeout, 5xx, limitation de débit, clé invalide, quota épuisé, modèle
  introuvable, client non initialisé.
- Une erreur **non éligible** (requête refusée : 400, 413, 422 ; erreur de
  programmation) est remontée immédiatement : rejouer la même requête chez un
  autre fournisseur n'a pas de sens (et contournerait un refus de contenu).
  Le service métier applique alors son heuristique habituelle.
- Chaque bascule est logguée en WARNING. Si tous les providers échouent, la
  dernière exception est remontée (cf. ``HeuristicFallbackError`` côté service).
- Streaming (``generate_stream``) : la bascule n'est possible qu'AVANT le
  premier chunk. Une erreur en cours de flux est remontée telle quelle
  (impossible de rebasculer sans réémettre ce qui a déjà été envoyé).
- ``is_available()`` retourne True dès qu'UN provider est dispo — l'ordre
  de préférence est conservé pour ``generate()``.
"""

from __future__ import annotations

import logging
from typing import Any, Iterator

from .base import AIMessage, AIProvider, AIResponse, ProviderUnavailableError

logger = logging.getLogger(__name__)

# Statuts HTTP propres au fournisseur (et non à la requête) : clé invalide ou
# révoquée (401/403), solde épuisé (402), modèle ou endpoint introuvable (404),
# timeout (408), conflit/trop tôt (409/425), limitation de débit (429).
# Tout statut >= 500 est également éligible.
FALLBACK_STATUS_CODES = frozenset({401, 402, 403, 404, 408, 409, 425, 429})

# Erreurs de transport des SDK (openai, anthropic) et de leurs couches HTTP
# (httpx, httpcore, requests), reconnues par nom de classe dans la MRO pour ne
# dépendre d'aucun SDK à l'import.
_TRANSPORT_ERROR_NAMES = frozenset({
    "APIConnectionError", "APITimeoutError",          # openai / anthropic
    "TransportError", "TimeoutException",             # httpx / httpcore
    "ConnectError", "ConnectTimeout", "ReadTimeout",  # httpx / httpcore / requests
    "Timeout",                                        # requests
})


def _status_code(exc: BaseException) -> int | None:
    for candidate in (getattr(exc, "status_code", None), getattr(getattr(exc, "response", None), "status_code", None)):
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            return candidate
    return None


def is_fallback_eligible(exc: BaseException) -> bool:
    """
    Vrai si l'erreur tient au fournisseur et justifie d'essayer le suivant.

    Éligibles : ``ProviderUnavailableError``, statuts ``FALLBACK_STATUS_CODES``
    et 5xx, erreurs de connexion / timeout. Tout le reste (400, 413, 422,
    ``ValueError``, ``TypeError``…) est une erreur de requête ou de code :
    pas de bascule.
    """
    if isinstance(exc, ProviderUnavailableError):
        return True
    status = _status_code(exc)
    if status is not None:
        return status in FALLBACK_STATUS_CODES or status >= 500
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    return any(cls.__name__ in _TRANSPORT_ERROR_NAMES for cls in type(exc).__mro__)


class FallbackChainProvider(AIProvider):
    """
    Wrappe une liste de providers et délègue ``generate()`` au premier qui
    répond. Bascule sur le suivant uniquement pour une erreur éligible
    (``is_fallback_eligible``) ; les autres erreurs sont remontées.

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
                if not is_fallback_eligible(exc):
                    logger.warning(
                        "fallback_chain: provider '%s' failed with a non-eligible "
                        "error (%s: %s) — no fallback",
                        provider.name, type(exc).__name__, exc,
                    )
                    raise
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
        raise ProviderUnavailableError(
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

        Bascule : uniquement si une erreur éligible survient AVANT le premier
        chunk (ou si le flux est vide). Une fois le premier chunk émis, on est
        engagé sur ce provider : toute erreur est remontée telle quelle.
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
                stream = iter(stream_fn(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                ))
                first = next(stream, None)
            except Exception as exc:
                if not is_fallback_eligible(exc):
                    logger.warning(
                        "fallback_chain[stream]: '%s' failed with a non-eligible "
                        "error (%s: %s) — no fallback",
                        provider.name, type(exc).__name__, exc,
                    )
                    raise
                last_exc = exc
                logger.warning(
                    "fallback_chain[stream]: '%s' failed (%s: %s) — fallback",
                    provider.name, type(exc).__name__, exc,
                )
                continue

            if first is None:
                # Flux vide : provider considéré comme défaillant, on tente le suivant.
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
            # Engagé sur ce provider : hors du try, une erreur en cours de flux
            # remonte au lieu de réémettre le début chez un autre fournisseur.
            yield from stream
            return

        if last_exc is not None:
            raise last_exc
        raise ProviderUnavailableError(
            "fallback_chain[stream]: no provider available "
            f"(chain: {[p.name for p in self.providers]})"
        )
