"""
Garde-fous métier des endpoints REST bruts ``/api/v1/tasks/`` et
``/api/v1/timesheets/``.

Ces endpoints restent en écriture (intégrations par jeton), mais appliquent
désormais les mêmes règles que l'interface Django :

* Tâches — droits réels (``services.task_permissions``), workspace imposé par
  le projet, cohérence sprint / backlog / parent avec le projet (``TaskForm.clean``),
  réaffectation soumise à ``can_reassign``, rapporteur non falsifiable.
* Timesheets — saisie réservée à l'employé (``_OwnTimesheetMixin``),
  lignes modifiables uniquement en brouillon / rejet (``_editable_own_entries``),
  semaines soumises / validées verrouillées (``assert_week_editable``),
  statut d'approbation piloté exclusivement par le workflow N+1.
"""

from __future__ import annotations

from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from project import models as dm
from project.utils.workspaces import user_can_access_workspace, users_in_workspaces


class WeekLocked(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Cette semaine est soumise ou validée : elle n'est plus modifiable."
    default_code = "week_locked"


# ---------------------------------------------------------------------------
# Tâches
# ---------------------------------------------------------------------------
def _check_task_relations(data, project, workspace_id):
    """Miroir de ``TaskForm.clean`` + scoping des FK au workspace de la tâche."""
    if project is not None and project.workspace_id != workspace_id:
        raise ValidationError({"project": "Ce projet n'appartient pas au workspace de la tâche."})
    sprint = data.get("sprint")
    if sprint is not None and project is not None and sprint.project_id != project.pk:
        raise ValidationError({"sprint": "Le sprint sélectionné n'appartient pas au projet choisi."})
    backlog = data.get("backlog_item")
    if backlog is not None and project is not None and backlog.project_id != project.pk:
        raise ValidationError({"backlog_item": "Le backlog item sélectionné n'appartient pas au projet choisi."})
    parent = data.get("parent")
    if parent is not None and parent.workspace_id != workspace_id:
        raise ValidationError({"parent": "La tâche parente n'appartient pas à ce workspace."})
    assignee = data.get("assignee")
    if assignee is not None and not users_in_workspaces([workspace_id]).filter(pk=assignee.pk).exists():
        raise ValidationError({"assignee": "Cet utilisateur n'est pas membre du workspace."})
    progress = data.get("progress_percent")
    if progress is not None and not 0 <= progress <= 100:
        raise ValidationError({"progress_percent": "Le pourcentage d'avancement doit être compris entre 0 et 100."})


def prepare_task_create(user, data) -> dict:
    """Retourne les valeurs imposées côté serveur pour ``serializer.save()``."""
    project = data.get("project")
    workspace = data.get("workspace")
    if project is not None:
        if workspace is not None and workspace.pk != project.workspace_id:
            raise ValidationError({"workspace": "Le workspace doit être celui du projet."})
        workspace = project.workspace
    if workspace is None:
        raise ValidationError({"workspace": "Ce champ est obligatoire."})
    if not user.is_superuser and not user_can_access_workspace(user, workspace):
        raise PermissionDenied("Vous n'avez pas accès à ce workspace.")
    _check_task_relations(data, project, workspace.pk)
    # TaskCreateView : le rapporteur est toujours l'auteur de la requête.
    return {"workspace": workspace, "reporter": user}


def check_task_update(user, task, data) -> None:
    from project.services.task_assignment import can_reassign
    from project.services.task_permissions import can_edit_task

    if not can_edit_task(user, task):
        raise PermissionDenied("Vous n'avez pas les droits pour modifier cette tâche.")
    if "workspace" in data and data["workspace"].pk != task.workspace_id:
        raise ValidationError({"workspace": "Le workspace d'une tâche ne peut pas être modifié."})
    if "reporter" in data and getattr(data["reporter"], "pk", None) != task.reporter_id:
        raise ValidationError({"reporter": "Le rapporteur d'une tâche ne peut pas être modifié."})
    if "assignee" in data and getattr(data["assignee"], "pk", None) != task.assignee_id and not can_reassign(user, task):
        raise PermissionDenied("Vous n'êtes pas autorisé à réaffecter cette tâche.")
    project = data.get("project", task.project)
    relations = dict(data)
    if "project" in data:  # changement de projet : sprint / backlog actuels doivent suivre
        relations.setdefault("sprint", task.sprint)
        relations.setdefault("backlog_item", task.backlog_item)
    _check_task_relations(relations, project, task.workspace_id)


def check_task_destroy(user, task) -> None:
    from project.services.task_permissions import can_delete_task

    if not can_delete_task(user, task):
        raise PermissionDenied("Suppression non autorisée pour votre rôle.")


# ---------------------------------------------------------------------------
# Timesheets
# ---------------------------------------------------------------------------
EDITABLE = (dm.TimesheetEntry.ApprovalStatus.DRAFT, dm.TimesheetEntry.ApprovalStatus.REJECTED)
DRAFT_RESET = {"approval_status": dm.TimesheetEntry.ApprovalStatus.DRAFT, "approved_by": None, "approved_at": None}


def _assert_editable(user, workspace, day):
    from project.services import timesheet_workflow as tw

    try:
        tw.assert_week_editable(user, workspace, day)
    except tw.TimesheetWorkflowError as exc:
        raise WeekLocked(str(exc)) from exc


def _check_entry_relations(data, workspace):
    project, task = data.get("project"), data.get("task")
    # TimesheetEntryForm : projets / tâches actifs du workspace uniquement.
    if project is not None and (project.workspace_id != workspace.pk or project.is_archived):
        raise ValidationError({"project": "Projet introuvable dans ce workspace."})
    if task is not None and (task.workspace_id != workspace.pk or task.is_archived):
        raise ValidationError({"task": "Tâche introuvable dans ce workspace."})


def _reject_other_user(user, data):
    if "user" in data and data["user"] is not None and data["user"].pk != user.pk:
        raise PermissionDenied("Vous ne pouvez saisir que vos propres temps.")


def prepare_entry_create(user, data) -> dict:
    from project.utils.workspaces import get_default_workspace_for_user

    _reject_other_user(user, data)
    workspace = data.get("workspace")
    for related in (data.get("project"), data.get("task")):
        if workspace is None and related is not None:
            workspace = related.workspace
    workspace = workspace or get_default_workspace_for_user(user)
    if workspace is None or not user_can_access_workspace(user, workspace):
        raise PermissionDenied("Vous n'avez pas accès à ce workspace.")
    _check_entry_relations(data, workspace)
    _assert_editable(user, workspace, data.get("entry_date") or timezone.localdate())
    return {"user": user, "workspace": workspace, **DRAFT_RESET}


def check_entry_update(user, entry, data) -> dict:
    if entry.user_id != user.pk:
        raise PermissionDenied("Seul l'auteur d'une saisie peut la modifier ; la validation passe par le workflow N+1.")
    _reject_other_user(user, data)
    if "workspace" in data and data["workspace"].pk != entry.workspace_id:
        raise ValidationError({"workspace": "Le workspace d'une saisie ne peut pas être modifié."})
    if entry.approval_status not in EDITABLE:
        raise WeekLocked()
    _check_entry_relations(data, entry.workspace)
    _assert_editable(user, entry.workspace, entry.entry_date)
    if "entry_date" in data:
        _assert_editable(user, entry.workspace, data["entry_date"])
    return dict(DRAFT_RESET)


def check_entry_destroy(user, entry) -> None:
    if entry.user_id != user.pk:
        raise PermissionDenied("Seul l'auteur d'une saisie peut la supprimer.")
    if entry.approval_status not in EDITABLE:
        raise WeekLocked()
