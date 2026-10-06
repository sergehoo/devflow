import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth import get_user_model
from django.utils import timezone

from project import models as dm

logger = logging.getLogger(__name__)


class ChannelChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.channel_id = self.scope["url_route"]["kwargs"]["channel_id"]
        self.room_group_name = f"chat_channel_{self.channel_id}"
        self.user = self.scope["user"]

        logger.warning(
            "WS connect attempt | channel_id=%s | user=%s | authenticated=%s",
            self.channel_id,
            getattr(self.user, "username", None),
            getattr(self.user, "is_authenticated", False),
        )

        if not self.user.is_authenticated:
            logger.warning("WS refused: anonymous user")
            await self.close(code=4401)
            return

        allowed = await self.user_in_channel(self.user.id, self.channel_id)

        logger.warning(
            "WS membership check | user_id=%s | channel_id=%s | allowed=%s",
            self.user.id,
            self.channel_id,
            allowed,
        )

        if not allowed:
            logger.warning("WS refused: user not member of channel")
            await self.close(code=4403)
            return

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

        logger.warning(
            "WS connected | channel_id=%s | user_id=%s",
            self.channel_id,
            self.user.id,
        )

    async def disconnect(self, close_code):
        logger.warning(
            "WS disconnect | channel_id=%s | user_id=%s | close_code=%s",
            getattr(self, "channel_id", None),
            getattr(getattr(self, "user", None), "id", None),
            close_code,
        )

        room_group_name = getattr(self, "room_group_name", None)
        if room_group_name:
            await self.channel_layer.group_discard(room_group_name, self.channel_name)

    async def receive(self, text_data):
        try:
            data = json.loads(text_data or "{}")
        except json.JSONDecodeError:
            logger.warning("WS invalid JSON received | channel_id=%s", self.channel_id)
            return

        msg_type = data.get("type", "chat_message")

        # ── PR-CHAT-4 : typing indicator broadcast ──────────────────────
        # Le client envoie {"type":"typing.start"} ou {"type":"typing.stop"}
        # On rebroadcast aux autres membres du canal SANS persister en DB.
        if msg_type in ("typing.start", "typing.stop", "typing_start", "typing_stop"):
            is_typing = msg_type.endswith("start")
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "chat.typing",
                    "user_id": self.user.id,
                    "username": getattr(self.user, "username", ""),
                    "display_name": (
                        self.user.get_full_name() or self.user.username
                    ),
                    "is_typing": is_typing,
                },
            )
            return

        body = (data.get("body") or "").strip()
        if not body:
            return
        # Persistance + notifications + diffusion au groupe via ChatService
        # (canal résolu côté serveur depuis l'URL déjà autorisée au connect).
        await self.create_message(
            channel_id=self.channel_id,
            author_id=self.user.id,
            body=body,
            parent_id=data.get("parent_id"),
            client_id=data.get("client_id"),
        )

    async def chat_message(self, event):
        payload = event["message"]

        await self.send(
            text_data=json.dumps(
                {
                    "type": "chat_message",
                    "message": {
                        **payload,
                        "is_mine": payload.get("author_id") == getattr(self.user, "id", None),
                    },
                }
            )
        )

    async def chat_event(self, event):
        """Événements Messenger (réactions…) diffusés par ChatService."""
        await self.send(text_data=json.dumps({"type": event.get("event"), **(event.get("data") or {})}))

    async def chat_typing(self, event):
        """
        PR-CHAT-4 : retransmet un événement typing aux clients du canal,
        SAUF l'émetteur (le front sait déjà qu'il tape).
        """
        if event.get("user_id") == getattr(self.user, "id", None):
            return
        await self.send(
            text_data=json.dumps({
                "type": "typing",
                "user_id": event.get("user_id"),
                "username": event.get("username"),
                "display_name": event.get("display_name"),
                "is_typing": event.get("is_typing", False),
            })
        )

    @database_sync_to_async
    def user_in_channel(self, user_id, channel_id):
        """
        PR27 — Vérification renforcée d'accès WebSocket à un canal :
          1. Le canal doit exister et son workspace doit être accessible
             à l'utilisateur (via TeamMembership ou UserProfile).
          2. Pour un canal PRIVÉ : membership direct requise.
          3. Pour un canal PUBLIC : accès workspace suffit.
        """
        from project.utils.workspaces import get_user_workspace_ids

        channel = (
            dm.DirectChannel.objects
            .select_related("workspace")
            .filter(pk=channel_id)
            .first()
        )
        if channel is None:
            return False

        # 1) Le workspace du canal doit être dans les workspaces du user
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.filter(pk=user_id).first()
        if user is None:
            return False
        accessible_ws = get_user_workspace_ids(user)
        if channel.workspace_id not in accessible_ws:
            # Log de l'incident pour audit
            try:
                from project.services.security_audit import SecurityAuditService
                SecurityAuditService.log(
                    event_type=dm.SecurityAuditLog.EventType.ACCESS_DENIED,
                    action="ws.chat.cross_tenant_attempt",
                    user=user,
                    workspace=channel.workspace,
                    target=channel,
                    severity=dm.SecurityAuditLog.Severity.WARNING,
                    success=False,
                    error_message=(
                        f"WebSocket cross-tenant attempt sur canal {channel_id} "
                        f"depuis user {user_id}"
                    ),
                )
            except Exception:
                pass
            return False

        # 2) Canal privé : membership direct exigée
        if channel.is_private:
            return dm.ChannelMembership.objects.filter(
                channel_id=channel_id, user_id=user_id,
            ).exists()

        # 3) Canal public : accès workspace suffit
        return True

    @database_sync_to_async
    def create_message(self, channel_id, author_id, body, parent_id=None, client_id=None):
        from project.services.chat import ChatService

        author = get_user_model().objects.get(pk=author_id)
        channel = dm.DirectChannel.objects.get(pk=channel_id)
        # SECURITY — le parent doit appartenir au même canal.
        parent = (
            dm.Message.objects.filter(pk=parent_id, channel_id=channel_id).first()
            if parent_id else None
        )
        try:
            return ChatService.post_message(
                channel=channel, author=author, body=body, parent=parent, client_id=client_id,
            ).message.pk
        except (ValueError, PermissionError):
            return None


def _user_can_access_channel(user, channel_id) -> bool:
    """Canal du tenant de l'utilisateur ; privé → membership obligatoire."""
    from project.services.chat import ChatService

    return ChatService.channels_qs_for(user).filter(pk=channel_id).exists()


class ChatConsumer(AsyncWebsocketConsumer):
    """
    Consumer générique conservé si tu en as encore besoin ailleurs.
    Idéalement, unifie tout sur ChannelChatConsumer.
    """

    async def connect(self):
        self.channel_id = self.scope["url_route"]["kwargs"]["channel_id"]
        self.room_group_name = f"chat_{self.channel_id}"
        self.user = self.scope["user"]

        # SECURITY — authentification + appartenance au canal AVANT group_add.
        if not getattr(self.user, "is_authenticated", False):
            await self.close(code=4401)
            return
        if not await database_sync_to_async(_user_can_access_channel)(self.user, self.channel_id):
            await self.close(code=4403)
            return

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        room_group_name = getattr(self, "room_group_name", None)
        if room_group_name:
            await self.channel_layer.group_discard(room_group_name, self.channel_name)

    async def receive(self, text_data):
        try:
            data = json.loads(text_data or "{}")
        except json.JSONDecodeError:
            return

        body = (data.get("body") or "").strip()
        client_id = data.get("client_id")

        if not body:
            return

        user = self.scope["user"]
        # Re-vérifie l'accès à chaque écriture (membership révoquée en cours de session).
        if not await database_sync_to_async(_user_can_access_channel)(user, self.channel_id):
            await self.close(code=4403)
            return
        channel = await dm.DirectChannel.objects.aget(pk=self.channel_id)
        msg = await dm.Message.objects.acreate(
            channel=channel,
            author=user,
            body=body,
        )

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat.message",
                "message": {
                    "id": msg.pk,
                    "author": user.get_full_name() or user.username,
                    "author_id": user.id,
                    "body": msg.body,
                    "created_at": timezone.localtime(msg.created_at).strftime("%d/%m/%Y %H:%M"),
                    "client_id": client_id,
                },
            },
        )

    async def chat_message(self, event):
        payload = event["message"]

        await self.send(
            text_data=json.dumps(
                {
                    "type": "chat_message",
                    "message": {
                        **payload,
                        "is_mine": payload.get("author_id") == getattr(self.user, "id", None),
                    },
                }
            )
        )