"""
DevFlow — Service RBAC central (PR23 — Sécurité globale).

Définit la matrice de permissions, la résolution de rôle par workspace,
et l'API publique ``RBACService.can(user, action, target=None, workspace=None)``
utilisée par :
  * les vues HTML (via context processor)
  * les viewsets DRF (permission custom)
  * les templates (via {% if user_can ... %})

Convention "action" : ``"<domaine>.<verbe>"`` (ex: ``project.edit``,
``budget.view``). Le wildcard ``"*"`` (ou ``"domaine.*"``) accorde tout.

Rôles (ordre décroissant) :
  1. SUPER_ADMIN        — User.is_superuser, accès total
  2. WORKSPACE_OWNER    — Workspace.owner OU role explicite
  3. PROJECT_MANAGER    — gère projets, sprints, tâches, rapports (PAS finance)
  4. TEAM_LEAD          — gère son équipe + tâches équipe (PAS finance)
  5. MEMBER             — accès limité à ses tâches + timesheet perso
  6. CLIENT             — vue projet + livrables, AUCUNE donnée interne
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from django.contrib.auth import get_user_model

from project import models as dm

logger = logging.getLogger(__name__)
User = get_user_model()


# ---------------------------------------------------------------------------
# Constantes rôles (alignées sur WorkspaceRoleAssignment.Role)
# ---------------------------------------------------------------------------
SUPER_ADMIN = "SUPER_ADMIN"
WORKSPACE_OWNER = "WORKSPACE_OWNER"
PROJECT_MANAGER = "PROJECT_MANAGER"
TEAM_LEAD = "TEAM_LEAD"
MEMBER = "MEMBER"
CLIENT = "CLIENT"

ROLE_ORDER = [
    SUPER_ADMIN, WORKSPACE_OWNER, PROJECT_MANAGER,
    TEAM_LEAD, MEMBER, CLIENT,
]


# ---------------------------------------------------------------------------
# Matrice de permissions
# ---------------------------------------------------------------------------
# Chaque rôle reçoit un set d'actions. Le wildcard ``*`` accorde TOUT.
# Le wildcard ``<domaine>.*`` accorde tout sur ce domaine.
ROLE_PERMISSIONS: dict[str, set[str]] = {
    SUPER_ADMIN: {"*"},
    WORKSPACE_OWNER: {
        "workspace.manage", "workspace.delete", "workspace.view",
        "members.manage", "members.invite", "members.remove",
        "project.*", "task.*", "sprint.*", "milestone.*", "roadmap.*",
        "backlog.*", "objective.*", "risk.*",
        "budget.*", "billing.*", "invoice.*", "timesheet.*",
        "team.*", "report.*", "ai.*", "ai_report.*",
        "settings.manage", "integration.manage", "webhook.manage",
        "field.*", "real_estate.*", "admin_case.*", "phase.*",
        "audit.view", "audit.export",
    },
    PROJECT_MANAGER: {
        "workspace.view",
        "project.view", "project.create", "project.edit",
        "task.*", "sprint.*", "milestone.*", "roadmap.view",
        "backlog.*", "objective.view", "risk.view", "risk.create",
        "report.view", "report.generate",
        "timesheet.view_team", "timesheet.approve",
        "team.view", "team.assign",
        "ai.summarize", "ai.recommend", "ai.generate_roadmap",
        "ai_report.view", "ai_report.generate",
        "field.*", "real_estate.view", "admin_case.*", "phase.*",
        # PAS de gestion finance directe (lecture seule)
        "budget.view", "billing.view", "invoice.view",
    },
    TEAM_LEAD: {
        "workspace.view",
        "project.view",
        "task.view", "task.assign", "task.edit_team",
        "sprint.view",
        "team.view", "team.manage_members",
        "timesheet.view_team", "timesheet.approve_team",
        "report.view",
        "notification.view",
        "ai.summarize",
    },
    MEMBER: {
        "workspace.view",
        "project.view_assigned",
        "task.view_assigned", "task.update_own", "task.comment",
        "timesheet.create_own", "timesheet.view_own",
        "notification.view",
        "comment.create",
        "ai.summarize",
        # explicitement PAS : budget.*, team.manage, report.generate,
        # task.delete, project.create, etc.
    },
    CLIENT: {
        "project.view_assigned",
        "deliverable.view",
        "document.view_shared",
        "comment.create",
        "notification.view",
        # AUCUNE donnée interne : pas de tâches détaillées, pas de
        # budget, pas de timesheet, pas de team.
    },
}


# ---------------------------------------------------------------------------
# Service public
# ---------------------------------------------------------------------------
class RBACService:
    """
    API publique pour la résolution de rôle et le check de permission.

    Usage typique :
        from project.services.rbac import RBACService

        if not RBACService.can(request.user, "budget.edit", workspace=ws):
            raise PermissionDenied()
    """

    # ─── Résolution de rôle ─────────────────────────────────────────────
    @classmethod
    def is_super_admin(cls, user) -> bool:
        return bool(user and user.is_authenticated and (
            user.is_superuser or getattr(user, "is_staff", False) and
            getattr(user, "_devflow_force_super", False)
        )) or (user and user.is_authenticated and user.is_superuser)

    @classmethod
    def get_role_for(cls, user, workspace) -> str:
        """
        Retourne le rôle effectif d'un user dans un workspace.

        Priorité :
          1. SUPER_ADMIN si is_superuser
          2. WORKSPACE_OWNER si Workspace.owner == user
          3. Rôle de WorkspaceRoleAssignment(user, workspace)
          4. MEMBER par défaut si le user a accès au workspace
             (via TeamMembership ou UserProfile.workspace)
          5. None si pas d'accès du tout
        """
        if user is None or not user.is_authenticated:
            return None
        if user.is_superuser:
            return SUPER_ADMIN
        if workspace is None:
            return None

        ws_id = getattr(workspace, "pk", None) or getattr(workspace, "id", None)
        if ws_id is None:
            return None

        if getattr(workspace, "owner_id", None) == user.pk:
            return WORKSPACE_OWNER

        # Rôle explicite ?
        assignment = (
            dm.WorkspaceRoleAssignment.objects
            .filter(user=user, workspace_id=ws_id)
            .only("role")
            .first()
        )
        if assignment:
            return assignment.role

        # Sinon : MEMBER si accès workspace (membership ou profile)
        has_access = (
            dm.TeamMembership.objects.filter(
                user=user, workspace_id=ws_id,
            ).exists()
            or getattr(
                getattr(user, "profile", None), "workspace_id", None,
            ) == ws_id
        )
        return MEMBER if has_access else None

    @classmethod
    def get_all_workspace_roles(cls, user) -> dict[int, str]:
        """Retourne {workspace_id: role} pour tous les workspaces du user."""
        if user is None or not user.is_authenticated:
            return {}
        if user.is_superuser:
            # SuperAdmin : on retourne tous les workspaces non archivés
            return {
                ws_id: SUPER_ADMIN
                for ws_id in dm.Workspace.objects
                    .filter(is_archived=False)
                    .values_list("id", flat=True)
            }

        roles: dict[int, str] = {}
        # Workspaces possédés → WORKSPACE_OWNER
        for ws_id in dm.Workspace.objects.filter(
            owner=user, is_archived=False,
        ).values_list("id", flat=True):
            roles[ws_id] = WORKSPACE_OWNER

        # Rôles explicites
        for assignment in dm.WorkspaceRoleAssignment.objects.filter(
            user=user, workspace__is_archived=False,
        ).only("workspace_id", "role"):
            # On ne dégrade pas un Owner par une autre assignation
            if roles.get(assignment.workspace_id) != WORKSPACE_OWNER:
                roles[assignment.workspace_id] = assignment.role

        # MEMBER par défaut pour les workspaces accessibles non encore listés
        from project.utils.workspaces import get_user_workspace_ids
        accessible = get_user_workspace_ids(user)
        for ws_id in accessible:
            roles.setdefault(ws_id, MEMBER)

        return roles

    # ─── Vérification de permission ─────────────────────────────────────
    @classmethod
    def _permissions_for_role(cls, role: str) -> set[str]:
        return ROLE_PERMISSIONS.get(role, set())

    @classmethod
    def _matches(cls, granted: set[str], action: str) -> bool:
        """Vérifie si une action est couverte par un set (avec wildcards)."""
        if "*" in granted:
            return True
        if action in granted:
            return True
        # Wildcard de domaine : "project.*" couvre "project.edit"
        domain = action.split(".", 1)[0] if "." in action else action
        return f"{domain}.*" in granted

    @classmethod
    def can(
        cls, user, action: str, *,
        target: Any = None, workspace=None,
    ) -> bool:
        """
        Retourne True si ``user`` peut effectuer ``action``.

        Args :
            user      : Django user (anonymous → False)
            action    : "domaine.verbe" (ex: "task.edit")
            target    : objet métier (ex: Task instance) — utilisé pour
                        dériver le workspace si pas fourni
            workspace : Workspace instance (ou None si on l'infère du target)
        """
        if user is None or not getattr(user, "is_authenticated", False):
            return False
        if user.is_superuser:
            return True  # accès total

        # Résolution du workspace cible
        if workspace is None and target is not None:
            workspace = cls._workspace_of(target)

        if workspace is None:
            # Action globale (rare) : autorisée pour SUPER_ADMIN uniquement,
            # déjà géré ci-dessus → refus sinon.
            return False

        role = cls.get_role_for(user, workspace)
        if role is None:
            return False

        permissions = cls._permissions_for_role(role)
        return cls._matches(permissions, action)

    @classmethod
    def _workspace_of(cls, target) -> Any:
        """Dérive le workspace d'un objet métier (FK directe ou via chaîne)."""
        if target is None:
            return None
        if isinstance(target, dm.Workspace):
            return target
        if getattr(target, "workspace_id", None):
            return getattr(target, "workspace", None)
        for attr in ("project", "team", "task", "sprint", "milestone",
                     "channel", "meeting"):
            related = getattr(target, attr, None)
            if related and getattr(related, "workspace_id", None):
                return related.workspace
        return None

    # ─── Helpers UI ─────────────────────────────────────────────────────
    @classmethod
    def user_permissions(cls, user, workspace=None) -> set[str]:
        """Retourne les permissions effectives d'un user dans un workspace."""
        if user is None or not user.is_authenticated:
            return set()
        if user.is_superuser:
            return {"*"}
        role = cls.get_role_for(user, workspace) if workspace else None
        if role is None:
            return set()
        return cls._permissions_for_role(role)

    @classmethod
    def role_label(cls, role: str) -> str:
        """Label lisible humain pour un rôle."""
        if role == SUPER_ADMIN:
            return "Super administrateur"
        for r in dm.WorkspaceRoleAssignment.Role.choices:
            if r[0] == role:
                return r[1]
        return role


# ---------------------------------------------------------------------------
# Permission DRF — pour viewsets API
# ---------------------------------------------------------------------------
class HasRBACPermission:
    """
    Permission DRF basée sur RBAC. À utiliser ainsi sur un viewset :

        class MyViewSet(viewsets.ModelViewSet):
            permission_classes = [IsAuthenticated, HasRBACPermission]
            rbac_action_map = {
                "list":     "task.view",
                "retrieve": "task.view",
                "create":   "task.create",
                "update":   "task.edit",
                "destroy":  "task.delete",
            }
    """

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        # has_object_permission fait le check fin sur les actions detail
        return True

    def has_object_permission(self, request, view, obj):
        action_map = getattr(view, "rbac_action_map", {})
        action = action_map.get(view.action)
        if not action:
            return True  # pas de mapping → on laisse passer (déjà filtré ailleurs)
        return RBACService.can(request.user, action, target=obj)
