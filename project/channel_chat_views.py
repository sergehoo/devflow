import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from project.models import DirectChannel, Message
from project.services.chat import ChatService


def _accessible_channels(user):
    """SECURITY — canaux du tenant de l'utilisateur, privés seulement s'il en est membre."""
    return ChatService.channels_qs_for(user)


@login_required
@require_GET
def channel_chat_page(request, pk):
    channel = get_object_or_404(
        _accessible_channels(request.user).select_related("workspace"),
        pk=pk,
    )

    # Messagerie unifiée : la conversation s'ouvre dans Messenger.
    return redirect(f"/chat/?channel={channel.pk}")


@login_required
@require_GET
def channel_panel_data(request):
    profile = getattr(request.user, "profile", None)
    workspace = getattr(profile, "workspace", None)

    if workspace is None:
        return JsonResponse(
            {
                "success": False,
                "channels": [],
                "message": "Aucun workspace associé à cet utilisateur.",
            },
            status=200,
        )

    channels = (
        _accessible_channels(request.user)
        .filter(workspace=workspace)
        .order_by("name", "id")
    )

    data = [
        {
            "id": channel.pk,
            "name": channel.name,
            "is_private": channel.is_private,
            "unread_count": 0,
        }
        for channel in channels
    ]

    return JsonResponse({"success": True, "channels": data})


@login_required
@require_GET
def channel_panel_detail(request, pk):
    channel = get_object_or_404(_accessible_channels(request.user), pk=pk)

    messages = channel.messages.select_related("author").order_by("created_at")[:80]

    return JsonResponse({
        "success": True,
        "channel": {
            "id": channel.pk,
            "name": channel.name,
            "is_private": channel.is_private,
        },
        "messages": [
            {
                "id": m.pk,
                "author": m.author.get_full_name() or m.author.username,
                "body": m.body,
                "created_at": m.created_at.strftime("%d/%m/%Y %H:%M"),
                "is_mine": m.author_id == request.user.id,
            }
            for m in messages
        ]
    })


@login_required
@require_POST
def channel_send_message(request, pk):
    channel = get_object_or_404(_accessible_channels(request.user), pk=pk)

    payload = json.loads(request.body.decode("utf-8"))
    body = (payload.get("body") or "").strip()

    if not body:
        return JsonResponse({"success": False, "message": "Message vide."}, status=400)

    msg = Message.objects.create(
        channel=channel,
        author=request.user,
        body=body,
    )

    return JsonResponse({
        "success": True,
        "message": {
            "id": msg.pk,
            "author": request.user.get_full_name() or request.user.username,
            "body": msg.body,
            "created_at": msg.created_at.strftime("%d/%m/%Y %H:%M"),
            "is_mine": True,
        }
    })