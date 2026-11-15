"""
Rattrapage du temps passé des tâches à partir des saisies de temps.

Avant cette version, les heures saisies dans la grille hebdomadaire des
timesheets ne mettaient pas à jour ``Task.spent_hours`` (seule la saisie rapide
depuis une tâche le faisait). Désormais les signaux de ``TimesheetEntry``
maintiennent ``spent_hours`` = somme des saisies ; cette migration rattrape
l'historique.

1. Une saisie portant sur une tâche est rattachée au projet de cette tâche (les
   formulaires et l'API permettaient un projet vide ou différent : ses heures et
   son coût échappaient au projet de la tâche).
2. ``spent_hours`` n'est relevé que lorsqu'il est INFÉRIEUR à la somme des saisies.
   Une valeur supérieure (saisie manuelle sur la fiche tâche) est conservée.

Aucune opération inverse nécessaire.
"""
from collections import defaultdict
from decimal import Decimal

from django.db import migrations
from django.db.models import Sum


def attach_entries_to_task_project(apps, schema_editor):
    TimesheetEntry = apps.get_model("project", "TimesheetEntry")
    moves = defaultdict(list)
    rows = TimesheetEntry.objects.filter(task__isnull=False).values_list("pk", "project_id", "task__project_id")
    for pk, project_id, task_project_id in rows.iterator():
        if task_project_id and project_id != task_project_id:
            moves[task_project_id].append(pk)
    for task_project_id, pks in moves.items():
        for start in range(0, len(pks), 500):
            TimesheetEntry.objects.filter(pk__in=pks[start:start + 500]).update(project_id=task_project_id)


def raise_spent_hours(apps, schema_editor):
    Task = apps.get_model("project", "Task")
    TimesheetEntry = apps.get_model("project", "TimesheetEntry")
    totals = (
        TimesheetEntry.objects.filter(task__isnull=False)
        .order_by().values("task_id").annotate(total=Sum("hours"))
    )
    for row in totals.iterator():
        total = row["total"] or Decimal("0")
        if total > 0:
            Task.objects.filter(pk=row["task_id"], spent_hours__lt=total).update(spent_hours=total)


class Migration(migrations.Migration):

    dependencies = [
        ("project", "0057_ticketing_public_intake"),
    ]

    operations = [
        migrations.RunPython(attach_entries_to_task_project, migrations.RunPython.noop),
        migrations.RunPython(raise_spent_hours, migrations.RunPython.noop),
    ]
