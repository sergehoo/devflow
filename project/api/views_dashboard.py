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
