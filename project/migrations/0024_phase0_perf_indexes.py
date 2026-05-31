"""
Phase 0 — PR5 : indexes de performance.

Migration ADDITIVE uniquement (zéro RemoveField, zéro AlterField). Cinq
``Index`` composites posés sur les modèles les plus chauds :

* ``Task(workspace, status)``           — filtre principal de TaskListView
* ``Task.due_date``                      — overdue scan + tri par échéance
* ``Project(workspace, status, priority)`` — ProjectListView.stats + tri
* ``Notification(recipient, is_read, -created_at)`` — panel notifs unread
* ``TimesheetEntry(user, entry_date)``  — fiches de temps user

NOTE PROD POSTGRES (très gros volumes) :
    L'``AddIndex`` Django se traduit par ``CREATE INDEX`` standard qui prend
    un lock ACCESS EXCLUSIVE le temps de la création. Sur des tables Task /
    TimesheetEntry de plusieurs millions de lignes, cela peut bloquer les
    écritures plusieurs minutes.

    Procédure recommandée en prod sur très grosses tables :

        # 1) Pose les indexes sans lock — à exécuter A LA MAIN :
        CREATE INDEX CONCURRENTLY IF NOT EXISTS task_ws_status_idx
            ON project_task (workspace_id, status);
        CREATE INDEX CONCURRENTLY IF NOT EXISTS task_due_date_idx
            ON project_task (due_date);
        CREATE INDEX CONCURRENTLY IF NOT EXISTS proj_ws_status_prio_idx
            ON project_project (workspace_id, status, priority);
        CREATE INDEX CONCURRENTLY IF NOT EXISTS notif_unread_idx
            ON project_notification (recipient_id, is_read, created_at DESC);
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ts_user_date_idx
            ON project_timesheetentry (user_id, entry_date);

        # 2) Marque la migration appliquée sans la rejouer :
        python manage.py migrate project 0024 --fake

    Pour les déploiements normaux (volumes modérés, < quelques 100k lignes
    par table), laisser Django poser les indexes via ``migrate`` est suffisant.

ROLLBACK : la migration est entièrement réversible — ``migrate project 0023``
supprime les 5 indexes sans toucher aux données.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        # Cible le dernier merge connu pour éviter les conflits de tête.
        ("project", "0023_merge_0022_merge_20260429_1915_0022_project_teams_m2m"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="task",
            index=models.Index(
                fields=["workspace", "status"],
                name="task_ws_status_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="task",
            index=models.Index(
                fields=["due_date"],
                name="task_due_date_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="project",
            index=models.Index(
                fields=["workspace", "status", "priority"],
                name="proj_ws_status_prio_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(
                fields=["recipient", "is_read", "-created_at"],
                name="notif_unread_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="timesheetentry",
            index=models.Index(
                fields=["user", "entry_date"],
                name="ts_user_date_idx",
            ),
        ),
    ]
