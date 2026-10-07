"""
Données des fiches « Membre d'équipe » et « Équipe ».

Tout est calculé dans le workspace de l'objet affiché ; les informations de
temps (timesheet) ne sont exposées qu'à l'intéressé, à sa ligne hiérarchique
et aux gestionnaires des membres (RBAC ``members.manage``).
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

from django.db.models import Count, Q
from django.utils import timezone

from project import models as dm
from project.services import timesheet_workflow as tw

CLOSED_TASK_STATUSES = [dm.Task.Status.DONE, dm.Task.Status.CANCELLED]


def _can_see_timesheet(viewer, user, workspace) -> bool:
    from project.services.password_reset import can_manage_passwords

    return user.pk in tw.visible_user_ids(viewer, workspace) or can_manage_passwords(viewer, workspace)


def _open_tasks_for(user_ids, workspace):
    assigned_ids = dm.TaskAssignment.objects.filter(
        user_id__in=user_ids, is_active=True,
    ).values("task_id")
    return (
        dm.Task.objects.filter(workspace=workspace, is_archived=False)
        .filter(Q(assignee_id__in=user_ids) | Q(pk__in=assigned_ids))
        .exclude(status__in=CLOSED_TASK_STATUSES)
        .distinct()
    )


def member_overview(membership, viewer) -> dict:
    user, workspace = membership.user, membership.workspace
    today = timezone.localdate()
    monday, _ = tw.week_bounds(today)
    profile = (
        dm.UserProfile.objects.filter(user=user, workspace=workspace)
        .select_related("manager__user").first()
    )

    open_tasks = _open_tasks_for([user.pk], workspace).select_related("project")
    status_counts = Counter(open_tasks.values_list("status", flat=True))
    labels = dict(dm.Task.Status.choices)

    can_see_time = _can_see_timesheet(viewer, user, workspace)
    return {
        "member": user,
        "profile": profile,
        "chain": profile.management_chain() if profile else [],
        "reports": (
            list(profile.direct_reports.filter(workspace=workspace).select_related("user"))
            if profile else []
        ),
        "other_memberships": (
            dm.TeamMembership.objects.filter(workspace=workspace, user=user)
            .exclude(pk=membership.pk).select_related("team")
        ),
        "projects": (
            dm.ProjectMember.objects.filter(
                user=user, project__workspace=workspace, project__is_archived=False,
            ).select_related("project").order_by("project__name")
        ),
        "task_stats": {
            "open": sum(status_counts.values()),
            "overdue": open_tasks.filter(due_date__lt=today).count(),
            "by_status": [(labels.get(s, s), n) for s, n in status_counts.most_common()],
        },
        "upcoming_tasks": list(open_tasks.order_by("due_date", "-priority")[:6]),
        "can_see_timesheet": can_see_time,
        "week": tw.week_summary(user, workspace, monday, upto=today) if can_see_time else None,
        "today": today,
    }


def team_overview(team, viewer) -> dict:
    workspace = team.workspace
    today = timezone.localdate()
    monday, _ = tw.week_bounds(today)
    memberships = list(
        team.memberships.select_related("user").order_by("-status", "user__last_name", "user__first_name")
    )
    user_ids = [m.user_id for m in memberships]
    tasks_by_user = dict(
        dm.Task.objects.filter(
            workspace=workspace, is_archived=False, assignee_id__in=user_ids,
        ).exclude(status__in=CLOSED_TASK_STATUSES)
        .values("assignee_id").annotate(n=Count("id")).values_list("assignee_id", "n")
    )

    rows, total_hours, total_expected = [], Decimal("0"), Decimal("0")
    for m in memberships:
        week = None
        if _can_see_timesheet(viewer, m.user, workspace):
            week = tw.week_summary(m.user, workspace, monday, upto=today)
            total_hours += week.total_hours
            total_expected += week.expected
        rows.append({"membership": m, "week": week, "open_tasks": tasks_by_user.get(m.user_id, 0)})

    projects = (
        dm.Project.objects.filter(Q(team=team) | Q(teams=team), workspace=workspace, is_archived=False)
        .distinct().order_by("name")
    )
    open_tasks = _open_tasks_for(user_ids, workspace)
    chat = dm.DirectChannel.objects.filter(team=team, memberships__user=viewer).first()
    return {
        "rows": rows,
        "active_count": sum(1 for m in memberships if m.status != dm.TeamMembership.Status.INACTIVE),
        "avg_load": (
            round(sum(m.current_load_percent for m in memberships) / len(memberships))
            if memberships else 0
        ),
        "week_hours": total_hours,
        "week_expected": total_expected,
        "week_percent": int(round(total_hours / total_expected * 100)) if total_expected else None,
        "projects": projects,
        "open_tasks": open_tasks.count(),
        "overdue_tasks": open_tasks.filter(due_date__lt=today).count(),
        "sprints": team.sprints.filter(is_archived=False).order_by("-start_date")[:5],
        "chat_channel": chat,
        "monday": monday,
    }
