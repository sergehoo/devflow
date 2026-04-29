"""
Commande management : scanne les tâches en retard et notifie les chefs de
projet (in-app + email) pour qu'ils décident de reconduire ou marquer expirée.

Usage :
    python manage.py notify_overdue_tasks
    python manage.py notify_overdue_tasks --workspace 3
    python manage.py notify_overdue_tasks --force      # ignore le délai 24h

À planifier dans Celery beat ou via cron quotidien.
"""

from django.core.management.base import BaseCommand

from project import models as dm
from project.services.task_overdue import scan_overdue_tasks, notify_pm_task_overdue


class Command(BaseCommand):
    help = "Scanne les tâches en retard et notifie le PM."

    def add_arguments(self, parser):
        parser.add_argument(
            "--workspace", type=int, default=None,
            help="Limiter à un workspace par ID.",
        )
        parser.add_argument(
            "--force", action="store_true",
            help="Forcer la notification même si déjà envoyée dans les 24h.",
        )

    def handle(self, *args, **options):
        ws = None
        if options.get("workspace"):
            try:
                ws = dm.Workspace.objects.get(pk=options["workspace"])
            except dm.Workspace.DoesNotExist:
                self.stderr.write(self.style.ERROR(
                    f"Workspace #{options['workspace']} introuvable."
                ))
                return

        if options.get("force"):
            # Bypass : on appelle notify_pm_task_overdue avec force=True
            from django.utils import timezone
            qs = dm.Task.objects.filter(
                is_archived=False,
                due_date__lt=timezone.localdate(),
            ).exclude(status__in=[
                dm.Task.Status.DONE,
                dm.Task.Status.CANCELLED,
                dm.Task.Status.EXPIRED,
            ])
            if ws:
                qs = qs.filter(workspace=ws)
            notified = 0
            for t in qs.select_related("project", "workspace"):
                if notify_pm_task_overdue(t, force=True):
                    notified += 1
            self.stdout.write(self.style.SUCCESS(
                f"Forcé · {notified}/{qs.count()} tâche(s) notifiée(s)."
            ))
            return

        stats = scan_overdue_tasks(workspace=ws)
        self.stdout.write(self.style.SUCCESS(
            f"Scan terminé · {stats['scanned']} tâche(s) en retard, "
            f"{stats['notified']} notifiée(s), {stats['skipped']} ignorée(s) "
            f"(notif récente)."
        ))
