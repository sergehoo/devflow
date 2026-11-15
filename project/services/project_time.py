"""
Temps des projets à partir des saisies de temps (``TimesheetEntry``).

* ``logged_hours`` : heures saisies sur le projet, ventilées entre les saisies sur
  une tâche et les lignes « activité » (projet sans tâche) de la grille hebdomadaire.
  C'est la même base que « Heures saisies » (budget) et « Temps saisi » (équipes).
* ``task_spent_hours`` : somme des ``Task.spent_hours`` (comparaison estimé / passé
  par tâche), alignés sur les saisies par les signaux de ``TimesheetEntry``.

Sans les activités hors tâche, les heures des collaborateurs qui saisissent
« Réunion », « Support »… sur un projet disparaissaient des fiches projet.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Q, Sum

from project import models as dm

ZERO = Decimal("0")


def _ids(project_ids) -> list[int]:
    return sorted({int(pk) for pk in project_ids if pk})


def activity_hours(project_ids) -> dict[int, Decimal]:
    """Heures des saisies « activité » (projet renseigné, aucune tâche), tous statuts confondus."""
    ids = _ids(project_ids)
    if not ids:
        return {}
    rows = (
        dm.TimesheetEntry.objects.filter(project_id__in=ids, task__isnull=True)
        .order_by().values("project_id").annotate(total=Sum("hours"))
    )
    return {row["project_id"]: row["total"] or ZERO for row in rows}


def task_spent_hours(project_ids) -> dict[int, Decimal]:
    ids = _ids(project_ids)
    if not ids:
        return {}
    rows = (
        dm.Task.objects.filter(project_id__in=ids, is_archived=False)
        .order_by().values("project_id").annotate(total=Sum("spent_hours"))
    )
    return {row["project_id"]: row["total"] or ZERO for row in rows}


def logged_hours(project_ids) -> dict[int, dict[str, Decimal]]:
    """``{project_id: {"tasks", "activities", "total"}}`` (heures saisies, tous statuts ; zéros inclus)."""
    ids = _ids(project_ids)
    out = {pk: {"tasks": ZERO, "activities": ZERO, "total": ZERO} for pk in ids}
    if not ids:
        return out
    rows = (
        dm.TimesheetEntry.objects.filter(project_id__in=ids)
        .order_by().values("project_id")
        .annotate(tasks=Sum("hours", filter=Q(task__isnull=False)), activities=Sum("hours", filter=Q(task__isnull=True)))
    )
    for row in rows:
        tasks, activities = row["tasks"] or ZERO, row["activities"] or ZERO
        out[row["project_id"]] = {"tasks": tasks, "activities": activities, "total": tasks + activities}
    return out


def project_logged_hours(project) -> dict[str, Decimal]:
    return logged_hours([project.pk])[project.pk]
