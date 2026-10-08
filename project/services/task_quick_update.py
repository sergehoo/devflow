"""
Mise à jour rapide d'une tâche (fiche tâche, liste, kanban).

Une seule opération atomique : statut, avancement, temps passé (timesheet
de l'assigné via ``task_time``) et commentaire. Réservée à l'assigné, comme
les autres actions rapides opérationnelles.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from project import models as dm

Status = dm.Task.Status
QUICK_STATUSES = [Status.TODO, Status.IN_PROGRESS, Status.REVIEW, Status.BLOCKED, Status.DONE]


class QuickUpdateError(Exception):
    """Mise à jour refusée ou invalide (message affichable)."""


def task_state(task, user) -> dict:
    return {
        "id": task.pk,
        "title": task.title,
        "status": task.status,
        "status_label": task.get_status_display(),
        "progress_percent": task.progress_percent,
        "spent_hours": str(task.spent_hours or 0),
        "estimate_hours": str(task.estimate_hours) if task.estimate_hours is not None else None,
        "assignee_id": task.assignee_id,
        "assignee_name": (task.assignee.get_full_name() or task.assignee.get_username()) if task.assignee_id else "",
        "can_update": bool(user and task.assignee_id == user.pk),
        "statuses": [{"value": s.value, "label": s.label} for s in QUICK_STATUSES],
    }


def _parse_progress(value) -> int:
    try:
        progress = int(float(str(value).replace(",", ".")))
    except (TypeError, ValueError):
        raise QuickUpdateError("L'avancement doit être un nombre entre 0 et 100.")
    if not 0 <= progress <= 100:
        raise QuickUpdateError("L'avancement doit être compris entre 0 et 100 %.")
    return progress


@transaction.atomic
def apply_quick_update(task, user, data) -> dict:
    if task.assignee_id != user.pk:
        raise QuickUpdateError("Seul le collaborateur assigné peut mettre à jour cette tâche.")

    data = data or {}
    new_status = data.get("status") or None
    progress = data.get("progress_percent")
    hours = data.get("spent_hours")
    comment = (data.get("comment") or "").strip()
    changed = []

    if new_status is not None:
        if new_status not in {s.value for s in QUICK_STATUSES}:
            raise QuickUpdateError("Statut non autorisé.")
        if new_status == Status.BLOCKED and new_status != task.status and not comment:
            raise QuickUpdateError("Indiquez la raison du blocage dans le commentaire.")

    if new_status is not None and new_status != task.status:
        now = timezone.now()
        task.status = new_status
        if new_status == Status.IN_PROGRESS and not task.started_at:
            task.started_at = now
        if new_status == Status.DONE:
            task.completed_at = task.completed_at or now
            task.started_at = task.started_at or now
            task.progress_percent = 100
        else:
            task.completed_at = None
        changed += ["status", "started_at", "completed_at", "progress_percent"]

    if progress not in (None, ""):
        task.progress_percent = 100 if task.status == Status.DONE else _parse_progress(progress)
        changed.append("progress_percent")

    if changed:
        task.save(update_fields=sorted(set(changed)) + ["updated_at"])

    if hours not in (None, "", 0, "0"):
        from project.services.task_time import TaskTimeError, record_task_time

        try:
            record_task_time(task=task, user=user, hours=hours)
        except TaskTimeError as exc:
            raise QuickUpdateError(str(exc)) from exc
        task.refresh_from_db(fields=["spent_hours"])

    if comment:
        dm.TaskComment.objects.create(task=task, author=user, body=comment[:5000])

    if not (changed or hours not in (None, "", 0, "0") or comment):
        raise QuickUpdateError("Aucune modification à enregistrer.")
    return task_state(task, user)
