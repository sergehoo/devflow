from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from project.models import Workspace, UserProfile


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        workspace = Workspace.objects.first()  # ou logique custom
        if workspace:
            UserProfile.objects.create(user=instance, workspace=workspace)

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from project import models as dm
from project.services.notifications import notify_task_assignment
from project.services.activity_logs import log_activity


@receiver(pre_save, sender=dm.Task)
def cache_previous_task_assignee(sender, instance, **kwargs):
    instance._previous_assignee_id = None
    if instance.pk:
        try:
            previous = dm.Task.objects.only("assignee_id").get(pk=instance.pk)
            instance._previous_assignee_id = previous.assignee_id
        except dm.Task.DoesNotExist:
            pass


@receiver(post_save, sender=dm.Task)
def notify_on_task_assignee_change(sender, instance, created, **kwargs):
    previous_assignee_id = getattr(instance, "_previous_assignee_id", None)
    current_assignee_id = instance.assignee_id

    should_notify = False

    if created and current_assignee_id:
        should_notify = True
    elif previous_assignee_id != current_assignee_id and current_assignee_id:
        should_notify = True

    if should_notify:
        recipient = instance.assignee

        notify_task_assignment(
            task=instance,
            recipient=recipient,
            assigned_by=instance.reporter,
        )

        log_activity(
            workspace=instance.workspace,
            actor=instance.reporter,
            project=instance.project,
            task=instance,
            activity_type=dm.ActivityLog.ActivityType.MEMBER_ASSIGNED,
            title="Utilisateur assigné à une tâche",
            description=f"{recipient} a été assigné à la tâche « {instance.title} ».",
            metadata={
                "task_id": instance.pk,
                "assignee_id": recipient.pk,
            },
        )


@receiver(post_save, sender=dm.TaskAssignment)
def notify_on_task_assignment_created(sender, instance, created, **kwargs):
    if not created or not instance.user_id:
        return

    notify_task_assignment(
        task=instance.task,
        recipient=instance.user,
        assigned_by=instance.assigned_by,
    )

    log_activity(
        workspace=instance.task.workspace,
        actor=instance.assigned_by,
        project=instance.task.project,
        task=instance.task,
        activity_type=dm.ActivityLog.ActivityType.MEMBER_ASSIGNED,
        title="Affectation complémentaire sur tâche",
        description=f"{instance.user} a été affecté à la tâche « {instance.task.title} ».",
        metadata={
            "task_id": instance.task_id,
            "user_id": instance.user_id,
            "allocation_percent": instance.allocation_percent,
        },
    )