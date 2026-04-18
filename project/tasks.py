from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.template.loader import render_to_string

from project import models as dm


@shared_task
def send_task_assignment_email_task(task_id, recipient_id, assigned_by_id=None):
    User = get_user_model()

    try:
        task = dm.Task.objects.select_related("project").get(pk=task_id)
        recipient = User.objects.get(pk=recipient_id)
        assigned_by = User.objects.filter(pk=assigned_by_id).first() if assigned_by_id else None
    except Exception:
        return

    if not recipient.email:
        return

    subject = f"[DevFlow] Nouvelle tâche assignée : {task.title}"
    context = {
        "recipient": recipient,
        "task": task,
        "assigned_by": assigned_by,
        "project": task.project,
    }
    message = render_to_string("emails/task_assigned.txt", context)

    send_mail(
        subject=subject,
        message=message,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[recipient.email],
        fail_silently=True,
    )