from decimal import Decimal

from django.conf import settings
from django.db.models import Q
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from project.models import Workspace, UserProfile


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile(sender, instance, created, **kwargs):
    """
    Crée un UserProfile à la création d'un utilisateur.
    Le workspace cible est lu sur l'attribut transient `instance._invited_workspace`
    posé par le flow d'invitation. À défaut, on ne crée RIEN — il vaut mieux
    rater la création silencieuse d'un profil que rattacher l'utilisateur au
    mauvais workspace en multi-tenant.
    """
    if not created:
        return
    workspace = getattr(instance, "_invited_workspace", None)
    if workspace is None:
        # Mode mono-tenant historique : on retombe sur le 1er workspace
        # uniquement si un seul existe en base. Évite la dérive multi-tenant.
        ws_qs = Workspace.objects.all()[:2]
        if len(ws_qs) == 1:
            workspace = ws_qs[0]
    if workspace:
        UserProfile.objects.get_or_create(user=instance, workspace=workspace)


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
        # _assigned_by est posé par Task.assign() / les vues quick-assign.
        # À défaut on retombe sur le reporter (créateur) qui est moins faux
        # qu'un None pour les notifications.
        actor = getattr(instance, "_assigned_by", None) or instance.reporter

        notify_task_assignment(
            task=instance,
            recipient=recipient,
            assigned_by=actor,
        )

        log_activity(
            workspace=instance.workspace,
            actor=actor,
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

# =========================================================================
# TIMESHEET FINANCIAL SNAPSHOT
# =========================================================================
@receiver(post_save, sender=dm.TimesheetEntry)
def create_or_update_timesheet_snapshot(sender, instance, created, **kwargs):
    """
    Crée/met à jour le TimesheetCostSnapshot lié à une entrée de feuille
    de temps. Le coût est figé au moment de la création ou de la
    validation, en utilisant le BillingRate actif du jour de l'entrée.
    """
    if not instance.user_id or not instance.hours:
        return

    today = instance.entry_date or timezone.localdate()
    rate = (
        dm.BillingRate.objects.filter(
            user_id=instance.user_id,
            is_internal_cost=True,
            valid_from__lte=today,
        )
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=today))
        .order_by("-valid_from", "-id")
        .first()
    )

    profile = getattr(instance.user, "profile", None)
    hours_per_day = Decimal("8")
    if profile and getattr(profile, "capacity_hours_per_day", None):
        try:
            hp = Decimal(str(profile.capacity_hours_per_day))
            if hp > 0:
                hours_per_day = hp
        except Exception:
            pass

    hours = Decimal(str(instance.hours or 0))
    if rate:
        if rate.unit == dm.BillingRate.RateUnit.DAILY:
            daily_cost = rate.cost_rate_amount or Decimal("0")
        elif rate.unit == dm.BillingRate.RateUnit.HOURLY:
            daily_cost = (rate.cost_rate_amount or Decimal("0")) * hours_per_day
        else:  # MONTHLY
            daily_cost = (rate.cost_rate_amount or Decimal("0")) / Decimal("22")
    else:
        daily_cost = (
            profile.cost_per_day if profile and profile.cost_per_day else Decimal("0")
        )

    days = hours / hours_per_day if hours_per_day > 0 else Decimal("0")
    computed_cost = (days * daily_cost).quantize(Decimal("0.01"))

    dm.TimesheetCostSnapshot.objects.update_or_create(
        timesheet_entry=instance,
        defaults={
            "billing_rate": rate,
            "rate_unit": rate.unit if rate else "",
            "rate_amount": (rate.cost_rate_amount if rate else daily_cost) or Decimal("0"),
            "computed_cost": computed_cost,
            "currency": (rate.currency if rate else (profile.currency if profile else "XOF")),
        },
    )


# =========================================================================
# AUTO-DÉCLENCHEMENT IA À LA CRÉATION D'UN PROJET
# =========================================================================
@receiver(post_save, sender=dm.Project)
def trigger_ai_proposal_on_project_creation(sender, instance, created, **kwargs):
    """
    À la création d'un nouveau projet, on déclenche en arrière-plan
    une tâche Celery qui va générer une proposition IA complète
    (roadmap, milestones, sprints, backlog, tâches, dépendances,
    affectations).

    Si Celery n'est pas disponible (settings.CELERY_TASK_ALWAYS_EAGER=False
    + pas de worker), le signal échoue silencieusement et l'utilisateur
    pourra déclencher manuellement la génération via le bouton dédié.
    """
    if not created:
        return

    # Possibilité de désactiver complètement via settings ou env var
    if not getattr(settings, "AI_AUTO_TRIGGER_ON_PROJECT_CREATE", True):
        return

    try:
        from project.tasks import generate_project_ai_proposal_task

        # Owner == triggered_by par défaut
        triggered_by_id = instance.owner_id

        if getattr(settings, "AI_TRIGGER_SYNC", False):
            # Mode synchrone (utile pour les tests / dev sans broker)
            generate_project_ai_proposal_task(
                project_id=instance.pk,
                triggered_by_id=triggered_by_id,
            )
        else:
            generate_project_ai_proposal_task.delay(
                project_id=instance.pk,
                triggered_by_id=triggered_by_id,
            )
    except Exception:
        # Ne JAMAIS planter la création de projet à cause de l'IA.
        # On crée juste une proposition en état FAILED pour traçabilité.
        try:
            dm.ProjectAIProposal.objects.create(
                project=instance,
                workspace=instance.workspace,
                status=dm.ProjectAIProposal.Status.FAILED,
                triggered_by=instance.owner,
                error_message="Impossible de déclencher la tâche Celery (broker indisponible ?).",
            )
        except Exception:
            pass


# =========================================================================
# Notification automatique du chef de projet à chaque mise à jour de tâche
# =========================================================================
@receiver(pre_save, sender=dm.Task)
def cache_task_state_before_save(sender, instance, **kwargs):
    """Mémorise l'état "avant" d'une tâche pour le diff post_save."""
    instance._before_state = {
        "status": None,
        "assignee_id": None,
        "assignee_label": None,
        "progress_percent": None,
    }
    if not instance.pk:
        return
    try:
        previous = (
            dm.Task.objects.only(
                "status", "assignee_id", "progress_percent"
            ).get(pk=instance.pk)
        )
    except dm.Task.DoesNotExist:
        return

    instance._before_state["status"] = previous.status
    instance._before_state["assignee_id"] = previous.assignee_id
    instance._before_state["progress_percent"] = previous.progress_percent
    if previous.assignee_id:
        try:
            instance._before_state["assignee_label"] = str(
                dm.Task._meta.get_field("assignee").remote_field.model.objects.get(
                    pk=previous.assignee_id
                )
            )
        except Exception:
            pass


@receiver(post_save, sender=dm.Task)
def notify_pm_on_task_change(sender, instance, created, **kwargs):
    """
    Notifie le chef de projet (PM ou owner) à chaque mise à jour utile :
    changement de statut, d'assignee ou progression significative.

    Si la tâche fait suite à un rappel envoyé récemment, on marque ce
    rappel comme "ayant déclenché" un changement (métrique de réactivité).
    """
    before = getattr(instance, "_before_state", {}) or {}

    if not created:
        # 1. Notification PM
        try:
            from project.services.task_reminder import TaskUpdateNotifier

            TaskUpdateNotifier.notify_pm(instance, before, actor=None)
        except Exception:
            pass

        # 2. Si la tâche a changé d'état, on marque les rappels récents comme
        #    "ayant déclenché" un changement (mesure de réactivité).
        status_changed = before.get("status") and before.get("status") != instance.status
        progress_changed = (
            before.get("progress_percent") is not None
            and before.get("progress_percent") != instance.progress_percent
        )
        if status_changed or progress_changed:
            try:
                from datetime import timedelta

                cutoff = timezone.now() - timedelta(days=2)
                dm.TaskReminder.objects.filter(
                    task=instance,
                    sent_at__gte=cutoff,
                    triggered_status_change=False,
                ).update(
                    triggered_status_change=True,
                    is_acknowledged=True,
                    acknowledged_at=timezone.now(),
                )
            except Exception:
                pass


# =========================================================================
# Auto-refresh budget estimatif quand une tâche change (TJM intégré)
# =========================================================================
@receiver(post_save, sender=dm.Task)
def refresh_project_budget_on_task_change(sender, instance, created, **kwargs):
    """
    Le budget estimatif d'un projet dépend du TJM × heures estimées des
    tâches de ses membres. Dès qu'une tâche est créée, modifiée (estimate,
    assignee, status), on déclenche un rafraîchissement asynchrone du
    budget pour que le cockpit financier reste cohérent sans clic manuel.

    On utilise un drapeau `_skip_budget_refresh` pour éviter les boucles
    et on délègue à Celery quand disponible (sinon best-effort sync).
    """
    if not instance.project_id:
        return
    if getattr(instance, "_skip_budget_refresh", False):
        return

    if not getattr(settings, "AUTO_REFRESH_BUDGET_ON_TASK_CHANGE", True):
        return

    try:
        from project.tasks import refresh_project_budget_task

        if getattr(settings, "AI_TRIGGER_SYNC", False):
            refresh_project_budget_task(instance.project_id)
        else:
            refresh_project_budget_task.delay(instance.project_id)
    except Exception:
        # Ne JAMAIS planter le save d'une tâche à cause du budget.
        pass
