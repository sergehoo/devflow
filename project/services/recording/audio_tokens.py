"""
Tokens audio HMAC signés (PR-REC-1).

L'élément ``<audio src="...">`` HTML n'envoie pas de header Authorization
ni de cookies cross-origin → on ne peut pas protéger un endpoint de stream
audio par session Django classique seule.

Solution : on signe un token HMAC court (30 min par défaut) qui contient :
  * resource_path (ex: "/recordings/42/speakers/SPEAKER_A/sample/")
  * user_id
  * expires_at (epoch)

Le token est ajouté en query string : ``?token=<base64>``. L'endpoint
de stream vérifie la signature avant de servir le fichier.

Ce module est **stateless** — pas de stockage DB, pas de Redis, juste
HMAC-SHA256 sur ``settings.RECORDING_AUDIO_TOKEN_SECRET`` (ou SECRET_KEY
en fallback).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time

from django.conf import settings

logger = logging.getLogger(__name__)


def _get_secret() -> bytes:
    """Secret HMAC. Fallback sur SECRET_KEY si non configuré."""
    secret = getattr(settings, "RECORDING_AUDIO_TOKEN_SECRET", "") \
        or settings.SECRET_KEY
    return secret.encode("utf-8")


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(token: str) -> bytes:
    pad = 4 - len(token) % 4
    if pad and pad != 4:
        token = token + ("=" * pad)
    return base64.urlsafe_b64decode(token.encode("ascii"))


def generate_audio_token(
    *,
    resource_path: str,
    user_id: str,
    expiry_seconds: int | None = None,
) -> str:
    """
    Génère un token signé pour autoriser l'accès à ``resource_path``.

    Args:
        resource_path: chemin URL exact (ex: "/recordings/42/audio/").
            Compare sera fait par préfixe — utile car la query string peut
            varier sur le client.
        user_id: identifiant du user (str). Peut être "anonymous" si la
            ressource est publique au sein du workspace.
        expiry_seconds: durée de validité. Default = settings.RECORDING_AUDIO_TOKEN_TTL.

    Returns:
        Token URL-safe à utiliser en ``?token=<token>``.
    """
    ttl = expiry_seconds or getattr(settings, "RECORDING_AUDIO_TOKEN_TTL", 1800)
    payload = {
        "p": resource_path,
        "u": str(user_id),
        "e": int(time.time()) + int(ttl),
    }
    payload_b = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(_get_secret(), payload_b, hashlib.sha256).digest()
    return f"{_b64encode(payload_b)}.{_b64encode(signature)}"


def verify_audio_token(*, token: str, resource_path: str) -> dict | None:
    """
    Vérifie un token. Retourne le payload décodé si valide, sinon None.

    Validations :
      1. Format ``<payload>.<signature>``
      2. Signature HMAC valide (constant-time compare)
      3. Pas expiré (``payload.e`` >= maintenant)
      4. ``payload.p`` correspond exactement à ``resource_path``
    """
    if not token or "." not in token:
        return None
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        payload_b = _b64decode(payload_b64)
        sig = _b64decode(sig_b64)
    except Exception:
        return None
    expected_sig = hmac.new(_get_secret(), payload_b, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected_sig):
        return None
    try:
        payload = json.loads(payload_b.decode("utf-8"))
    except Exception:
        return None
    if payload.get("e", 0) < int(time.time()):
        return None
    if payload.get("p") != resource_path:
        return None
    return payload
