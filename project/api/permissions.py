"""
DevFlow REST API — Permissions & viewset mixins (Phase 0 sécurité).

Le but : empêcher tout accès cross-tenant sur les endpoints DRF, en deux
couches :

1. ``WorkspaceScopedViewSetMixin.get_queryset`` filtre dès le départ les
   listes par workspace de l'utilisateur connecté. Un user ne voit que
   les objets de ses workspaces, point.

2. ``IsWorkspaceMember.has_object_permission`` est une seconde ligne de
   défense au niveau objet (utile pour les actions personnalisées qui
   font ``self.get_object()``).

Les deux mécanismes se cumulent volontairement (defense in depth).
"""

from __future__ import annotations

from django.db.models import Q
from rest_framework import permissions

from project import models as dm
from project.utils.workspaces import get_user_workspace_ids


# ---------------------------------------------------------------------------
# Helpers — résolution du workspace pour un objet ou un queryset
# ---------------------------------------------------------------------------
def _resolve_object_workspace_id(obj):
    """
    Retourne l'ID du workspace auquel un objet DRF appartient, peu importe
    la profondeur de la relation. Aligné sur ``DevflowBaseMixin.filter_by_workspace``.

    Retourne None si on ne peut pas déterminer le workspace (l'objet sera
    alors refusé par sécurité).
    """
    if obj is None:
        return None

    # Cas direct : Workspace lui-même
    if isinstance(obj, dm.Workspace):
        return obj.pk

    # FK directe vers workspace
    ws_id = getattr(obj, "workspace_id", None)
    if ws_id is not None:
        return ws_id

    # Chemins indirects fréquents
    for attr in ("project", "team", "task", "sprint", "milestone", "objective",
                 "roadmap", "channel", "invoice", "meeting"):
        related = getattr(obj, attr, None)
        if related is not None:
            related_ws = getattr(related, "workspace_id", None)
            if related_ws is not None:
                return related_ws

    # BillingRate : via user.profile.workspace ou team.workspace
    if isinstance(obj, dm.BillingRate):
        team = getattr(obj, "team", None)
        if team and getattr(team, "workspace_id", None):
            return team.workspace_id
        user = getattr(obj, "user", None)
        profile = getattr(user, "profile", None) if user else None
        if profile and getattr(profile, "workspace_id", None):
            return profile.workspace_id

    return None


def scope_queryset_to_user_workspaces(queryset, user):
    """
    Filtre un queryset DRF aux workspaces accessibles à l'utilisateur.

    La logique de mapping (workspace direct, via project, via team…) est
    alignée sur ``DevflowBaseMixin.filter_by_workspace`` utilisée par les
    vues HTML pour rester cohérent entre les deux surfaces.
    """
    workspace_ids = get_user_workspace_ids(user)
    if not workspace_ids:
        return queryset.none()

    model = queryset.model
    field_names = {f.name for f in model._meta.get_fields() if hasattr(f, "name")}

    # Workspace lui-même
    if model is dm.Workspace:
        return queryset.filter(id__in=workspace_ids)

    # FK directe vers workspace
    if "workspace" in field_names:
        return queryset.filter(workspace_id__in=workspace_ids)

    # BillingRate : pas de FK directe → user.profile.workspace OU team.workspace
    if model is dm.BillingRate:
        return queryset.filter(
            Q(team__workspace_id__in=workspace_ids)
            | Q(user__profile__workspace_id__in=workspace_ids)
        ).distinct()

    # Relations indirectes communes
    for attr in ("project", "team", "task", "sprint", "milestone", "objective",
                 "roadmap", "channel", "invoice", "meeting"):
        if attr in field_names:
            return queryset.filter(**{f"{attr}__workspace_id__in": workspace_ids})

    # Pas de chemin trouvé → on bloque par sécurité plutôt que de tout exposer.
    return queryset.none()


# ---------------------------------------------------------------------------
# Permission
# ---------------------------------------------------------------------------
class IsWorkspaceMember(permissions.BasePermission):
    """
    SECURITY (Phase 0) — Permission DRF object-level :

    L'utilisateur doit être membre (profile, owner ou via TeamMembership) du
    workspace de l'objet manipulé. Voir
    ``project.utils.workspaces.get_user_workspace_ids``.

    À combiner avec ``IsAuthenticated`` et le ``WorkspaceScopedViewSetMixin``
    pour une défense en profondeur.
    """

    message = "Vous n'êtes pas membre du workspace de cet objet."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False

        obj_ws_id = _resolve_object_workspace_id(obj)
        if obj_ws_id is None:
            # On ne peut pas déterminer le workspace → on refuse par sécurité.
            return False

        return obj_ws_id in get_user_workspace_ids(request.user)


# ---------------------------------------------------------------------------
# Mixin viewset — filtrage automatique du queryset
# ---------------------------------------------------------------------------
class WorkspaceScopedViewSetMixin:
    """
    Mixin pour ``ModelViewSet`` qui scope automatiquement le queryset aux
    workspaces accessibles à l'utilisateur connecté.

    À combiner avec ``permission_classes = [IsAuthenticated, IsWorkspaceMember]``.
    """

    def get_queryset(self):
        queryset = super().get_queryset()
        user = getattr(self.request, "user", None)
        if not user or not user.is_authenticated:
            return queryset.none()
        return scope_queryset_to_user_workspaces(queryset, user)
