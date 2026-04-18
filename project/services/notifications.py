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
    if not recipient or not recipient.email:
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


def notify_task_assignment(*, task, recipient, assigned_by=None):
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