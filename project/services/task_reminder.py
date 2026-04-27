"""
Service de relance automatique des tâches DevFlow.

Stratégie :
1. Cron Celery 2x/jour → `TaskReminderService.run()`
2. Détection des tâches "stagnantes" :
   - non terminées (status != DONE/CANCELLED)
   - assignée à un utilisateur
   - ET (en retard OU due bientôt avec aucun progrès récent OU bloquée)
3. Anti-spam : un rappel par tâche/destinataire dans les `TASK_REMINDER_COOLDOWN_HOURS`.
4. Pour chaque rappel envoyé :
   - email à l'assignee (template `emails/task_reminder.txt|html`)
   - notification in-app + email digest au chef de projet
   - log dans TaskReminder + ActivityLog

Configurable via Django settings :
- TASK_REMINDER_COOLDOWN_HOURS (défaut 10) → fenêtre minimum entre 2 rappels
- TASK_STALE_DAYS (défaut 2)               → "stagnante" si pas modifiée depuis N jours
- TASK_DUE_SOON_DAYS (défaut 3)            → "due bientôt" si due_date dans <= N jours
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Iterable

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives, send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from project import models as dm
from project.services.activity_logs import log_activity

logger = logging.getLogger(__name__)
User = get_user_model()


@dataclass
class ReminderRunResult:
    scanned_tasks: int = 0
    eligible_tasks: int = 0
    reminders_sent: int = 0
    pm_notified_count: int = 0
    skipped_cooldown: int = 0
    errors: int = 0
    by_reason: dict = field(default_factory=lambda: defaultdict(int))


class TaskReminderService:

    # ---------------------------------------------------------------------
    # PUBLIC
    # ---------------------------------------------------------------------
    @classmethod
    def run(cls, dry_run: bool = False) -> ReminderRunResult:
        result = ReminderRunResult()

        cooldown_hours = int(getattr(settings, "TASK_REMINDER_COOLDOWN_HOURS", 10))
        stale_days = int(getattr(settings, "TASK_STALE_DAYS", 2))
        due_soon_days = int(getattr(settings, "TASK_DUE_SOON_DAYS", 3))

        candidates = cls._candidate_tasks(stale_days=stale_days, due_soon_days=due_soon_days)
        result.scanned_tasks = candidates.count()

        cooldown = timezone.now() - timedelta(hours=cooldown_hours)

        # Regroupement par projet pour digest PM
        pm_buckets: dict[int, list[tuple[dm.Task, str, int]]] = defaultdict(list)

        for task in candidates.iterator():
            if not task.assignee_id:
                continue
            reason, days_overdue = cls._classify(task, stale_days, due_soon_days)
            if reason is None:
                continue
            result.eligible_tasks += 1

            recent = dm.TaskReminder.objects.filter(
                task=task,
                recipient_id=task.assignee_id,
                sent_at__gte=cooldown,
            ).exists()
            if recent:
                result.skipped_cooldown += 1
                continue

            try:
                if not dry_run:
                    cls._send_assignee_reminder(task, reason, days_overdue)
                result.reminders_sent += 1
                result.by_reason[reason] += 1

                pm = cls._project_manager(task.project)
                if pm:
                    pm_buckets[task.project_id].append((task, reason, days_overdue))
            except Exception as exc:
                logger.exception("Reminder failed for task %s: %s", task.pk, exc)
                result.errors += 1

        # Digest PM (1 email + 1 notification par projet)
        if not dry_run:
            for project_id, items in pm_buckets.items():
                project = dm.Project.objects.select_related("workspace", "product_manager", "owner").get(pk=project_id)
                pm = cls._project_manager(project)
                if pm:
                    cls._send_pm_digest(project, pm, items)
                    result.pm_notified_count += 1

        return result

    # ---------------------------------------------------------------------
    # Candidate tasks
    # ---------------------------------------------------------------------
    @staticmethod
    def _candidate_tasks(stale_days: int, due_soon_days: int):
        today = timezone.localdate()
        stale_cutoff = timezone.now() - timedelta(days=stale_days)
        due_soon_limit = today + timedelta(days=due_soon_days)

        terminal = [dm.Task.Status.DONE, dm.Task.Status.CANCELLED]

        from django.db.models import Q
        qs = (
            dm.Task.objects.select_related("project", "project__product_manager", "project__owner",
                                           "assignee", "workspace")
            .filter(is_archived=False, assignee__isnull=False)
            .exclude(status__in=terminal)
            .filter(
                Q(due_date__isnull=False, due_date__lte=due_soon_limit)
                | Q(updated_at__lt=stale_cutoff)
                | Q(status=dm.Task.Status.BLOCKED)
            )
        )
        return qs

    @staticmethod
    def _classify(task, stale_days: int, due_soon_days: int):
        today = timezone.localdate()
        if task.status == dm.Task.Status.BLOCKED:
            return dm.TaskReminder.Reason.BLOCKED, 0
        if task.due_date and task.due_date < today:
            return dm.TaskReminder.Reason.OVERDUE, (today - task.due_date).days
        if task.due_date and (task.due_date - today).days <= due_soon_days:
            return dm.TaskReminder.Reason.DUE_SOON, 0
        if task.updated_at and (timezone.now() - task.updated_at).days >= stale_days:
            return dm.TaskReminder.Reason.STALE, (timezone.now() - task.updated_at).days
        return None, 0

    @staticmethod
    def _project_manager(project):
        return project.product_manager or project.owner

    # ---------------------------------------------------------------------
    # Sending
    # ---------------------------------------------------------------------
    @classmethod
    def _send_assignee_reminder(cls, task, reason: str, days_overdue: int) -> None:
        recipient = task.assignee
        if not recipient or not recipient.email:
            cls._record_reminder(task, recipient, reason, days_overdue, error="no email")
            return

        subject = f"[DevFlow] Rappel — {task.title}"
        ctx = {
            "task": task,
            "project": task.project,
            "recipient": recipient,
            "reason_label": dm.TaskReminder.Reason(reason).label,
            "reason_code": reason,
            "days_overdue": days_overdue,
            "task_url": cls._task_url(task),
        }
        try:
            text_body = render_to_string("emails/task_reminder.txt", ctx)
            html_body = render_to_string("emails/task_reminder.html", ctx)
            email = EmailMultiAlternatives(
                subject=subject,
                body=text_body,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@devflow.local"),
                to=[recipient.email],
            )
            email.attach_alternative(html_body, "text/html")
            email.send(fail_silently=True)
        except Exception as exc:
            cls._record_reminder(task, recipient, reason, days_overdue, error=str(exc))
            return

        # In-app notification
        try:
            dm.Notification.objects.create(
                workspace=task.workspace,
                recipient=recipient,
                notification_type=dm.Notification.NotificationType.TASK,
                title=f"Rappel — {task.title}",
                body=cls._reason_message(reason, days_overdue),
                url=cls._task_url(task),
                metadata={"task_id": task.pk, "reason": reason, "days_overdue": days_overdue},
            )
        except Exception:
            pass

        cls._record_reminder(task, recipient, reason, days_overdue)
        log_activity(
            workspace=task.workspace,
            actor=None,
            project=task.project,
            task=task,
            activity_type=dm.ActivityLog.ActivityType.MEMBER_ASSIGNED,
            title="Rappel automatique envoyé",
            description=f"Rappel envoyé à {recipient} ({reason}).",
            metadata={"reason": reason, "days_overdue": days_overdue},
        )

    @classmethod
    def _send_pm_digest(cls, project, pm, items) -> None:
        if not pm.email:
            return
        ctx = {
            "project": project,
            "pm": pm,
            "items": [
                {
                    "task": t,
                    "reason_label": dm.TaskReminder.Reason(reason).label,
                    "days_overdue": days,
                    "task_url": cls._task_url(t),
                }
                for t, reason, days in items
            ],
            "items_count": len(items),
        }
        try:
            text_body = render_to_string("emails/task_reminder_pm_digest.txt", ctx)
            html_body = render_to_string("emails/task_reminder_pm_digest.html", ctx)
            subject = f"[DevFlow] {len(items)} tâche(s) en attente — {project.name}"
            email = EmailMultiAlternatives(
                subject=subject,
                body=text_body,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@devflow.local"),
                to=[pm.email],
            )
            email.attach_alternative(html_body, "text/html")
            email.send(fail_silently=True)
        except Exception as exc:
            logger.warning("PM digest failed for project %s: %s", project.pk, exc)

        try:
            dm.Notification.objects.create(
                workspace=project.workspace,
                recipient=pm,
                notification_type=dm.Notification.NotificationType.TASK,
                title=f"{len(items)} tâche(s) en attente sur « {project.name} »",
                body="Synthèse automatique des rappels envoyés à votre équipe.",
                metadata={"project_id": project.pk, "items_count": len(items)},
            )
        except Exception:
            pass

    # ---------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------
    @staticmethod
    def _reason_message(reason: str, days_overdue: int) -> str:
        if reason == dm.TaskReminder.Reason.OVERDUE:
            return f"Cette tâche est en retard de {days_overdue} jour(s). Merci de mettre à jour son statut."
        if reason == dm.TaskReminder.Reason.STALE:
            return f"Aucune mise à jour depuis {days_overdue} jour(s). Merci d'indiquer où en est la tâche."
        if reason == dm.TaskReminder.Reason.DUE_SOON:
            return "L'échéance approche. Merci de confirmer l'avancement."
        if reason == dm.TaskReminder.Reason.BLOCKED:
            return "Cette tâche est marquée comme bloquée. Merci de préciser le blocage."
        return "Merci de mettre à jour cette tâche."

    @staticmethod
    def _task_url(task) -> str:
        try:
            return reverse("task_detail", kwargs={"pk": task.pk})
        except Exception:
            return f"/tasks/{task.pk}/"

    @staticmethod
    def _record_reminder(task, recipient, reason, days_overdue, error: str = "") -> None:
        try:
            dm.TaskReminder.objects.create(
                task=task,
                recipient=recipient,
                reason=reason,
                channel=dm.TaskReminder.Channel.BOTH if not error else dm.TaskReminder.Channel.EMAIL,
                task_status_at_send=task.status,
                task_due_date_at_send=task.due_date,
                days_overdue=days_overdue,
                error_message=error,
            )
        except Exception as exc:
            logger.warning("Could not log TaskReminder: %s", exc)


# =========================================================================
# Notification PM en temps réel sur changement de tâche
# =========================================================================
class TaskUpdateNotifier:
    """
    Appelé depuis le signal post_save de Task.
    Envoie une notif au chef de projet à chaque mise à jour utile :
    - changement de status
    - changement d'assignee
    - changement de progress_percent significatif
    """

    SIGNIFICANT_PROGRESS_DELTA = 25  # % (pour ne pas spammer le PM)

    @classmethod
    def notify_pm(cls, task, before: dict, actor=None) -> None:
        pm = task.project.product_manager or task.project.owner
        if not pm or pm == actor:  # pas la peine d'auto-notifier le PM si c'est lui qui a édité
            return

        changes = []
        if before.get("status") != task.status:
            changes.append(
                f"statut « {before.get('status') or '—'} » → « {task.get_status_display()} »"
            )
        if before.get("assignee_id") != task.assignee_id:
            changes.append(
                f"affectation : {before.get('assignee_label') or '—'} → {task.assignee or '—'}"
            )
        if before.get("progress_percent") is not None:
            delta = (task.progress_percent or 0) - (before.get("progress_percent") or 0)
            if abs(delta) >= cls.SIGNIFICANT_PROGRESS_DELTA:
                changes.append(f"progression {before.get('progress_percent')}% → {task.progress_percent}%")

        if not changes:
            return

        message = "Mise à jour : " + ", ".join(changes)

        try:
            dm.Notification.objects.create(
                workspace=task.workspace,
                recipient=pm,
                notification_type=dm.Notification.NotificationType.TASK,
                title=f"Tâche mise à jour — {task.title}",
                body=message,
                metadata={"task_id": task.pk},
            )
        except Exception:
            pass

        if pm.email:
            ctx = {
                "task": task,
                "project": task.project,
                "pm": pm,
                "changes": changes,
                "actor": actor,
                "message": message,
            }
            try:
                send_mail(
                    subject=f"[DevFlow] Mise à jour — {task.title}",
                    message=render_to_string("emails/task_pm_update.txt", ctx),
                    from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@devflow.local"),
                    recipient_list=[pm.email],
                    fail_silently=True,
                )
            except Exception as exc:
                logger.warning("PM update email failed for task %s: %s", task.pk, exc)
