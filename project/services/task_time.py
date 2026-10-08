"""Enregistrement cohérent du temps passé lors des actions rapides sur tâche."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from project import models as dm


class TaskTimeError(Exception):
    """La saisie rapide de temps ne peut pas être enregistrée."""


def parse_hours(value) -> Decimal:
    """Parse une durée positive saisie par l'interface."""
    try:
        hours = Decimal(str(value).replace(",", "."))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise TaskTimeError("Indiquez un nombre d'heures valide.") from exc

    if hours <= 0:
        raise TaskTimeError("Le temps passé doit être supérieur à zéro.")
    if hours > Decimal("24"):
        raise TaskTimeError("Le temps passé ne peut pas dépasser 24 heures.")
    return hours


@transaction.atomic
def record_task_time(*, task: dm.Task, user, hours, entry_date: date | None = None):
    """Ajoute du temps au timesheet personnel et synchronise ``spent_hours``.

    Les actions rapides ne créent jamais une ligne pour un autre utilisateur.
    Le temps est ajouté à la ligne existante de la tâche pour la journée au
    lieu d'écraser une saisie manuelle précédente.
    """
    if task.assignee_id != user.id:
        raise TaskTimeError("Seul l'utilisateur actuellement assigné peut saisir du temps.")

    hours = parse_hours(hours)
    entry_date = entry_date or timezone.localdate()

    from project.services import timesheet_workflow as workflow

    try:
        workflow.assert_week_editable(user, task.workspace, entry_date)
    except workflow.TimesheetWorkflowError as exc:
        raise TaskTimeError(str(exc)) from exc

    daily_total = (
        dm.TimesheetEntry.objects.select_for_update()
        .filter(user=user, entry_date=entry_date)
        .aggregate(total=Sum("hours"))["total"]
        or Decimal("0")
    )
    if daily_total + hours > Decimal("24"):
        raise TaskTimeError("Cette saisie ferait dépasser 24 heures pour cette journée.")

    entry = (
        dm.TimesheetEntry.objects.select_for_update()
        .filter(user=user, task=task, entry_date=entry_date)
        .order_by("pk")
        .first()
    )
    if entry is None:
        entry = dm.TimesheetEntry.objects.create(
            user=user,
            workspace=task.workspace,
            project=task.project,
            task=task,
            entry_date=entry_date,
            hours=hours,
            is_billable=True,
            approval_status=dm.TimesheetEntry.ApprovalStatus.DRAFT,
            description="Saisie rapide depuis une mise à jour de tâche.",
        )
    else:
        entry.hours += hours
        entry.save(update_fields=["hours", "updated_at"])

    workflow.reopen_rejected_for_correction(user, task.workspace, entry_date)

    total_spent = (
        dm.TimesheetEntry.objects.filter(task=task).aggregate(total=Sum("hours"))["total"]
        or Decimal("0")
    )
    task.spent_hours = total_spent
    task.save(update_fields=["spent_hours", "updated_at"])
    return entry
