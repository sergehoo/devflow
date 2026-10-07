"""
Réaffectation de tâche — point d'entrée unique (modale « Réaffecter »,
API rapide, vue HTML historique).

Qui peut réaffecter une tâche :
  * un rôle RBAC disposant de ``task.assign`` (owner, PM, team lead) ;
  * le responsable / product manager du projet ;
  * l'assigné actuel (il peut passer la main).
Le nouveau mandataire doit appartenir au workspace de la tâche.
"""

from __future__ import annotations

from django.db.models import Count, Q

from project import models as dm
from project.utils.workspaces import users_in_workspaces

OPEN_EXCLUDED = [dm.Task.Status.DONE, dm.Task.Status.CANCELLED]


class ReassignError(Exception):
    """Réaffectation refusée (droits, utilisateur hors workspace…)."""


def can_reassign(user, task) -> bool:
    from project.services.rbac import RBACService

    if user is None or not user.is_authenticated:
        return False
    if RBACService.can(user, "task.assign", target=task):
        return True
    project = task.project
    return user.pk in {task.assignee_id, project.owner_id if project else None,
                       project.product_manager_id if project else None}


def assignable_users(task, query: str = "", limit: int = 60) -> list[dict]:
    """Membres du workspace, participants du projet en premier, avec leur charge."""
    users = users_in_workspaces([task.workspace_id])
    query = (query or "").strip()
    if query:
        users = users.filter(
            Q(first_name__icontains=query) | Q(last_name__icontains=query)
            | Q(username__icontains=query) | Q(email__icontains=query)
        )
    users = list(users.order_by("first_name", "last_name", "username")[:limit])
    ids = [u.pk for u in users]
    project_ids = set(
        dm.ProjectMember.objects.filter(project_id=task.project_id, user_id__in=ids)
        .values_list("user_id", flat=True)
    )
    load = dict(
        dm.Task.objects.filter(workspace_id=task.workspace_id, is_archived=False, assignee_id__in=ids)
        .exclude(status__in=OPEN_EXCLUDED)
        .values("assignee_id").annotate(n=Count("id")).values_list("assignee_id", "n")
    )
    titles = dict(
        dm.TeamMembership.objects.filter(workspace_id=task.workspace_id, user_id__in=ids)
        .exclude(job_title="").values_list("user_id", "job_title")
    )
    rows = [
        {
            "id": u.pk,
            "name": u.get_full_name() or u.get_username(),
            "email": u.email,
            "job_title": titles.get(u.pk, ""),
            "is_project_member": u.pk in project_ids,
            "is_current": u.pk == task.assignee_id,
            "open_tasks": load.get(u.pk, 0),
        }
        for u in users
    ]
    rows.sort(key=lambda r: (not r["is_current"], not r["is_project_member"], r["name"].lower()))
    return rows


def reassign(task, new_user_id, *, actor, note: str = ""):
    """Affecte la tâche (``None`` = retirer l'assignation). Retourne le nouvel assigné."""
    if not can_reassign(actor, task):
        raise ReassignError("Vous n'avez pas le droit de réaffecter cette tâche.")

    if new_user_id in (None, "", "null", 0, "0"):
        task.unassign(actor=actor)
        new_user = None
    else:
        new_user = users_in_workspaces([task.workspace_id]).filter(pk=new_user_id).first()
        if new_user is None:
            raise ReassignError("Ce collaborateur n'appartient pas au workspace de la tâche.")
        if new_user.pk != task.assignee_id:
            task.assign(new_user, assigned_by=actor)

    note = (note or "").strip()
    if note:
        target = new_user.get_full_name() or new_user.get_username() if new_user else "personne"
        dm.TaskComment.objects.create(
            task=task, author=actor, body=f"Réaffectation à {target} : {note}"[:5000],
        )
    return new_user
