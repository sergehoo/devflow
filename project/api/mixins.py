"""
Mixins DRF partagés par les écrans React (Phase 3).

Ils reproduisent côté API les contrôles RBAC déjà appliqués par les vues
Django (``DevflowUpdateView.dispatch``, ``ArchiveObjectView``) : React ne
fait que masquer des boutons, l'autorisation reste ici.
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response


def require_rbac(user, rbac_action: str | None, target) -> None:
    if not rbac_action:
        return
    from project.services.rbac import RBACService

    if not RBACService.can(user, rbac_action, target=target):
        raise PermissionDenied("Action non autorisée pour votre rôle.")


class RBACUpdateArchiveMixin:
    """``update_rbac_action`` pour PUT/PATCH, ``archive_rbac_action`` pour POST …/archive/."""

    update_rbac_action: str | None = None
    archive_rbac_action: str | None = None

    def perform_update(self, serializer):
        require_rbac(self.request.user, self.update_rbac_action, serializer.instance)
        super().perform_update(serializer)

    @action(detail=True, methods=["post"], url_path="archive")
    def archive(self, request, pk=None):
        obj = self.get_object()
        require_rbac(request.user, self.archive_rbac_action, obj)
        obj.archive()
        return Response(status=status.HTTP_204_NO_CONTENT)
