"""
API Notifications (frontend React, Phase 4).

Reprend les règles des vues Django (``NotificationListView``,
``NotificationMarkReadView``, ``NotificationMarkAllReadView``) :
une notification n'est visible et modifiable que par son destinataire,
limitée aux workspaces auxquels il a encore accès.

    GET    /me/notifications/?status=unread|read&type=&q=&page=
    GET    /me/notifications/summary/          — badge + 6 dernières (cloche)
    POST   /me/notifications/<id>/read/
    POST   /me/notifications/read-all/
    DELETE /me/notifications/<id>/
    GET    /me/notification-preferences/
    PATCH  /me/notification-preferences/
"""

from __future__ import annotations

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from project import models as dm
from project.api.pagination import FlexiblePagination
from project.services.realtime import push_to_users, serialize_notification
from project.utils.workspaces import get_user_workspace_ids


def _own_notifications(user):
    return (
        dm.Notification.objects.filter(recipient=user, workspace_id__in=get_user_workspace_ids(user))
        .select_related("workspace")
        .order_by("-created_at")
    )


def _sync_other_tabs(user):
    push_to_users([user.pk], "notification.read", {"unread_count": _own_notifications(user).filter(is_read=False).count()})


class NotificationListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        base = _own_notifications(request.user)
        qs = base
        state = request.GET.get("status")
        if state == "unread":
            qs = qs.filter(is_read=False)
        elif state == "read":
            qs = qs.filter(is_read=True)
        if request.GET.get("type"):
            qs = qs.filter(notification_type=request.GET["type"])
        term = (request.GET.get("q") or "").strip()
        if term:
            qs = qs.filter(Q(title__icontains=term) | Q(body__icontains=term))
        paginator = FlexiblePagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        response = paginator.get_paginated_response([serialize_notification(n) for n in page])
        unread = base.filter(is_read=False).count()
        total = base.count()
        response.data.update({
            "unread_count": unread, "read_count": total - unread, "total_count": total,
            "types": [{"value": v, "label": label} for v, label in dm.Notification.NotificationType.choices],
        })
        return response


class NotificationSummaryView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        qs = _own_notifications(request.user)
        return Response({
            "unread_count": qs.filter(is_read=False).count(),
            "recent": [serialize_notification(n) for n in qs[:6]],
        })


class NotificationReadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        n = get_object_or_404(_own_notifications(request.user), pk=pk)
        if not n.is_read:
            n.is_read, n.read_at = True, timezone.now()
            n.save(update_fields=["is_read", "read_at", "updated_at"])
        _sync_other_tabs(request.user)
        return Response(serialize_notification(n))


class NotificationReadAllView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        updated = _own_notifications(request.user).filter(is_read=False).update(is_read=True, read_at=timezone.now())
        _sync_other_tabs(request.user)
        return Response({"updated": updated, "unread_count": 0})


class NotificationDeleteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, pk):
        get_object_or_404(_own_notifications(request.user), pk=pk).delete()
        _sync_other_tabs(request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = dm.NotificationPreference
        fields = ["channel_in_app", "channel_email", "channel_digest", "notify_frequency",
                  "quiet_hours_start", "quiet_hours_end", "priority_types"]

    def validate_quiet_hours_start(self, value):
        return self._hour(value)

    def validate_quiet_hours_end(self, value):
        return self._hour(value)

    @staticmethod
    def _hour(value):
        if not 0 <= value <= 23:
            raise serializers.ValidationError("Heure attendue entre 0 et 23.")
        return value

    def validate_priority_types(self, value):
        allowed = {v for v, _ in dm.Notification.NotificationType.choices}
        if not isinstance(value, list) or any(v not in allowed for v in value):
            raise serializers.ValidationError("Types de notification inconnus.")
        return value


class NotificationPreferenceView(APIView):
    """Préférences de l'utilisateur connecté uniquement (aucun identifiant accepté)."""
    permission_classes = [permissions.IsAuthenticated]

    def _payload(self, prefs):
        data = NotificationPreferenceSerializer(prefs).data
        data["choices"] = {
            "notify_frequency": [{"value": v, "label": label} for v, label in dm.NotificationPreference.NotifyFrequency.choices],
            "priority_types": [{"value": v, "label": label} for v, label in dm.Notification.NotificationType.choices],
        }
        return data

    def get(self, request):
        from project.services.smart_notifications import NotificationPreferenceService

        return Response(self._payload(NotificationPreferenceService.get_or_create(request.user)))

    def patch(self, request):
        from project.services.smart_notifications import NotificationPreferenceService

        prefs = NotificationPreferenceService.get_or_create(request.user)
        serializer = NotificationPreferenceSerializer(prefs, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(self._payload(prefs))
