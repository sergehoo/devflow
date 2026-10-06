"""
DevFlow REST API — Endpoints Chat unifiés (DM + groupes).

URLs montées sous /api/v1/me/chat/* :
    GET  /channels/                 — liste des canaux du user
    POST /direct/                   — find_or_create DM, body: {user_id}
    POST /groups/                   — créer un groupe, body: {name, member_ids: []}
    GET  /channels/{id}/messages/   — historique + ?after=ID pour polling
    POST /channels/{id}/messages/   — envoyer un message, body: {body, parent_id?}
    GET  /contacts/                 — annuaire users du workspace, ?q=
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from project import models as dm
from project.services.chat import ChatService, _channel_to_dict
from project.utils.workspaces import (
    get_default_workspace_for_user,
    get_user_workspace_ids,
)


User = get_user_model()


def _resolve_workspace(request):
    """
    Détermine le workspace courant pour les opérations chat.
    Priorité : ?workspace_id=... > UserProfile.workspace > premier accessible.
    """
    workspace_id = request.GET.get("workspace_id") or (
        request.data.get("workspace_id") if hasattr(request, "data") else None
    )
    if workspace_id:
        try:
            workspace_id = int(workspace_id)
        except (TypeError, ValueError):
            return None
        if workspace_id in get_user_workspace_ids(request.user):
            return dm.Workspace.objects.filter(pk=workspace_id).first()
        return None
    return get_default_workspace_for_user(request.user)


# ---------------------------------------------------------------------------
# GET /channels/
# ---------------------------------------------------------------------------
class ChatChannelsListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response({
            "channels": ChatService.list_channels_for(request.user),
        })


# ---------------------------------------------------------------------------
# POST /direct/
# ---------------------------------------------------------------------------
class ChatDirectCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        user_id = (request.data or {}).get("user_id")
        if not user_id:
            return Response(
                {"detail": "user_id requis."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # L'autre user doit appartenir à un workspace en commun.
        workspace = _resolve_workspace(request)
        if workspace is None:
            return Response(
                {"detail": "Aucun workspace accessible."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from project.utils.workspaces import users_in_workspaces
        # SECURITY — le destinataire doit appartenir au workspace courant.
        other_in_ws = users_in_workspaces([workspace.pk]).filter(pk=user_id).first()
        if other_in_ws is None:
            return Response(
                {"detail": "Utilisateur introuvable ou non accessible."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            channel = ChatService.find_or_create_direct(
                user_a=request.user, user_b=other_in_ws, workspace=workspace,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)

        return Response(
            {
                **_channel_to_dict(channel, current_user=request.user),
                "conversation": ChatService.conversation_dict(request.user, channel),
            },
            status=200,
        )


# ---------------------------------------------------------------------------
# POST /groups/
# ---------------------------------------------------------------------------
class ChatGroupCreateView(APIView):
    """Les conversations de groupe sont automatiques (équipes / projets)."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        return Response(
            {"detail": "Les conversations de groupe sont créées automatiquement pour les équipes et les projets."},
            status=status.HTTP_403_FORBIDDEN,
        )


class ChatConversationsView(APIView):
    """GET /me/chat/conversations/?q= — liste Messenger (DM, équipes, projets)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        workspace = _resolve_workspace(request)
        if workspace is None:
            return Response({"workspace_id": None, "conversations": []})
        ChatService.ensure_group_channels_for(request.user, workspace)
        return Response({
            "workspace_id": workspace.pk,
            "conversations": ChatService.conversations_for(
                request.user, workspace, query=request.GET.get("q", ""),
            ),
        })


class ChatReactionView(APIView):
    """POST /me/chat/messages/{id}/reactions/ — body: {emoji}. Bascule la réaction."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        message = (
            dm.Message.objects.select_related("channel")
            .filter(pk=pk, channel__in=ChatService.channels_qs_for(request.user))
            .first()
        )
        if message is None:
            return Response({"detail": "Message introuvable."}, status=404)
        try:
            reactions = ChatService.toggle_reaction(
                user=request.user, message=message, emoji=(request.data or {}).get("emoji", ""),
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=403)
        return Response({"message_id": message.pk, "reactions": reactions})


class ChatChannelMessagesView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        channel = ChatService.get_channel_for(request.user, pk)
        if channel is None:
            return Response({"detail": "Canal introuvable."}, status=404)

        def _parse_int(val):
            try:
                return int(val) if val else None
            except (TypeError, ValueError):
                return None

        before_id = _parse_int(request.GET.get("before"))
        after_id = _parse_int(request.GET.get("after"))
        limit = _parse_int(request.GET.get("limit")) or 50
        limit = min(max(limit, 1), 200)

        try:
            messages = ChatService.latest_messages(
                channel=channel, user=request.user,
                before_id=before_id, after_id=after_id, limit=limit,
            )
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=403)
        from django.db.models import Max
        others_read = (
            channel.memberships.exclude(user=request.user).aggregate(m=Max("last_read_at"))["m"]
        )
        return Response({
            "channel": _channel_to_dict(channel, current_user=request.user),
            "messages": messages,
            "others_last_read_at": others_read.isoformat() if others_read else None,
        })

    def post(self, request, pk):
        channel = ChatService.get_channel_for(request.user, pk)
        if channel is None:
            return Response({"detail": "Canal introuvable."}, status=404)
        body = (request.data or {}).get("body", "")
        parent_id = (request.data or {}).get("parent_id")
        parent = None
        if parent_id:
            parent = channel.messages.filter(pk=parent_id).first()

        try:
            result = ChatService.post_message(
                channel=channel, author=request.user, body=body, parent=parent,
                files=request.FILES.getlist("files"),
                client_id=(request.data or {}).get("client_id"),
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=403)

        return Response(result.to_dict(current_user=request.user), status=201)


# ---------------------------------------------------------------------------
# GET /contacts/
# ---------------------------------------------------------------------------
class ChatContactsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        query = request.GET.get("q", "")
        try:
            limit = int(request.GET.get("limit") or 30)
        except (TypeError, ValueError):
            limit = 30
        limit = min(max(limit, 1), 100)

        workspace = _resolve_workspace(request)
        if workspace is None:
            return Response({"contacts": []})
        contacts = ChatService.contacts_for(
            request.user, query=query, limit=limit, workspace=workspace,
        )
        return Response({"contacts": contacts})


# ---------------------------------------------------------------------------
# GET /unread/  (PR-CHAT-2)
# ---------------------------------------------------------------------------
class ChatUnreadCountView(APIView):
    """
    Retourne le nombre de messages non lus par canal + total global.

    Utilisé par la bulle chat flottante (badge) et la liste des canaux
    (highlight de chaque canal non lu).
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        counts = ChatService.unread_counts_for(request.user)
        return Response(counts)


# ---------------------------------------------------------------------------
# POST /channels/{id}/mark-read/  (PR-CHAT-2)
# ---------------------------------------------------------------------------
class ChatMarkReadView(APIView):
    """
    Marque tous les messages du canal comme lus jusqu'à maintenant.

    Idempotent. Appelé par le front au focus/scroll du canal.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        channel = ChatService.get_channel_for(request.user, pk)
        if channel is None:
            return Response({"detail": "Canal introuvable."}, status=404)
        result = ChatService.mark_read(user=request.user, channel=channel)
        return Response(result)


# ---------------------------------------------------------------------------
# GET /channels/{id}/members/  (PR-CHAT-3)
# ---------------------------------------------------------------------------
class ChatChannelMembersView(APIView):
    """
    Liste les membres d'un canal (groupe ou DM) avec leur présence.

    Sécurité : le caller doit être membre du canal (ou le canal public dans
    son workspace).
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        channel = ChatService.get_channel_for(request.user, pk)
        if channel is None:
            return Response({"detail": "Canal introuvable."}, status=404)
        try:
            members = ChatService.members_for_channel(
                user=request.user, channel=channel,
            )
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=403)
        return Response({
            "channel_id": channel.pk,
            "name": channel.name,
            "member_count": len(members),
            "members": members,
        })
