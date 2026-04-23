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

        body = (data.get("body") or "").strip()
        parent_id = data.get("parent_id")
        client_id = data.get("client_id")

        if not body:
            return

        message = await self.create_message(
            channel_id=self.channel_id,
            author_id=self.user.id,
            body=body,
            parent_id=parent_id,
        )

        payload = {
            "id": message["id"],
            "body": message["body"],
            "author": message["author"],
            "author_id": self.user.id,
            "created_at": message["created_at"],
            "parent_id": message["parent_id"],
            "client_id": client_id,
        }

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat.message",
                "message": payload,
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

    @database_sync_to_async
    def user_in_channel(self, user_id, channel_id):
        return dm.ChannelMembership.objects.filter(
            channel_id=channel_id,
            user_id=user_id,
        ).exists()

    @database_sync_to_async
    def create_message(self, channel_id, author_id, body, parent_id=None):
        User = get_user_model()

        author = User.objects.get(pk=author_id)
        channel = dm.DirectChannel.objects.get(pk=channel_id)
        parent = dm.Message.objects.filter(pk=parent_id).first() if parent_id else None

        msg = dm.Message.objects.create(
            channel=channel,
            author=author,
            body=body,
            parent=parent,
        )

        member_ids = list(
            channel.memberships.exclude(user_id=author_id).values_list("user_id", flat=True)
        )
        recipients = User.objects.filter(pk__in=member_ids)

        for recipient in recipients:
            dm.Notification.objects.create(
                recipient=recipient,
                workspace=channel.workspace,
                notification_type=dm.Notification.NotificationType.MESSAGE,
                title=f"Nouveau message dans {channel.name}",
                body=body[:180],
                url=f"/channels/{channel.pk}/",
                metadata={
                    "channel_id": channel.pk,
                    "message_id": msg.pk,
                },
            )

        return {
            "id": msg.pk,
            "body": msg.body,
            "author": author.get_full_name() or author.username,
            "created_at": timezone.localtime(msg.created_at).strftime("%d/%m/%Y %H:%M"),
            "parent_id": msg.parent_id,
        }


class ChatConsumer(AsyncWebsocketConsumer):
    """
    Consumer générique conservé si tu en as encore besoin ailleurs.
    Idéalement, unifie tout sur ChannelChatConsumer.
    """

    async def connect(self):
        self.channel_id = self.scope["url_route"]["kwargs"]["channel_id"]
        self.room_group_name = f"chat_{self.channel_id}"
        self.user = self.scope["user"]

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