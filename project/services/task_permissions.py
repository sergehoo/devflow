"""
Droits de modification d'une tâche — source unique pour l'API REST.

Réutilise strictement les règles déjà présentes dans DevFlow (aucune règle
nouvelle) :

* matrice RBAC (``project.services.rbac.ROLE_PERMISSIONS``) :
  ``task.*`` (propriétaire du workspace, chef de projet), ``task.edit_team``
  (team lead, sur le périmètre de ses équipes), ``task.update_own`` (membre,
  sur ses propres tâches), ``task.delete`` (jamais accordé au membre) ;
* responsables du projet (owner / product manager), déjà reconnus par
  ``task_assignment.can_reassign`` et l'arbitrage (prolonger / expirer) ;
* réaffectation : ``task_assignment.can_reassign``.
"""

from __future__ import annotations

from project import models as dm
from project.services.rbac import RBACService


def _is_project_lead(user, task) -> bool:
    project = task.project
    return bool(project and user.pk in (project.owner_id, project.product_manager_id))


def _is_assigned(user, task) -> bool:
    if task.assignee_id == user.pk:
        return True
    return dm.TaskAssignment.objects.filter(task=task, user=user, is_active=True).exists()


def _in_led_team_scope(user, task) -> bool:
    """Périmètre ``task.edit_team`` : équipes dont l'utilisateur est lead ou membre."""
    team_ids = set(
        dm.TeamMembership.objects.filter(user=user, workspace_id=task.workspace_id, team__isnull=False)
        .values_list("team_id", flat=True)
    )
    team_ids |= set(dm.Team.objects.filter(lead=user, workspace_id=task.workspace_id).values_list("id", flat=True))
    if not team_ids:
        return False
    if task.project_id and task.project.team_id in team_ids:
        return True
    return bool(task.assignee_id and dm.TeamMembership.objects.filter(
        user_id=task.assignee_id, team_id__in=team_ids,
    ).exists())


def can_edit_task(user, task) -> bool:
    if user is None or not user.is_authenticated:
        return False
    if user.is_superuser or RBACService.can(user, "task.edit", target=task) or _is_project_lead(user, task):
        return True
    if RBACService.can(user, "task.edit_team", target=task) and _in_led_team_scope(user, task):
        return True
    return RBACService.can(user, "task.update_own", target=task) and _is_assigned(user, task)


def can_delete_task(user, task) -> bool:
    if user is None or not user.is_authenticated:
        return False
    return bool(user.is_superuser or RBACService.can(user, "task.delete", target=task) or _is_project_lead(user, task))
