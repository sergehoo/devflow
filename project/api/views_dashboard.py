"""
API du tableau de bord (frontend React, Phase 3).

Aucune logique nouvelle : on exécute ``DashboardView.get_context_data`` (la
vue Django existante, déjà scopée au workspace courant de l'utilisateur) et
on sérialise uniquement ce que l'ancien template affiche.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView


def _num(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def _iso(value):
    return value.isoformat() if isinstance(value, (date, datetime)) else None


def _name(user):
    if not user:
        return ""
    return user.get_full_name() or user.get_username()


def _task(task):
    return {
        "id": task.pk,
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
        "priority_label": task.get_priority_display(),
        "due_date": _iso(task.due_date),
        "estimate_hours": _num(task.estimate_hours),
        "project": task.project.name if task.project_id else "",
        "assignee": _name(task.assignee) if task.assignee_id else "",
    }


def serialize_dashboard(ctx) -> dict:
    ws = ctx.get("current_workspace")
    sprint = ctx.get("active_sprint")
    return {
        "workspace": {"id": ws.pk, "name": ws.name, "quarter_label": getattr(ws, "quarter_label", "")} if ws else None,
        "stats": {k: _num(v) for k, v in (ctx.get("stats") or {}).items()},
        "finance": {k: _num(v) for k, v in (ctx.get("finance") or {}).items()},
        "task_distribution": ctx.get("task_distribution") or {},
        "analysis_cards": [
            {k: item.get(k, "") for k in ("severity", "title", "text", "action")}
            for item in ctx.get("analysis_cards") or []
        ],
        "projects": [
            {
                "id": p.pk,
                "name": p.name,
                "status": p.status,
                "status_label": p.get_status_display(),
                "progress_percent": p.progress_percent,
                "risk_score": p.risk_score,
                "target_date": _iso(p.target_date),
                "team": p.team.name if p.team_id else "",
                "tech_stack": p.tech_stack or "",
            }
            for p in ctx.get("projects") or []
        ],
        "due_soon_tasks": [_task(t) for t in ctx.get("due_soon_tasks") or []],
        "active_sprint": {
            "id": sprint.pk,
            "name": sprint.name,
            "status_label": sprint.get_status_display(),
            "project": sprint.project.name if sprint.project_id else "",
            "team": sprint.team.name if sprint.team_id else "",
            "remaining_days": sprint.remaining_days,
            "total_story_points": sprint.total_story_points,
            "completed_story_points": sprint.completed_story_points,
            "columns": [
                {
                    "id": col["id"], "name": col["name"], "color": col["color"],
                    "count": col["count"], "is_done": col["is_done"],
                    "tasks": [_task(t) for t in col["tasks"]],
                }
                for col in ctx.get("kanban_columns") or []
            ],
        } if sprint else None,
        "team_load": [
            {
                "user": _name(m.user),
                "status_label": m.get_status_display(),
                "current_load_percent": _num(m.current_load_percent),
            }
            for m in ctx.get("team_load") or []
        ],
        "top_cost_members": [
            {
                "user": _name(p.user),
                "job_title": p.job_title or "",
                "cost_per_day": _num(p.cost_per_day),
                "currency": p.currency or "",
            }
            for p in ctx.get("top_cost_members") or []
        ],
        "activities": [
            {
                "id": a.pk,
                "title": a.title,
                "actor": _name(a.actor) if a.actor_id else "",
                "created_at": _iso(a.created_at),
            }
            for a in ctx.get("activities") or []
        ],
    }


class DashboardSummaryView(APIView):
    """GET /api/v1/dashboard/summary/ — contenu du tableau de bord du workspace courant."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from project.views import DashboardView

        django_request = request._request
        django_request.user = request.user  # authentification DRF (session ou jeton)
        view = DashboardView()
        view.setup(django_request)
        return Response(serialize_dashboard(view.get_context_data()))


# ─── Indicateurs du tableau de bord React (refonte UI) ───────────────────────
# Agrégats en lecture seule sur le workspace courant (même résolution que
# DashboardView). Aucune règle métier nouvelle : seuil de risque repris du
# tableau de bord historique (« projets à haut risque » : risk_score >= 70).

HIGH_RISK_SCORE = 70
PRIORITY_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


def _project_health(project) -> str:
    from project import models as dm

    if project.status == dm.Project.Status.DELAYED:
        return "delayed"
    if project.status == dm.Project.Status.BLOCKED or (project.risk_score or 0) >= HIGH_RISK_SCORE:
        return "at_risk"
    return "on_track"


def build_insights(user, workspace, weeks: int) -> dict:
    from datetime import timedelta

    from django.db.models import Case, Count, F, IntegerField, Q, Value, When
    from django.db.models.functions import TruncDate
    from django.utils import timezone

    from project import models as dm

    today = timezone.localdate()
    horizon = today + timedelta(days=7)
    open_task = ~Q(status__in=[dm.Task.Status.DONE, dm.Task.Status.CANCELLED])
    tasks = workspace.tasks.filter(is_archived=False)

    # Santé des projets actifs (hors terminés / annulés / archivés).
    active = workspace.projects.filter(is_archived=False).exclude(
        status__in=[dm.Project.Status.DONE, dm.Project.Status.CANCELLED])
    delayed = Q(status=dm.Project.Status.DELAYED)
    at_risk = ~delayed & (Q(status=dm.Project.Status.BLOCKED) | Q(risk_score__gte=HIGH_RISK_SCORE))
    h = active.aggregate(total=Count("id"), delayed=Count("id", filter=delayed), at_risk=Count("id", filter=at_risk))
    on_track = h["total"] - h["delayed"] - h["at_risk"]

    # Heatmap : tâches terminées par jour (completed_at), archivées comprises.
    start = today - timedelta(days=weeks * 7 - 1)
    per_day = {
        row["day"]: row["n"]
        for row in workspace.tasks.filter(status=dm.Task.Status.DONE, completed_at__date__gte=start)
        .annotate(day=TruncDate("completed_at")).values("day").annotate(n=Count("id"))
    }
    heatmap = [{"date": (start + timedelta(days=i)).isoformat(), "count": per_day.get(start + timedelta(days=i), 0)}
               for i in range(weeks * 7)]

    # Mes priorités : mes tâches ouvertes, priorité puis échéance.
    focus_qs = (
        tasks.filter(open_task, assignee=user).select_related("project", "assignee")
        .annotate(prank=Case(*[When(priority=k, then=Value(v)) for k, v in PRIORITY_RANK.items()],
                             default=Value(9), output_field=IntegerField()))
        .order_by("prank", F("due_date").asc(nulls_last=True), "-updated_at")
    )
    focus = [
        {**_task(t), "status_label": t.get_status_display(), "overdue": bool(t.due_date and t.due_date < today)}
        for t in focus_qs[:6]
    ]

    # À venir (7 jours) : mes tâches, mes réunions, jalons du workspace.
    upcoming = [
        {"kind": "task", "id": t.pk, "title": t.title, "subtitle": t.project.name if t.project_id else "",
         "date": t.due_date.isoformat(), "time": None, "url": f"/tasks/{t.pk}"}
        for t in tasks.filter(open_task, assignee=user, due_date__range=(today, horizon))
        .select_related("project").order_by("due_date")[:10]
    ]
    meetings = (
        dm.ProjectMeeting.objects.filter(workspace=workspace, is_archived=False,
                                         scheduled_at__date__range=(today, horizon))
        .exclude(status=dm.ProjectMeeting.Status.CANCELLED)
        .filter(Q(organizer=user) | Q(created_by=user) | Q(internal_participants=user))
        .select_related("project").distinct().order_by("scheduled_at")[:10]
    )
    for m in meetings:
        local = timezone.localtime(m.scheduled_at)
        upcoming.append({"kind": "meeting", "id": m.pk, "title": m.title,
                         "subtitle": m.project.name if m.project_id else "Réunion", "date": local.date().isoformat(),
                         "time": local.strftime("%H:%M"), "url": f"/meetings/{m.pk}"})
    for ms in (dm.Milestone.objects.filter(project__workspace=workspace, project__is_archived=False, is_archived=False,
                                           due_date__range=(today, horizon))
               .exclude(status__in=[dm.Milestone.Status.DONE, dm.Milestone.Status.MISSED])
               .select_related("project").order_by("due_date")[:10]):
        upcoming.append({"kind": "milestone", "id": ms.pk, "title": ms.name,
                         "subtitle": ms.project.name, "date": ms.due_date.isoformat(), "time": None,
                         "url": f"/m/milestone/{ms.pk}"})
    upcoming.sort(key=lambda i: (i["date"], i["time"] or "99:99"))

    # Ma journée : mes tâches prévues aujourd'hui (hors annulées) et terminées.
    day = workspace.tasks.filter(is_archived=False, assignee=user, due_date=today).exclude(
        status=dm.Task.Status.CANCELLED).aggregate(planned=Count("id"), done=Count("id", filter=Q(status=dm.Task.Status.DONE)))
    day["completed_today"] = workspace.tasks.filter(assignee=user, status=dm.Task.Status.DONE,
                                                    completed_at__date=today).count()

    # Projets : actifs récemment mis à jour, avec membres (3 premiers).
    recent = active.select_related("team").prefetch_related("members__user").order_by("-updated_at")[:5]
    projects = []
    for p in recent:
        members = list(p.members.all())  # préchargés
        projects.append({"id": p.pk, "name": p.name, "status_label": p.get_status_display(),
                         "progress_percent": p.progress_percent, "health": _project_health(p),
                         "target_date": _iso(p.target_date), "members": [_name(m.user) for m in members[:3]],
                         "members_count": len(members)})

    return {
        "workspace": {"id": workspace.pk, "name": workspace.name},
        "today": today.isoformat(),
        "day": day,
        "health": {"active": h["total"], "on_track": on_track, "at_risk": h["at_risk"], "delayed": h["delayed"],
                   "healthy_percent": round(on_track * 100 / h["total"]) if h["total"] else None},
        "overdue_tasks": tasks.filter(open_task, due_date__lt=today).count(),
        "weeks": weeks,
        "heatmap": heatmap,
        "completed_in_period": sum(per_day.values()),
        "focus": focus,
        "focus_total": focus_qs.count(),
        "upcoming": upcoming[:8],
        "projects": projects,
    }


class DashboardInsightsView(APIView):
    """GET /api/v1/dashboard/insights/?weeks=15 — santé, heatmap, priorités, à venir (workspace courant)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from project.views import DashboardView

        django_request = request._request
        django_request.user = request.user
        view = DashboardView()
        view.setup(django_request)
        workspace = view.get_current_workspace()
        if workspace is None:
            return Response({"workspace": None})
        try:
            weeks = min(max(int(request.query_params.get("weeks", 15)), 4), 52)
        except (TypeError, ValueError):
            weeks = 15
        return Response(build_insights(request.user, workspace, weeks))
