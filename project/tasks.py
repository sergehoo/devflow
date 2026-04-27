import logging

from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.template.loader import render_to_string

from project import models as dm

logger = logging.getLogger(__name__)


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

# =========================================================================
# Tâche Celery : génération asynchrone d'une ProjectAIProposal
# =========================================================================
@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def generate_project_ai_proposal_task(self, project_id, triggered_by_id=None, use_ai=True):
    """
    Tâche async appelée par le signal post_save de Project.
    Crée une ProjectAIProposal complète (roadmap, milestones, sprints,
    backlog, tâches, dépendances, affectations).
    """
    User = get_user_model()
    from project.services.ai.services.project_structure import (
        ProjectAIStructureService,
    )

    try:
        project = dm.Project.objects.select_related("workspace", "owner").get(pk=project_id)
    except dm.Project.DoesNotExist:
        logger.warning("generate_project_ai_proposal_task: project %s missing", project_id)
        return {"ok": False, "reason": "project not found"}

    triggered_by = None
    if triggered_by_id:
        triggered_by = User.objects.filter(pk=triggered_by_id).first()

    # Idempotence : si on a déjà une proposition non-terminale récente, on ne
    # régénère pas (évite la duplication en cas de double save).
    existing = dm.ProjectAIProposal.objects.filter(
        project=project,
        status__in=[
            dm.ProjectAIProposal.Status.PENDING,
            dm.ProjectAIProposal.Status.GENERATING,
            dm.ProjectAIProposal.Status.READY,
        ],
    ).first()
    if existing and existing.items.exists():
        return {"ok": True, "skipped": True, "proposal_id": existing.pk}

    try:
        result = ProjectAIStructureService.generate_for_project(
            project=project,
            triggered_by=triggered_by,
            use_ai=use_ai,
        )
        return {
            "ok": True,
            "proposal_id": result.proposal.pk,
            "items_created": result.items_created,
            "used_provider": result.used_provider,
        }
    except Exception as exc:
        logger.exception("AI proposal generation failed for project %s", project_id)
        try:
            self.retry(exc=exc)
        except Exception:
            pass
        return {"ok": False, "reason": str(exc)}


# =========================================================================
# Celery Beat : relance automatique des tâches stagnantes (2x/jour)
# =========================================================================
@shared_task(bind=True, max_retries=2, default_retry_delay=120)
def run_task_reminder_sweep(self, dry_run: bool = False):
    """
    Lance un balayage de toutes les tâches DevFlow et envoie les rappels
    nécessaires aux assignees + digest aux chefs de projet.

    Programmée 2x/jour via CELERY_BEAT_SCHEDULE (matin & après-midi).
    """
    from project.services.task_reminder import TaskReminderService

    try:
        result = TaskReminderService.run(dry_run=dry_run)
        return {
            "ok": True,
            "scanned": result.scanned_tasks,
            "eligible": result.eligible_tasks,
            "reminders_sent": result.reminders_sent,
            "pm_notified": result.pm_notified_count,
            "skipped_cooldown": result.skipped_cooldown,
            "errors": result.errors,
            "by_reason": dict(result.by_reason),
            "dry_run": dry_run,
        }
    except Exception as exc:
        logger.exception("Task reminder sweep failed: %s", exc)
        try:
            self.retry(exc=exc)
        except Exception:
            pass
        return {"ok": False, "reason": str(exc)}


# =========================================================================
# Refresh asynchrone du budget projet quand une tâche change
# =========================================================================
@shared_task(bind=True, max_retries=1)
def refresh_project_budget_task(self, project_id):
    """
    Recalcule le budget estimatif d'un projet (TJM × heures estimées de
    ses tâches) sans bloquer le save de la tâche déclencheuse.
    """
    try:
        project = dm.Project.objects.get(pk=project_id)
    except dm.Project.DoesNotExist:
        return {"ok": False, "reason": "project not found"}

    from project.services.budget import ProjectBudgetService
    try:
        ProjectBudgetService.refresh_project_financials(
            project=project, user=None, rebuild_budget=True,
        )
        return {"ok": True, "project_id": project_id}
    except Exception as exc:
        logger.exception("Budget refresh failed for project %s", project_id)
        return {"ok": False, "reason": str(exc)}
