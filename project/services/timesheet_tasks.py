"""
Tâches créées ou rattachées depuis le timesheet.

Le timesheet n'a pas de tâches à lui : une ligne « tâche » de la grille est la
``dm.Task`` du projet, la même que celle de /tasks, de la fiche projet et du Suivi
Pôle Développement. Ce module est le seul chemin d'écriture du timesheet vers les
tâches :

* ``create_task``       crée une vraie tâche dans un projet de l'espace courant,
                        assignée au collaborateur, puis y saisit éventuellement des
                        heures (``task_time.record_task_time``) ;
* ``convert_activity``  transforme une activité libre (libellé texte sans tâche) en
                        tâche — ou la rattache à la tâche ouverte de même intitulé
                        déjà affectée au collaborateur — et y relie ses saisies
                        encore modifiables.

Les mises à jour d'une tâche existante (statut, avancement, temps du jour,
commentaire) passent par la mise à jour rapide (``task_quick_update``), comme
depuis la liste des tâches ou la fiche tâche.
"""

from __future__ import annotations

from datetime import date

from django.db import transaction
from django.db.models import Q

from project import models as dm
from project.services.activity_logs import log_activity
from project.services.rbac import RBACService
from project.services.task_sync import apply_status, sync_assignee
from project.services.tracking_import import key

TITLE_MAX = 220
EntryStatus = dm.TimesheetEntry.ApprovalStatus
EDITABLE = (EntryStatus.DRAFT, EntryStatus.REJECTED)


class TimesheetTaskError(Exception):
    """Création / conversion refusée (message affichable, code HTTP)."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _check_access(user, workspace) -> None:
    """Accès aux tâches internes de l'espace (un rôle client n'en a aucun)."""
    if workspace is None:
        raise TimesheetTaskError("Aucun espace de travail sélectionné.", status=404)
    perms = RBACService.user_permissions(user, workspace)
    if not ("*" in perms or any(p.startswith("task.") for p in perms)):
        raise TimesheetTaskError("Vous ne pouvez pas créer de tâche dans cet espace.", status=403)


def _project(workspace, project_id):
    if not str(project_id or "").strip().isdigit():
        raise TimesheetTaskError("Projet invalide.")
    project = dm.Project.objects.filter(workspace=workspace, pk=int(project_id), is_archived=False).first()
    if project is None:
        raise TimesheetTaskError("Projet introuvable.", status=404)
    return project


def _title(value) -> str:
    title = " ".join(str(value or "").split())
    if not title:
        raise TimesheetTaskError("L'intitulé de la tâche est obligatoire.")
    if len(title) > TITLE_MAX:
        raise TimesheetTaskError(f"L'intitulé ne peut pas dépasser {TITLE_MAX} caractères.")
    return title


def _day(value, label):
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        raise TimesheetTaskError(f"{label} invalide (AAAA-MM-JJ attendu).") from None


def _new_task(user, project, title, *, status, start_date=None, due_date=None, description="", origin):
    task = dm.Task(
        workspace=project.workspace, project=project, title=title, description=description,
        reporter=user, start_date=start_date, due_date=due_date,
    )
    apply_status(task, status)
    task.save()
    # Même état que Task.assign() (assigné + affectation active), sans se notifier
    # soi-même « une tâche vous a été assignée ».
    dm.Task.objects.filter(pk=task.pk).update(assignee=user)
    task.assignee = user
    sync_assignee(task, None, actor=user)
    log_activity(
        workspace=project.workspace, actor=user, project=project, task=task,
        activity_type=dm.ActivityLog.ActivityType.TASK_CREATED,
        title=f"Tâche créée depuis le timesheet : {title}"[:200],
        description=f"{user.get_full_name() or user.get_username()} a créé « {title} » depuis son timesheet.",
        metadata={"source": "timesheet", "origin": origin, "task_id": task.pk},
    )
    return task


@transaction.atomic
def create_task(user, workspace, *, project_id, title, start_date=None, due_date=None, description="",
                hours=None, entry_date=None):
    """
    Crée la tâche (assignée à ``user``) et, si ``hours`` est renseigné, saisit ce temps
    au jour ``entry_date``. Tout ou rien : une saisie refusée (semaine verrouillée,
    plus de 24 h) annule aussi la création.
    """
    from project.services.task_time import TaskTimeError, record_task_time

    _check_access(user, workspace)
    project = _project(workspace, project_id)
    title = _title(title)
    day = _day(entry_date, "Jour")
    start, due = _day(start_date, "Date de début") or day, _day(due_date, "Échéance")
    if start and due and due < start:
        raise TimesheetTaskError("L'échéance précède la date de début.")
    with_time = str(hours or "").strip() not in ("", "0", "0.0", "0,0")
    task = _new_task(
        user, project, title, start_date=start, due_date=due, description=str(description or "")[:5000],
        status=dm.Task.Status.IN_PROGRESS if with_time else dm.Task.Status.TODO, origin="create",
    )
    entry = None
    if with_time:
        try:
            entry = record_task_time(task=task, user=user, hours=hours, entry_date=day)
        except TaskTimeError as exc:
            raise TimesheetTaskError(str(exc)) from exc
    return task, entry


def _matching_task(user, project, label):
    """Tâche ouverte du projet, de même intitulé, déjà affectée au collaborateur."""
    wanted = key(label)
    candidates = (
        dm.Task.objects.filter(project=project, is_archived=False)
        .exclude(status__in=[dm.Task.Status.DONE, dm.Task.Status.CANCELLED])
        .filter(Q(assignee=user) | Q(assignments__user=user, assignments__is_active=True))
        .distinct().order_by("parent_id", "id")
    )
    return next((t for t in candidates if key(t.title) == wanted), None)


@transaction.atomic
def convert_activity(user, workspace, *, project_id, description):
    """
    Activité libre ``description`` sur ``project`` → tâche. Renvoie ``(task, saisies reliées, créée)``.

    Seules les saisies modifiables (brouillon ou rejetée, semaine non verrouillée) sont
    reliées : une saisie soumise ou validée reste telle que le manager l'a vue.
    """
    from project.services import realtime
    from project.services import timesheet_workflow as tw
    from project.services.task_time import sync_spent_hours

    _check_access(user, workspace)
    project = _project(workspace, project_id)
    label = str(description or "").strip()
    if not label:
        raise TimesheetTaskError("Libellé d'activité manquant.")
    entries = list(
        dm.TimesheetEntry.objects.select_for_update()
        .filter(user=user, workspace=workspace, project=project, task__isnull=True, description__iexact=label)
        .order_by("entry_date", "id")
    )
    if not entries:
        raise TimesheetTaskError("Activité introuvable dans votre timesheet.", status=404)
    locked_weeks = set()
    for monday in {tw.week_bounds(e.entry_date)[0] for e in entries}:
        try:
            tw.assert_week_editable(user, workspace, monday)
        except tw.TimesheetWorkflowError:
            locked_weeks.add(monday)
    editable = [e for e in entries
                if e.approval_status in EDITABLE and tw.week_bounds(e.entry_date)[0] not in locked_weeks]
    if not editable:
        raise TimesheetTaskError("Ces saisies sont soumises ou validées : elles ne peuvent plus être converties.")

    task = _matching_task(user, project, label)
    created = task is None
    if created:
        task = _new_task(user, project, _title(label[:TITLE_MAX]), status=dm.Task.Status.IN_PROGRESS,
                         start_date=editable[0].entry_date, origin="activity")
    dm.TimesheetEntry.objects.filter(pk__in=[e.pk for e in editable]).update(task=task)
    sync_spent_hours({task.pk})
    for day in {e.entry_date for e in editable if e.approval_status == EntryStatus.REJECTED}:
        tw.reopen_rejected_for_correction(user, workspace, day)
    realtime.tasks_changed(task_ids=[task.pk], user_ids=[user.pk])
    return task, len(editable), created
