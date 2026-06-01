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
        accessible = get_user_workspace_ids(request.user)
        if int(workspace_id) in accessible:
            return dm.Workspace.objects.filter(pk=workspace_id).first()
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

        accessible_workspace_ids = get_user_workspace_ids(request.user)
        # On vérifie que le user cible partage au moins un workspace avec moi.
        other_in_ws = (
            User.objects.filter(pk=user_id, is_active=True)
            .filter(
                # via profile, team membership ou owner
                Q(profile__workspace_id__in=accessible_workspace_ids)
                | Q(devflow_memberships__workspace_id__in=accessible_workspace_ids)
                | Q(owned_workspaces__id__in=accessible_workspace_ids)
            )
            .distinct()
            .first()
        )
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
            _channel_to_dict(channel, current_user=request.user),
            status=200,
        )


# ---------------------------------------------------------------------------
# POST /groups/
# ---------------------------------------------------------------------------
class ChatGroupCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        data = request.data or {}
        name = (data.get("name") or "").strip()
        member_ids = data.get("member_ids") or []
        if not name:
            return Response({"detail": "name requis."}, status=400)
        if not isinstance(member_ids, list) or len(member_ids) < 1:
            return Response(
                {"detail": "member_ids doit contenir au moins 1 user (en plus de vous)."},
                status=400,
            )

        workspace = _resolve_workspace(request)
        if workspace is None:
            return Response({"detail": "Aucun workspace accessible."}, status=400)

        # Charge les users — uniquement ceux dans le même workspace que le caller
        accessible_workspace_ids = get_user_workspace_ids(request.user)
        members_qs = (
            User.objects.filter(pk__in=member_ids, is_active=True)
            .filter(
                Q(profile__workspace_id__in=accessible_workspace_ids)
                | Q(devflow_memberships__workspace_id__in=accessible_workspace_ids)
                | Q(owned_workspaces__id__in=accessible_workspace_ids)
            )
            .distinct()
        )
        members = list(members_qs)
        if not members:
            return Response(
                {"detail": "Aucun membre valide trouvé."},
                status=404,
            )

        try:
            channel = ChatService.create_group(
                workspace=workspace, name=name,
                members=members, creator=request.user,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)

        return Response(
            _channel_to_dict(channel, current_user=request.user),
            status=201,
        )


# ---------------------------------------------------------------------------
# GET / POST /channels/{id}/messages/
# ---------------------------------------------------------------------------
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
        return Response({
            "channel": _channel_to_dict(channel, current_user=request.user),
            "messages": messages,
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

        contacts = ChatService.contacts_for(request.user, query=query, limit=limit)
        return Response({"contacts": contacts})
