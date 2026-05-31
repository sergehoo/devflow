from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.generic import DetailView

from project import models as dm


def create_in_app_notification(
    *,
    recipient,
    workspace,
    notification_type,
    title,
    body="",
    url="",
    metadata=None,
):
    return dm.Notification.objects.create(
        recipient=recipient,
        workspace=workspace,
        notification_type=notification_type,
        title=title,
        body=body or "",
        url=url or "",
        metadata=metadata or {},
    )


def send_assignment_email(*, recipient, task, assigned_by=None):
    """
    Envoi SYNCHRONE de l'email d'assignation. Conservé pour tests / mode dev
    sans broker Celery. Les appels production passent par
    `send_task_assignment_email_task.delay(...)` (cf. notify_task_assignment).
    """
    if not recipient or not recipient.email:
        return

    subject = f"[Dev'Flow] Nouvelle tâche pour vous · {task.title}"

    context = {
        "recipient": recipient,
        "task": task,
        "assigned_by": assigned_by,
        "project": task.project,
    }

    message_txt = render_to_string("emails/task_assigned.txt", context)
    try:
        message_html = render_to_string("emails/task_assigned.html", context)
    except Exception:
        message_html = None

    send_mail(
        subject=subject,
        message=message_txt,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[recipient.email],
        html_message=message_html,
        fail_silently=True,
    )


def notify_task_assignment(*, task, recipient, assigned_by=None):
    """
    Crée la notification in-app (sync, DB locale) et planifie l'envoi email
    en arrière-plan via Celery pour ne pas bloquer la requête HTTP sur SMTP.

    Compat : avec settings.CELERY_TASK_ALWAYS_EAGER=True (tests / dev sans
    broker), .delay() exécute la task de façon synchrone — comportement
    identique à l'ancien code.
    """
    if not recipient:
        return

    create_in_app_notification(
        recipient=recipient,
        workspace=task.workspace,
        notification_type=dm.Notification.NotificationType.TASK,
        title="Nouvelle tâche assignée",
        body=f"La tâche « {task.title} » vous a été assignée.",
        url=f"/tasks/{task.pk}/",
        metadata={
            "task_id": task.pk,
            "project_id": task.project_id,
            "project_name": task.project.name if task.project_id else "",
            "assigned_by_id": assigned_by.pk if assigned_by else None,
        },
    )

    # ASYNC (Phase 0): on ne bloque plus la requête HTTP sur l'envoi SMTP.
    # Import local pour éviter tout cycle (tasks.py importe models, pas les services).
    try:
        from project.tasks import send_task_assignment_email_task

        send_task_assignment_email_task.delay(
            task.pk,
            recipient.pk,
            assigned_by.pk if assigned_by else None,
        )
    except Exception:
        # Si Celery est indisponible (broker down et pas en EAGER), fallback
        # synchrone — la notification in-app a déjà été créée, l'utilisateur
        # ne reste donc pas sans signal.
        send_assignment_email(
            recipient=recipient,
            task=task,
            assigned_by=assigned_by,
        )


class ChannelDetailView(LoginRequiredMixin, DetailView):
    model = dm.DirectChannel
    template_name = "project/chat/channel_detail.html"
    context_object_name = "chat_channel"

    def get_queryset(self):
        return (
            dm.DirectChannel.objects
            .filter(members=self.request.user)
            .prefetch_related(
                "members",
                "messages__author",
                "messages__replies__author",
            )
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        channel = self.object
        ctx["messages"] = channel.messages.select_related("author").order_by("created_at")
        return ctx