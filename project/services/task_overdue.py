"""
Service : détection des tâches en dépassement d'échéance et notification
au chef de projet (PM ou owner). Le PM doit ensuite arbitrer :
  - reconduire la tâche pour une nouvelle période, ou
  - maintenir la tâche en statut EXPIRED (« expirée non traitée »).
"""

from __future__ import annotations

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from project import models as dm


def _resolve_pm(task):
    """Retourne l'utilisateur à notifier : product_manager > owner du projet."""
    if not task.project_id:
        return None
    project = task.project
    return project.product_manager or project.owner


def _build_action_url(view_name, task_pk, request=None) -> str:
    path = reverse(view_name, args=[task_pk])
    if request is not None:
        return request.build_absolute_uri(path)
    base = getattr(settings, "SITE_URL", "").rstrip("/")
    return f"{base}{path}" if base else path


def notify_pm_task_overdue(task, *, request=None, force=False) -> bool:
    """
    Envoie au PM une notification (in-app + email) avec deux liens :
    - reconduire (extend) → ouvre /tasks/<pk>/extend/
    - maintenir expirée  → POST /tasks/<pk>/mark-expired/

    Idempotence : on n'envoie pas deux fois dans la même journée pour la
    même tâche, sauf si `force=True`.
    Retourne True si la notification a été envoyée.
    """
    pm = _resolve_pm(task)
    if not pm:
        return False

    if not force and task.pm_overdue_notified_at:
        last = task.pm_overdue_notified_at
        if (timezone.now() - last).total_seconds() < 24 * 3600:
            return False

    extend_url = _build_action_url("task_extend", task.pk, request=request)
    expire_url = _build_action_url("task_mark_expired", task.pk, request=request)

    today = timezone.localdate()
    days_overdue = (today - task.due_date).days if task.due_date else 0

    # Notification in-app
    try:
        from project.services.notifications import create_in_app_notification

        create_in_app_notification(
            recipient=pm,
            workspace=task.workspace,
            notification_type=dm.Notification.NotificationType.TASK,
            title=f"Tâche en retard : {task.title}",
            body=(
                f"La tâche est en retard de {days_overdue} jour(s) "
                "sur son échéance. Reconduisez-la ou marquez-la expirée."
            ),
            url=f"/tasks/{task.pk}/",
            metadata={
                "task_id": task.pk,
                "project_id": task.project_id,
                "actions": [
                    {"label": "Reconduire", "url": extend_url},
                    {"label": "Maintenir expirée", "url": expire_url},
                ],
                "days_overdue": days_overdue,
            },
        )
    except Exception:
        pass

    # Email
    if pm.email:
        try:
            ctx = {
                "task": task,
                "project": task.project,
                "pm": pm,
                "days_overdue": days_overdue,
                "extend_url": extend_url,
                "expire_url": expire_url,
            }
            subject = f"[Dev'Flow] Tâche en retard · {task.title}"
            try:
                message_txt = render_to_string("emails/task_overdue.txt", ctx)
            except Exception:
                message_txt = (
                    f"Bonjour {pm.first_name or pm.username},\n\n"
                    f"La tâche « {task.title} » du projet {task.project} "
                    f"est en retard de {days_overdue} jour(s).\n\n"
                    f"Reconduisez : {extend_url}\n"
                    f"Maintenir expirée : {expire_url}\n"
                )
            try:
                message_html = render_to_string("emails/task_overdue.html", ctx)
            except Exception:
                message_html = None

            send_mail(
                subject=subject,
                message=message_txt,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                recipient_list=[pm.email],
                html_message=message_html,
                fail_silently=True,
            )
        except Exception:
            pass

    # Marquer la dernière notification pour éviter les doublons
    dm.Task.objects.filter(pk=task.pk).update(pm_overdue_notified_at=timezone.now())
    return True


def scan_overdue_tasks(*, workspace=None) -> dict:
    """
    Parcourt toutes les tâches dont `due_date < today` et qui ne sont pas
    déjà DONE / CANCELLED / EXPIRED, puis notifie leur PM.
    Retourne un dict de stats {scanned, notified, skipped}.
    """
    today = timezone.localdate()
    qs = dm.Task.objects.filter(
        is_archived=False,
        due_date__lt=today,
    ).exclude(status__in=[
        dm.Task.Status.DONE,
        dm.Task.Status.CANCELLED,
        dm.Task.Status.EXPIRED,
    ])
    if workspace is not None:
        qs = qs.filter(workspace=workspace)

    notified, skipped = 0, 0
    for task in qs.select_related("project", "workspace"):
        if notify_pm_task_overdue(task):
            notified += 1
        else:
            skipped += 1

    return {"scanned": qs.count(), "notified": notified, "skipped": skipped}
