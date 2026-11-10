"""
Agilité (frontend React) : statut de sprint (board) et décalage de dates de
roadmap. Exécute les vues fonction existantes (scoping workspace + RBAC
``sprint.edit`` / ``roadmap.edit`` appliqués par elles).
"""

from __future__ import annotations

import json

from rest_framework import permissions
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView


def _call(fbv, request, payload: dict) -> Response:
    django_request = request._request
    django_request.user = request.user
    django_request._body = json.dumps(payload).encode()
    response = fbv(django_request)
    data = json.loads(response.content or b"{}")
    if isinstance(data, dict) and data.get("message") and response.status_code >= 400:
        data["detail"] = data["message"]
    return Response(data, status=response.status_code)


class SprintStatusAPI(APIView):
    """POST /api/v1/sprints/<pk>/status/ {status} → ``sprint_status_update``."""

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser]

    def post(self, request, pk):
        from project.views import sprint_status_update

        fn = sprint_status_update
        while hasattr(fn, "__wrapped__"):  # login_required / require_POST : déjà garantis par DRF
            fn = fn.__wrapped__
        return _call(fn, request, {"sprint_id": pk, "status": request.data.get("status")})


class RoadmapShiftAPI(APIView):
    """POST /api/v1/roadmap-items/<pk>/shift-dates/ {delta_days} → ``roadmap_item_shift_dates``."""

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser]

    def post(self, request, pk):
        from project.views import roadmap_item_shift_dates

        fn = roadmap_item_shift_dates
        while hasattr(fn, "__wrapped__"):
            fn = fn.__wrapped__
        return _call(fn, request, {"item_id": pk, "delta_days": request.data.get("delta_days", 0)})
