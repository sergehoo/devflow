"""
Flux temps réel par utilisateur (Django Channels, groupe ``user_<id>``).

Diffusion « best effort » : si la couche Channels (Redis) est indisponible,
aucune erreur n'est remontée — les clients retombent sur le polling REST.
Les événements ne transportent que des identifiants / données déjà visibles
par le destinataire ; ils servent à invalider les caches côté client.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def user_group(user_id: int) -> str:
    return f"user_{user_id}"


def push_to_users(user_ids, event: str, data: dict | None = None) -> None:
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        layer = get_channel_layer()
        if layer is None:
            return
        send = async_to_sync(layer.group_send)
        for uid in {int(u) for u in user_ids if u}:
            send(user_group(uid), {"type": "user.event", "event": event, "data": data or {}})
    except Exception:  # Redis indisponible : le polling prend le relais
        logger.debug("realtime push failed (%s)", event, exc_info=True)


def serialize_notification(n) -> dict:
    return {
        "id": n.pk,
        "type": n.notification_type,
        "type_label": n.get_notification_type_display(),
        "title": n.title,
        "body": n.body,
        "url": n.url,
        "is_read": n.is_read,
        "read_at": n.read_at.isoformat() if n.read_at else None,
        "created_at": n.created_at.isoformat() if n.created_at else None,
        "workspace": {"id": n.workspace_id, "name": getattr(n.workspace, "name", "")} if n.workspace_id else None,
    }
