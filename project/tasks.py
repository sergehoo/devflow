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
    try:
        message_html = render_to_string("emails/task_assigned.html", context)
    except Exception:
        message_html = None

    send_mail(
        subject=subject,
        message=message,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[recipient.email],
        html_message=message_html,
        fail_silently=True,
    )


# =========================================================================
# Tâche Celery : envoi async de l'email d'invitation workspace (Phase 0)
# =========================================================================
@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def send_invitation_email_task(self, invitation_id, accept_url):
    """
    Envoie l'email d'invitation à un workspace en arrière-plan.

    Le caller a déjà construit `accept_url` côté requête HTTP (pour avoir le
    bon host via request.build_absolute_uri). On ne le recalcule pas ici.
    """
    try:
        invitation = (
            dm.WorkspaceInvitation.objects
            .select_related("workspace", "team", "invited_by")
            .get(pk=invitation_id)
        )
    except dm.WorkspaceInvitation.DoesNotExist:
        logger.warning("send_invitation_email_task: invitation %s missing", invitation_id)
        return {"ok": False, "reason": "invitation not found"}

    if not invitation.email:
        return {"ok": False, "reason": "no recipient email"}

    subject = f"[DevFlow] Vous êtes invité·e à rejoindre {invitation.workspace.name}"
    context = {
        "invitation": invitation,
        "workspace": invitation.workspace,
        "team": invitation.team,
        "invited_by": invitation.invited_by,
        "role_label": invitation.get_role_display(),
        "accept_url": accept_url,
        "expires_at": invitation.expires_at,
    }

    try:
        message_txt = render_to_string("emails/workspace_invitation.txt", context)
    except Exception:
        message_txt = (
            f"Bonjour,\n\n"
            f"{invitation.invited_by or 'Un collaborateur'} vous invite à rejoindre "
            f"le workspace {invitation.workspace.name} sur DevFlow en tant que "
            f"{invitation.get_role_display()}.\n\n"
            f"Cliquez ici pour accepter : {accept_url}\n\n"
            f"L'invitation expire le {invitation.expires_at:%d/%m/%Y}.\n"
        )

    try:
        message_html = render_to_string("emails/workspace_invitation.html", context)
    except Exception:
        message_html = None

    try:
        send_mail(
            subject=subject,
            message=message_txt,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[invitation.email],
            html_message=message_html,
            fail_silently=False,
        )
        return {"ok": True, "invitation_id": invitation_id}
    except Exception as exc:
        logger.exception("Invitation email failed for invitation %s", invitation_id)
        try:
            self.retry(exc=exc)
        except Exception:
            pass
        return {"ok": False, "reason": str(exc)}


# =========================================================================
# Tâche Celery : email PM tâche en retard (Phase 0)
# =========================================================================
@shared_task
def send_pm_task_overdue_email_task(task_id, pm_id, extend_url, expire_url, days_overdue):
    """
    Envoie l'email de notification au chef de projet pour une tâche en
    dépassement. Les URLs sont passées par le caller (qui connaît le request
    ou le SITE_URL fallback).
    """
    User = get_user_model()

    try:
        task = dm.Task.objects.select_related("project").get(pk=task_id)
    except dm.Task.DoesNotExist:
        return {"ok": False, "reason": "task not found"}

    pm = User.objects.filter(pk=pm_id).first()
    if not pm or not pm.email:
        return {"ok": False, "reason": "no PM email"}

    subject = f"[Dev'Flow] Tâche en retard · {task.title}"
    ctx = {
        "task": task,
        "project": task.project,
        "pm": pm,
        "days_overdue": days_overdue,
        "extend_url": extend_url,
        "expire_url": expire_url,
    }
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
    return {"ok": True, "task_id": task_id}

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


# =========================================================================
# Phase 3 — PR16 : Budget V2 (Celery beat)
# =========================================================================
@shared_task(bind=True, max_retries=2, default_retry_delay=180)
def scan_budget_overruns(self):
    """
    Tâche périodique : parcourt tous les workspaces actifs et émet des
    notifications + AInsight pour chaque projet en alerte budget.

    Anti-spam : on ne re-notifie pas un projet déjà notifié dans les
    dernières 24h (via metadata.last_scan_at sur la Notification).

    Beat schedule : 1×/jour à 6h Africa/Abidjan (voir CELERY_BEAT_SCHEDULE).
    """
    from datetime import timedelta
    from django.utils import timezone

    from project.services.budget_snapshots import BudgetAlertService

    stats = {"workspaces": 0, "alerts": 0, "notifications": 0, "insights": 0,
             "skipped_cooldown": 0, "errors": 0}

    severity_to_insight = {
        "info":     dm.AInsight.Severity.MEDIUM,
        "warning":  dm.AInsight.Severity.HIGH,
        "critical": dm.AInsight.Severity.CRITICAL,
    }

    now = timezone.now()
    cooldown_cutoff = now - timedelta(hours=24)

    try:
        workspaces = dm.Workspace.objects.filter(is_archived=False)
        for workspace in workspaces:
            stats["workspaces"] += 1
            try:
                alerts = BudgetAlertService.for_workspace(workspace, only_active=True)
            except Exception as exc:
                stats["errors"] += 1
                logger.warning("scan_budget_overruns workspace %s: %s",
                               workspace.pk, exc)
                continue

            for alert in alerts:
                stats["alerts"] += 1
                project = dm.Project.objects.filter(pk=alert.project_id).first()
                if project is None:
                    continue

                # Recipient : PM > owner
                pm = project.product_manager or project.owner
                if pm is None:
                    continue

                # Anti-spam : déjà notifié dans les 24h ?
                already_notified = dm.Notification.objects.filter(
                    recipient=pm,
                    workspace=workspace,
                    notification_type=dm.Notification.NotificationType.RISK,
                    metadata__project_id=project.pk,
                    metadata__alert_kind="budget_overrun",
                    created_at__gte=cooldown_cutoff,
                ).exists()
                if already_notified:
                    stats["skipped_cooldown"] += 1
                    continue

                # 1) Notification in-app
                try:
                    dm.Notification.objects.create(
                        recipient=pm,
                        workspace=workspace,
                        notification_type=dm.Notification.NotificationType.RISK,
                        title=f"Budget en alerte — {project.name}",
                        body=(
                            f"Consommation : {alert.consumption_percent}% "
                            f"(seuil {alert.alert_threshold_percent}%). "
                            f"Niveau : {alert.severity}."
                        ),
                        url=f"/projects/{project.pk}/",
                        metadata={
                            "alert_kind": "budget_overrun",
                            "project_id": project.pk,
                            "severity": alert.severity,
                            "consumption_percent": alert.consumption_percent,
                            "threshold_percent": alert.alert_threshold_percent,
                            "approved_budget": alert.approved_budget,
                            "forecast_final_cost": alert.forecast_final_cost,
                            "currency": alert.currency,
                            "scanned_at": now.isoformat(),
                        },
                    )
                    stats["notifications"] += 1
                except Exception as exc:
                    stats["errors"] += 1
                    logger.warning("Notification creation failed: %s", exc)

                # 2) AInsight type RISK
                try:
                    dm.AInsight.objects.create(
                        workspace=workspace,
                        project=project,
                        insight_type=dm.AInsight.InsightType.RISK,
                        severity=severity_to_insight.get(
                            alert.severity, dm.AInsight.Severity.MEDIUM,
                        ),
                        title=f"Dépassement budgétaire détecté · {alert.consumption_percent}%",
                        description=(
                            f"Projet {project.name} : consommation "
                            f"{alert.consumption_percent}% du budget approuvé "
                            f"({alert.approved_budget} {alert.currency}). "
                            f"Forecast final : {alert.forecast_final_cost} "
                            f"{alert.currency}. Seuil d'alerte : "
                            f"{alert.alert_threshold_percent}%."
                        ),
                        recommendation=(
                            "Réviser la baseline, replanifier les tâches "
                            "restantes ou demander une rallonge budgétaire."
                        ),
                        score=min(alert.consumption_percent, 100),
                    )
                    stats["insights"] += 1
                except Exception as exc:
                    stats["errors"] += 1
                    logger.warning("AInsight creation failed: %s", exc)

        return {"ok": True, **stats}
    except Exception as exc:
        logger.exception("scan_budget_overruns failed globally: %s", exc)
        try:
            self.retry(exc=exc)
        except Exception:
            pass
        return {"ok": False, "reason": str(exc), **stats}


# =========================================================================
# Phase 5 — PR21 : Notifications intelligentes
# =========================================================================
# =========================================================================
# PR24 — Purge SecurityAuditLog (rétention 90j par défaut)
# =========================================================================
@shared_task(bind=True, max_retries=1)
def purge_old_security_logs(self, days_to_keep: int = 90):
    """
    Tâche Celery beat : supprime les SecurityAuditLog plus vieux que
    `days_to_keep` jours. Beat : tous les dimanches à 3h Africa/Abidjan.
    """
    from datetime import timedelta
    from django.utils import timezone as _tz

    cutoff = _tz.now() - timedelta(days=days_to_keep)
    try:
        deleted, _ = dm.SecurityAuditLog.objects.filter(
            created_at__lt=cutoff,
        ).delete()
        return {"ok": True, "deleted": deleted, "cutoff": cutoff.isoformat()}
    except Exception as exc:
        logger.exception("purge_old_security_logs failed: %s", exc)
        return {"ok": False, "reason": str(exc)}


@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def generate_project_weekly_reports(self):
    """
    Tâche Celery beat (lundi 6h Africa/Abidjan) : génère un rapport IA
    hebdomadaire pour chaque projet actif et notifie le PM.

    Idempotent grâce à la UniqueConstraint
    (project, period, period_start) : si le rapport existe déjà pour la
    semaine N-1, on skip.
    """
    from project.services.ai.services.project_report import (
        ProjectAIReportService,
    )

    stats = {"projects": 0, "generated": 0, "skipped": 0, "errors": 0}
    period_start, period_end = ProjectAIReportService._default_period()

    try:
        projects = dm.Project.objects.filter(
            is_archived=False,
        ).exclude(status__in=["DONE", "CANCELLED"]).select_related("workspace")

        for project in projects:
            stats["projects"] += 1

            # Skip si rapport déjà prêt
            already = dm.ProjectAIReport.objects.filter(
                project=project, period="WEEKLY",
                period_start=period_start,
                status=dm.ProjectAIReport.ReportStatus.READY,
            ).exists()
            if already:
                stats["skipped"] += 1
                continue

            try:
                result = ProjectAIReportService.generate(
                    project,
                    period="WEEKLY",
                    period_start=period_start,
                    period_end=period_end,
                    use_ai=True,
                )
                stats["generated"] += 1

                # Notif au PM (ou owner)
                pm = project.product_manager or project.owner
                if pm is not None and result.report_id:
                    try:
                        dm.Notification.objects.create(
                            recipient=pm,
                            workspace=project.workspace,
                            notification_type=(
                                dm.Notification.NotificationType.AI
                                if hasattr(dm.Notification.NotificationType, "AI")
                                else dm.Notification.NotificationType.RISK
                            ),
                            title=f"📊 Rapport hebdomadaire prêt — {project.name}",
                            body=result.summary or "Votre rapport IA est disponible.",
                            url=f"/projects/{project.pk}/ai-reports/{result.report_id}/",
                            metadata={
                                "kind": "ai_weekly_report",
                                "project_id": project.pk,
                                "report_id": result.report_id,
                                "period_start": period_start.isoformat(),
                                "period_end": period_end.isoformat(),
                            },
                        )
                    except Exception as exc:
                        logger.warning(
                            "Notif rapport hebdo failed for project %s: %s",
                            project.pk, exc,
                        )
            except Exception as exc:
                stats["errors"] += 1
                logger.warning(
                    "Rapport hebdo failed for project %s: %s", project.pk, exc,
                )

        return {"ok": True, "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(), **stats}
    except Exception as exc:
        logger.exception("generate_project_weekly_reports failed: %s", exc)
        try:
            self.retry(exc=exc)
        except Exception:
            pass
        return {"ok": False, "reason": str(exc), **stats}


@shared_task(bind=True, max_retries=2, default_retry_delay=180)
def send_daily_notification_digest(self):
    """
    Tâche Celery beat (8h Africa/Abidjan) : parcourt les utilisateurs
    ayant notify_frequency=DAILY (ou non configuré) + channel_digest=True
    + au moins une notification non lue sur les dernières 24h, et leur
    envoie un email digest.

    Anti-doublon : si un NotificationDigest DAILY existe déjà sur la même
    période, on skip l'utilisateur.
    """
    from datetime import timedelta
    from django.contrib.auth import get_user_model
    from django.utils import timezone as _tz

    from project.services.smart_notifications import (
        NotificationDigestBuilder,
        NotificationPreferenceService,
        send_digest_email_sync,
    )

    User = get_user_model()
    stats = {"scanned": 0, "sent": 0, "skipped": 0, "errors": 0}

    now = _tz.now()
    period_end = now
    period_start = now - timedelta(hours=24)

    try:
        # On parcourt les users actifs avec au moins une notif non lue récente
        recent_users = (
            User.objects.filter(
                is_active=True,
                devflow_notifications__created_at__gte=period_start,
                devflow_notifications__is_read=False,
            )
            .distinct()
        )

        for user in recent_users:
            stats["scanned"] += 1
            try:
                prefs = NotificationPreferenceService.get_or_create(user)

                if prefs.notify_frequency == "DISABLED":
                    stats["skipped"] += 1
                    continue
                if not prefs.channel_digest:
                    stats["skipped"] += 1
                    continue
                # Seulement DAILY (HOURLY a un autre beat, IMMEDIATE n'a pas
                # de digest)
                if prefs.notify_frequency not in ("DAILY", "IMMEDIATE"):
                    stats["skipped"] += 1
                    continue

                # Anti-doublon : déjà envoyé pour cette journée ?
                already = dm.NotificationDigest.objects.filter(
                    user=user, frequency="DAILY",
                    period_end__gte=now - timedelta(hours=23),
                ).exists()
                if already:
                    stats["skipped"] += 1
                    continue

                payload = NotificationDigestBuilder.build_for(
                    user, period_start=period_start, period_end=period_end,
                    frequency="DAILY",
                )
                if payload.get("total", 0) == 0:
                    stats["skipped"] += 1
                    continue

                digest = NotificationDigestBuilder.persist(
                    user, payload,
                    period_start=period_start, period_end=period_end,
                    frequency="DAILY",
                )
                sent = send_digest_email_sync(user, digest)
                if sent:
                    stats["sent"] += 1
                else:
                    stats["skipped"] += 1
            except Exception as exc:
                stats["errors"] += 1
                logger.warning("Digest failed for user %s: %s", user.pk, exc)

        return {"ok": True, **stats}
    except Exception as exc:
        logger.exception("send_daily_notification_digest failed: %s", exc)
        try:
            self.retry(exc=exc)
        except Exception:
            pass
        return {"ok": False, "reason": str(exc), **stats}


@shared_task(bind=True, max_retries=1)
def recompute_project_eac_sweep(self):
    """
    Tâche périodique : recalcule Project.computed_eac et
    Project.computed_cost_variance pour tous les projets actifs.

    Beat schedule : 1×/jour à 5h Africa/Abidjan (avant scan_budget_overruns
    pour que les alertes utilisent des EAC frais).
    """
    from project.services.budget_snapshots import ProjectEACService

    total = {"recomputed": 0, "errors": 0, "workspaces": 0}
    try:
        workspaces = dm.Workspace.objects.filter(is_archived=False)
        for workspace in workspaces:
            total["workspaces"] += 1
            try:
                stats = ProjectEACService.recompute_workspace(
                    workspace, only_active=True,
                )
                total["recomputed"] += stats.get("recomputed", 0)
                total["errors"] += stats.get("errors", 0)
            except Exception as exc:
                total["errors"] += 1
                logger.warning("recompute_project_eac_sweep workspace %s: %s",
                               workspace.pk, exc)
        return {"ok": True, **total}
    except Exception as exc:
        logger.exception("recompute_project_eac_sweep failed: %s", exc)
        try:
            self.retry(exc=exc)
        except Exception:
            pass
        return {"ok": False, "reason": str(exc), **total}


# =============================================================================
# Réunions — génération d'occurrences cycliques (PR-MEET-2)
# =============================================================================
@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def generate_meeting_occurrences_sweep(self, horizon_days: int = 60):
    """
    Pour chaque MeetingSeries active, génère les occurrences futures
    sur un horizon de ``horizon_days`` (60 par défaut). Idempotent : ne
    re-crée pas les occurrences déjà présentes.

    Planifié quotidiennement via Celery beat (cf. settings).
    """
    from project import models as dm
    from project.services.meeting import MeetingService

    total = {"series_processed": 0, "occurrences_created": 0}
    try:
        series_qs = dm.MeetingSeries.objects.filter(
            is_active=True, is_archived=False,
        ).select_related("workspace", "organizer", "created_by")
        for series in series_qs:
            try:
                created = MeetingService.generate_occurrences(
                    series, horizon_days=horizon_days,
                )
                total["series_processed"] += 1
                total["occurrences_created"] += len(created)
            except Exception as exc:
                logger.warning(
                    "generate_meeting_occurrences: series %s failed: %s",
                    series.pk, exc,
                )
        return {"ok": True, **total}
    except Exception as exc:
        logger.exception("generate_meeting_occurrences_sweep failed: %s", exc)
        try:
            self.retry(exc=exc)
        except Exception:
            pass
        return {"ok": False, "reason": str(exc), **total}


# =============================================================================
# Enregistrement audio + transcription IA (PR-REC-2) — queue 'recordings'
# =============================================================================
@shared_task(
    bind=True, max_retries=2, default_retry_delay=300,
    queue="recordings",
)
def process_recording_task(self, recording_id: int):
    """Pipeline auto post-upload : transcribe → diarize → samples."""
    from project.services.recording.pipeline import process_recording
    try:
        process_recording(recording_id)
        return {"ok": True, "recording_id": recording_id}
    except Exception as exc:
        logger.exception("process_recording_task failed: %s", exc)
        try:
            self.retry(exc=exc)
        except Exception:
            pass
        return {"ok": False, "reason": str(exc)}


@shared_task(
    bind=True, max_retries=2, default_retry_delay=180,
    queue="recordings",
)
def finalize_recording_task(self, recording_id: int):
    """Pipeline post-mapping : final transcript + summary + extractions."""
    from project.services.recording.pipeline import finalize_recording
    try:
        finalize_recording(recording_id)
        return {"ok": True, "recording_id": recording_id}
    except Exception as exc:
        logger.exception("finalize_recording_task failed: %s", exc)
        try:
            self.retry(exc=exc)
        except Exception:
            pass
        return {"ok": False, "reason": str(exc)}


@shared_task(bind=True, max_retries=2, default_retry_delay=120)
def send_meeting_minutes_email_async(self, meeting_id: int,
                                     include_external: bool = True):
    """Tâche async pour envoyer le compte-rendu en background."""
    from project import models as dm
    from project.services.meeting import MeetingService

    try:
        meeting = dm.ProjectMeeting.objects.get(pk=meeting_id)
        sent = MeetingService.send_minutes_email(
            meeting, include_external=include_external,
        )
        return {"ok": True, "meeting_id": meeting_id, "recipients": sent}
    except dm.ProjectMeeting.DoesNotExist:
        return {"ok": False, "reason": "meeting not found"}
    except Exception as exc:
        logger.exception("send_meeting_minutes_email failed: %s", exc)
        try:
            self.retry(exc=exc)
        except Exception:
            pass
        return {"ok": False, "reason": str(exc)}
