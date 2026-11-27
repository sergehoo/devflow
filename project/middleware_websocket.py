"""
Garde d'origine des WebSockets — protection CSWSH (Cross-Site WebSocket Hijacking).

Les consumers (``/ws/me/``, ``/ws/channels/<id>/``, ``/ws/chat/<id>/``) authentifient
l'utilisateur par le seul cookie de session joint à la poignée de main. Les cookies
sont ``SameSite=Lax`` : une page d'un autre *site* ne les envoie pas, mais une page
d'un sous-domaine voisin (même site, ex. ``autre-app.datarium-dev.com``) peut ouvrir
``wss://flow.datarium-dev.com/ws/me/`` avec les cookies de la victime et lire ses
notifications et messages.

Règle appliquée AVANT toute lecture de session :

* pas d'en-tête ``Origin`` → accepté : client non navigateur, sans cookie implicite ;
* ``Origin`` dont l'hôte[:port] est celui de l'en-tête ``Host`` → accepté (le frontend
  React et les templates se connectent à ``location.host`` ; Traefik et le proxy Vite
  de dev conservent l'en-tête ``Host``) ;
* ``Origin`` listée telle quelle dans ``CSRF_TRUSTED_ORIGINS`` → accepté. Les motifs
  génériques (``https://*.domaine``) sont volontairement ignorés : ce sont justement
  les sous-domaines voisins qu'il faut refuser ;
* sinon (origine voisine, ``null``, mal formée, en double) → poignée de main refusée
  avant ``accept`` : le serveur ASGI répond HTTP 403.

``AllowedHostsOriginValidator`` (Channels) ne suffit pas : ``settings/dev.py``, que le
docker-compose charge sans ``DJANGO_ENV=prod``, fixe ``ALLOWED_HOSTS = ['*']``, ce qui
accepterait toutes les origines en production.
"""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

from django.conf import settings

logger = logging.getLogger(__name__)

DEFAULT_PORTS = {"http": 80, "https": 443}
# Code renvoyé au client de test ; avant ``accept`` le serveur ASGI répond HTTP 403.
DENIED_CLOSE_CODE = 4403


def _header_values(scope, name: bytes) -> list[str]:
    return [
        value.decode("latin-1").strip()
        for key, value in scope.get("headers") or ()
        if key.lower() == name
    ]


def _parse_origin(value: str):
    """``scheme://hôte[:port]`` → ``(scheme, hôte, port effectif)`` ; ``None`` si invalide."""
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if (
        scheme not in DEFAULT_PORTS
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
    ):
        return None
    return scheme, parts.hostname, port if port is not None else DEFAULT_PORTS[scheme]


def _parse_host(value: str):
    """En-tête ``Host`` → ``(hôte, port ou None)`` ; ``None`` si invalide."""
    try:
        parts = urlsplit("//" + value)
        port = parts.port
    except ValueError:
        return None
    if not parts.hostname or parts.username is not None or parts.path or parts.query or parts.fragment:
        return None
    return parts.hostname, port


def _trusted_origins() -> set:
    trusted = set()
    for entry in getattr(settings, "CSRF_TRUSTED_ORIGINS", None) or ():
        if "*" in entry:
            continue
        parsed = _parse_origin(entry.strip())
        if parsed:
            trusted.add(parsed)
    return trusted


def origin_allowed(origin: str, host: str | None) -> bool:
    """``origin`` (en-tête ``Origin``) est-elle autorisée pour une requête vers ``host`` ?"""
    parsed = _parse_origin(origin)
    if parsed is None:
        return False
    scheme, origin_host, origin_port = parsed
    target = _parse_host(host) if host else None
    if target is not None:
        target_host, target_port = target
        if target_port is None:
            target_port = DEFAULT_PORTS[scheme]
        if (origin_host, origin_port) == (target_host, target_port):
            return True
    return parsed in _trusted_origins()


def handshake_allowed(scope) -> bool:
    origins = _header_values(scope, b"origin")
    if not origins:
        return True
    hosts = _header_values(scope, b"host")
    host = hosts[0] if len(hosts) == 1 else None
    if len(origins) == 1 and origin_allowed(origins[0], host):
        return True
    logger.warning(
        "WebSocket refusé : origine non autorisée | path=%s | origin=%r | host=%r",
        scope.get("path"),
        [o[:200] for o in origins],
        [h[:200] for h in hosts],
    )
    return False


class WebsocketOriginMiddleware:
    """Refuse la poignée de main WebSocket dont l'origine n'est pas celle du site."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "websocket" and not handshake_allowed(scope):
            message = await receive()
            if message.get("type") == "websocket.connect":
                await send({"type": "websocket.close", "code": DENIED_CLOSE_CODE})
            return None
        return await self.app(scope, receive, send)
