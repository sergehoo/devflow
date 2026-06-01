"""
Endpoints DRF — Présence utilisateur.

URLs (montées sous /api/v1/me/presence/) :
    POST /heartbeat/         — ping de présence (front toutes les 30s)
    GET  /?user_ids=1,2,3    — statut batch pour une liste de users

Notes de sécurité :
    * Heartbeat n'a pas besoin de RBAC : tout utilisateur authentifié peut
      signaler sa propre présence.
    * Lecture batch (GET /) : on filtre les user_ids demandés pour ne
      retourner QUE les statuts des users effectivement visibles par le
      caller (mêmes workspaces). Sinon un user pourrait observer la
      présence d'un autre workspace via cet endpoint.
"""

from __future__ import annotations

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from project.services.presence import (
    IDLE_WITHIN_SECONDS,
    ONLINE_WITHIN_SECONDS,
    PRESENCE_TTL,
    PresenceService,
)
from project.utils.workspaces import users_for_user


class PresenceHeartbeatView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    # Throttle modeste : le front pingue toutes les 30s, donc on plafonne
    # à 10/min pour absorber les onglets multiples + double-ping après idle.
    throttle_scope = "presence_heartbeat"

    def post(self, request):
        ts = PresenceService.heartbeat(request.user)
        return Response(
            {
                "ok": True,
                "user_id": request.user.id,
                "ts": ts,
                "ttl": PRESENCE_TTL,
                "online_within_seconds": ONLINE_WITHIN_SECONDS,
                "idle_within_seconds": IDLE_WITHIN_SECONDS,
            },
            status=status.HTTP_200_OK,
        )


class PresenceBatchView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        raw = request.GET.get("user_ids", "")
        try:
            requested_ids = {
                int(s.strip()) for s in raw.split(",") if s.strip()
            }
        except (TypeError, ValueError):
            return Response(
                {"detail": "user_ids invalide (attendu : '1,2,3')."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # On limite l'inflation côté serveur — un client pourrait demander
        # 10000 IDs, le cache.get_many ferait un bombardement Redis.
        requested_ids.discard(None)
        if len(requested_ids) > 500:
            return Response(
                {"detail": "Trop d'IDs demandés (max 500)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # SECURITY — on filtre pour ne retourner QUE les statuts des users
        # visibles par le caller (même workspace ou superadmin).
        visible_ids = set(
            users_for_user(request.user)
            .filter(pk__in=requested_ids)
            .values_list("pk", flat=True)
        )
        # On inclut toujours le user lui-même
        visible_ids.add(request.user.id)

        statuses = PresenceService.get_many(visible_ids)
        return Response(
            {
                "statuses": [s.to_dict() for s in statuses.values()],
                "ts_server": __import__("time").time(),
            },
            status=status.HTTP_200_OK,
        )
