"""
Service "Mes actions du jour" — agrégateur centralisé.

Une seule source de vérité pour la vue HTML ``/my-day/`` et l'endpoint
DRF ``GET /api/v1/me/today/``. Retourne un dict structuré, prêt à être
sérialisé ou injecté dans un template.

Phase 1 — PR7.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from django.db.models import Q
from django.utils import timezone

from project import models as dm
from project.utils.workspaces import get_user_workspace_ids


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
ACTIVE_TASK_STATUSES = {
    dm.Task.Status.TODO,
    dm.Task.Status.IN_PROGRESS,
    dm.Task.Status.REVIEW,
    dm.Task.Status.BLOCKED,
}


@dataclass
class MyDayPayload:
    today: date
    stats: dict[str, int]
    tasks_today: list[dict]
    tasks_overdue: list[dict]
    tasks_in_progress: list[dict]
    meeting_action_items: list[dict]
    ai_insights: list[dict]
    unread_notifications: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _task_to_dict(task: dm.Task) -> dict:
    # URLs préformatées côté Python pour éviter le chaînage |add:|stringformat
    # dans les templates qui tombait silencieusement en "" (str + int illégal).
    return {
        "id": task.pk,
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "project_id": task.project_id,
        "project_name": task.project.name if task.project_id else "",
        "assignee_id": task.assignee_id,
        "is_flagged": bool(task.is_flagged),
        # Endpoints DRF quick-actions (Phase 1 PR7)
        "toggle_complete_url": f"/api/v1/tasks/{task.pk}/toggle-complete/",
        "snooze_url": f"/api/v1/tasks/{task.pk}/snooze/",
        "update_status_url": f"/api/v1/tasks/{task.pk}/update-status/",
        "quick_assign_url": f"/api/v1/tasks/{task.pk}/quick-assign/",
        # URL HTML détail tâche
        "detail_url": f"/tasks/{task.pk}/",
    }


def _notification_to_dict(notif: dm.Notification) -> dict:
    return {
        "id": notif.pk,
        "title": notif.title,
        "body": notif.body,
        "url": notif.url,
        "notification_type": notif.notification_type,
        "created_at": notif.created_at.isoformat(),
    }


def _meeting_action_to_dict(item: dm.MeetingActionItem) -> dict:
    meeting = item.meeting
    return {
        "id": item.pk,
        "title": item.title,
        "priority": item.priority,
        "status": item.status,
        "due_date": item.due_date.isoformat() if item.due_date else None,
        "meeting_id": meeting.pk,
        "meeting_title": meeting.title,
        "project_id": meeting.project_id,
        "converted_task_id": item.converted_task_id,
    }


def _insight_to_dict(insight: dm.AInsight) -> dict:
    return {
        "id": insight.pk,
        "title": insight.title,
        "severity": insight.severity,
        "score": insight.score,
        "insight_type": insight.insight_type,
        "project_id": insight.project_id,
        "project_name": insight.project.name if insight.project_id else "",
        "recommendation": (insight.recommendation or "")[:300],
    }


# ---------------------------------------------------------------------------
# Service public
# ---------------------------------------------------------------------------
class MyDayService:
    """
    Agrégat unifié pour la page "Mes actions du jour" et son équivalent
    REST. Tout est scopé aux workspaces de l'utilisateur via
    ``get_user_workspace_ids`` (SECURITY Phase 0).
    """

    LIMIT_TASKS = 20
    LIMIT_NOTIFS = 10
    LIMIT_INSIGHTS = 5
    LIMIT_MEETINGS = 8

    @classmethod
    def build(cls, user) -> MyDayPayload:
        if not user or not user.is_authenticated:
            return MyDayPayload(
                today=timezone.localdate(),
                stats={"due_today": 0, "overdue": 0, "in_progress": 0,
                       "unread_notifs": 0},
                tasks_today=[],
                tasks_overdue=[],
                tasks_in_progress=[],
                meeting_action_items=[],
                ai_insights=[],
                unread_notifications=[],
            )

        today = timezone.localdate()
        now = timezone.now()
        workspace_ids = get_user_workspace_ids(user)

        # Base : toutes les tâches du user accessibles, non archivées,
        # non terminées, non annulées. snoozed_until masque temporairement.
        base_tasks = (
            dm.Task.objects
            .filter(
                workspace_id__in=workspace_ids,
                assignee=user,
                is_archived=False,
            )
            .exclude(status__in=[
                dm.Task.Status.DONE,
                dm.Task.Status.CANCELLED,
            ])
            .filter(Q(snoozed_until__isnull=True) | Q(snoozed_until__lte=now))
            .select_related("project")
        )

        tasks_today_qs = base_tasks.filter(due_date=today).order_by(
            "-priority", "title")[:cls.LIMIT_TASKS]
        tasks_overdue_qs = base_tasks.filter(due_date__lt=today).order_by(
            "due_date", "-priority")[:cls.LIMIT_TASKS]
        tasks_in_progress_qs = base_tasks.filter(
            status=dm.Task.Status.IN_PROGRESS
        ).order_by("-priority", "title")[:cls.LIMIT_TASKS]

        # Notifications non lues, panel limité.
        unread_qs = (
            dm.Notification.objects
            .filter(recipient=user, is_read=False,
                    workspace_id__in=workspace_ids)
            .order_by("-created_at")[:cls.LIMIT_NOTIFS]
        )

        # Action items de réunion encore à traiter, dont je suis owner OU
        # qui sont sans owner mais dans mes workspaces.
        meeting_items_qs = (
            dm.MeetingActionItem.objects
            .filter(
                meeting__workspace_id__in=workspace_ids,
            )
            .filter(
                Q(owner=user) | Q(owner__isnull=True),
            )
            .exclude(status__in=[
                dm.MeetingActionItem.Status.DONE,
                dm.MeetingActionItem.Status.CANCELLED,
            ])
            .select_related("meeting", "meeting__project")
            .order_by("-meeting__scheduled_at")[:cls.LIMIT_MEETINGS]
        )

        # Insights IA pertinents : non dismissés, non lus, sur mes
        # workspaces, triés par score décroissant.
        insights_qs = (
            dm.AInsight.objects
            .filter(
                workspace_id__in=workspace_ids,
                is_dismissed=False,
                is_read=False,
                severity__in=[
                    dm.AInsight.Severity.CRITICAL,
                    dm.AInsight.Severity.HIGH,
                    dm.AInsight.Severity.MEDIUM,
                ],
            )
            .select_related("project")
            .order_by("-score", "-detected_at")[:cls.LIMIT_INSIGHTS]
        )

        # Stats globales (un seul aggregate). Note : on recompte sans le
        # slice [:LIMIT] sur la base totale pour les chiffres exacts.
        from django.db.models import Count
        agg = base_tasks.aggregate(
            due_today=Count("id", filter=Q(due_date=today)),
            overdue=Count("id", filter=Q(due_date__lt=today)),
            in_progress=Count("id",
                              filter=Q(status=dm.Task.Status.IN_PROGRESS)),
        )

        unread_notifs_count = (
            dm.Notification.objects
            .filter(recipient=user, is_read=False,
                    workspace_id__in=workspace_ids)
            .count()
        )

        return MyDayPayload(
            today=today,
            stats={
                "due_today": agg["due_today"] or 0,
                "overdue": agg["overdue"] or 0,
                "in_progress": agg["in_progress"] or 0,
                "unread_notifs": unread_notifs_count,
            },
            tasks_today=[_task_to_dict(t) for t in tasks_today_qs],
            tasks_overdue=[_task_to_dict(t) for t in tasks_overdue_qs],
            tasks_in_progress=[_task_to_dict(t) for t in tasks_in_progress_qs],
            meeting_action_items=[
                _meeting_action_to_dict(item) for item in meeting_items_qs
            ],
            ai_insights=[_insight_to_dict(i) for i in insights_qs],
            unread_notifications=[
                _notification_to_dict(n) for n in unread_qs
            ],
        )
