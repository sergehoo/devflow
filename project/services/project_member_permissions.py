"""
Droits de gestion des affectations projet (``ProjectMember``) — source unique
pour les vues Django historiques et l'API de la fiche projet React.

Réutilise strictement les règles existantes de DevFlow (aucun nouveau rôle) :

* matrice RBAC (``project.services.rbac.ROLE_PERMISSIONS``) :
  ``project.edit`` (propriétaire du workspace, chef de projet) ou
  ``team.manage_members`` (team lead) ;
* responsables du projet (owner / product manager), déjà reconnus par
  ``task_permissions._is_project_lead``.

Un simple membre (RBAC ``MEMBER``) ou un client ne peut ni ajouter, ni
modifier, ni retirer une affectation.
"""

from __future__ import annotations

from project.services.rbac import RBACService

MEMBER_MANAGEMENT_ACTIONS = ("project.edit", "team.manage_members")


def can_manage_members_in_workspace(user, workspace) -> bool:
    """Droit RBAC de gérer les affectations projet dans ``workspace``."""
    if user is None or not getattr(user, "is_authenticated", False) or workspace is None:
        return False
    if user.is_superuser:
        return True
    return any(RBACService.can(user, action, workspace=workspace) for action in MEMBER_MANAGEMENT_ACTIONS)


def can_manage_project_members(user, project) -> bool:
    """Droit d'ajouter / modifier / retirer les membres de ``project``."""
    if user is None or not getattr(user, "is_authenticated", False) or project is None:
        return False
    if user.is_superuser or user.pk in (project.owner_id, project.product_manager_id):
        return True
    return can_manage_members_in_workspace(user, project.workspace)


__all__ = ["can_manage_members_in_workspace", "can_manage_project_members"]
