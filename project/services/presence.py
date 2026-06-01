"""
PresenceService — Présence en ligne / inactivité des utilisateurs.

Stockage via le cache Django (Redis en prod, locmem en tests). Pour chaque
utilisateur connecté, on stocke un timestamp ``last_seen`` mis à jour par un
heartbeat côté front (POST /api/v1/me/presence/heartbeat/ toutes les ~30s).

Le TTL du cache (``PRESENCE_TTL``) est plus long que l'intervalle de heartbeat
(~ 2.5× pour absorber un raté réseau). Si la clé n'existe plus, l'utilisateur
est considéré hors ligne.

Seuils utilisés pour le rendu UI :

  * ONLINE_WITHIN_SECONDS  : 90s   → pastille verte
  * IDLE_WITHIN_SECONDS    : 300s  → pastille jaune (idle, "X min")
  * Au-delà                : hors ligne (pastille grise)

Limite volontaire : on ne tient PAS d'historique long terme — c'est de la
présence "live", pas un audit log. Pour la traçabilité (qui s'est connecté
quand), c'est ``SecurityAuditLog`` qui s'en charge.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Iterable

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
PRESENCE_TTL = getattr(settings, "PRESENCE_TTL_SECONDS", 180)
ONLINE_WITHIN_SECONDS = getattr(settings, "PRESENCE_ONLINE_WITHIN", 90)
IDLE_WITHIN_SECONDS = getattr(settings, "PRESENCE_IDLE_WITHIN", 300)

_CACHE_KEY = "presence:user:{user_id}"


# ---------------------------------------------------------------------------
# DTO
# ---------------------------------------------------------------------------
@dataclass
class PresenceStatus:
    user_id: int
    status: str  # "online" | "idle" | "offline"
    last_seen_ts: float | None  # epoch
    seconds_since_seen: int | None

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "status": self.status,
            "last_seen_ts": self.last_seen_ts,
            "seconds_since_seen": self.seconds_since_seen,
            "inactive_minutes": (
                int(self.seconds_since_seen // 60)
                if self.seconds_since_seen is not None
                else None
            ),
        }


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------
class PresenceService:
    """API publique du service de présence."""

    @staticmethod
    def _key(user_id: int) -> str:
        return _CACHE_KEY.format(user_id=user_id)

    # ─── Heartbeat ────────────────────────────────────────────────────────
    @classmethod
    def heartbeat(cls, user) -> float:
        """
        Marque l'utilisateur comme actif maintenant. Retourne le timestamp
        epoch enregistré.

        Idempotent : peut être appelé plusieurs fois par seconde sans effet
        secondaire (juste un set en cache).
        """
        if not user or not getattr(user, "is_authenticated", False):
            return 0.0
        now = time.time()
        try:
            cache.set(cls._key(user.id), now, timeout=PRESENCE_TTL)
        except Exception as exc:  # pragma: no cover
            # On ne casse jamais l'appli si Redis tombe — présence dégradée.
            logger.warning("PresenceService.heartbeat: cache set failed: %s", exc)
        return now

    @classmethod
    def mark_offline(cls, user) -> None:
        """Force la mise hors ligne (logout, déconnexion explicite)."""
        if not user or not getattr(user, "is_authenticated", False):
            return
        try:
            cache.delete(cls._key(user.id))
        except Exception:  # pragma: no cover
            pass

    # ─── Lecture ──────────────────────────────────────────────────────────
    @classmethod
    def get_status(cls, user_id: int) -> PresenceStatus:
        """
        Retourne le ``PresenceStatus`` pour un seul user_id.

        Si pas de heartbeat récent → status="offline", last_seen_ts=None.
        """
        try:
            last_seen = cache.get(cls._key(user_id))
        except Exception:  # pragma: no cover
            last_seen = None

        if last_seen is None:
            return PresenceStatus(
                user_id=user_id, status="offline",
                last_seen_ts=None, seconds_since_seen=None,
            )

        elapsed = int(time.time() - last_seen)
        if elapsed <= ONLINE_WITHIN_SECONDS:
            status = "online"
        elif elapsed <= IDLE_WITHIN_SECONDS:
            status = "idle"
        else:
            status = "offline"

        return PresenceStatus(
            user_id=user_id, status=status,
            last_seen_ts=last_seen,
            seconds_since_seen=elapsed,
        )

    @classmethod
    def get_many(cls, user_ids: Iterable[int]) -> dict[int, PresenceStatus]:
        """
        Lecture batch — recommandé pour les listes (contacts, membres).

        Utilise ``cache.get_many`` (1 round-trip Redis pour N clés).
        """
        ids = list({int(uid) for uid in user_ids if uid is not None})
        if not ids:
            return {}
        keys = {cls._key(uid): uid for uid in ids}
        try:
            raw = cache.get_many(list(keys.keys()))
        except Exception:  # pragma: no cover
            raw = {}

        now = time.time()
        out: dict[int, PresenceStatus] = {}
        for key, uid in keys.items():
            last_seen = raw.get(key)
            if last_seen is None:
                out[uid] = PresenceStatus(
                    user_id=uid, status="offline",
                    last_seen_ts=None, seconds_since_seen=None,
                )
                continue
            elapsed = int(now - last_seen)
            if elapsed <= ONLINE_WITHIN_SECONDS:
                status = "online"
            elif elapsed <= IDLE_WITHIN_SECONDS:
                status = "idle"
            else:
                status = "offline"
            out[uid] = PresenceStatus(
                user_id=uid, status=status,
                last_seen_ts=last_seen,
                seconds_since_seen=elapsed,
            )
        return out
