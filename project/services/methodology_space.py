"""
Espace méthodologie d'un projet (Scrum / Kanban / Waterfall) au format JSON.

Mêmes sélections que ``views_methodology`` (Project{Scrum,Kanban,Waterfall}WorkspaceView,
ProjectMethodologyDashboardView) et mêmes indicateurs (``methodology.kpis.compute_kpi``) :
aucun calcul nouveau, seulement la sérialisation pour le frontend React.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from project.services.methodology.kpis import compute_kpi

KIND_KPIS = {
    "scrum": ("velocity", "burndown_sprint", "sprint_success_rate"),
    "kanban": ("wip_count", "cycle_time", "lead_time", "throughput_weekly", "cumulative_flow"),
    "waterfall": ("advancement_global", "schedule_adherence", "budget_consumption", "critical_path_length", "gantt_data"),
}


def _json(value):
    if isinstance(value, dict):
        return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _task(t) -> dict:
    return {"id": t.pk, "title": t.title, "status": t.status, "status_label": t.get_status_display(),
            "priority_label": t.get_priority_display(),
            "assignee": (t.assignee.get_full_name() or t.assignee.get_username()) if t.assignee_id else ""}


def _kind(project, methodology) -> str:
    code = ((methodology.code if methodology else "") or getattr(project, "methodology", "") or "").lower()
    for kind in KIND_KPIS:
        if kind in code:
            return kind
    return ""


def build_space(project) -> dict:
    from project.views_methodology import _resolve_methodology

    methodology = _resolve_methodology(project)
    kind = _kind(project, methodology)
    data: dict = {
        "kind": kind,
        "methodology": {"name": methodology.name, "code": methodology.code} if methodology else None,
        "kpis": {code: compute_kpi(project, code) for code in KIND_KPIS.get(kind, ())},
        "dashboard": [],
    }
    if methodology:
        data["dashboard"] = [
            {"name": kpi.name if hasattr(kpi, "name") else kpi.compute_strategy, "pinned": kpi.is_pinned,
             "result": compute_kpi(project, kpi.compute_strategy)}
            for kpi in methodology.kpis.order_by("-is_pinned", "position")
        ]

    if kind == "scrum":
        sprint = project.sprints.filter(status__in=["ACTIVE", "PLANNED"]).order_by("status", "-start_date").first()
        data["active_sprint"] = sprint and {
            "id": sprint.pk, "name": str(sprint), "status_label": sprint.get_status_display(),
            "start_date": sprint.start_date, "end_date": sprint.end_date, "goal": sprint.goal,
            "tasks": [_task(t) for t in sprint.tasks.select_related("assignee").order_by("priority")],
        }
        data["backlog"] = [
            {"id": b.pk, "title": str(b), "status_label": b.get_item_type_display()}
            for b in project.backlog_items.filter(is_archived=False).order_by("rank", "-created_at")[:50]
        ]
        data["sprints"] = [{"id": s.pk, "name": str(s), "status_label": s.get_status_display()}
                           for s in project.sprints.order_by("-number")[:5]]
    elif kind == "kanban" and methodology:
        columns = []
        for status in methodology.statuses.order_by("position"):
            tasks = project.tasks.filter(status=status.code.upper())
            count = tasks.count()
            columns.append({
                "code": status.code, "name": status.name, "wip_limit": status.wip_limit, "count": count,
                "over_wip": status.wip_limit is not None and count > status.wip_limit,
                "tasks": [_task(t) for t in tasks.select_related("assignee")[:30]],
            })
        data["columns"] = columns
    elif kind == "waterfall":
        data["phases"] = [
            {"id": p.pk, "name": p.name, "status_label": p.get_status_display() if hasattr(p, "get_status_display") else "",
             "start_date": getattr(p, "start_date", None), "end_date": getattr(p, "end_date", None),
             "progress": getattr(p, "progress_percent", None),
             "owner": (p.owner.get_full_name() or p.owner.get_username()) if getattr(p, "owner_id", None) else ""}
            for p in project.phases.select_related("owner").order_by("position", "id")
        ]
        data["milestones"] = [{"id": m.pk, "name": str(m), "due_date": m.due_date}
                              for m in project.milestones.order_by("due_date")[:10]]
    return _json(data)
