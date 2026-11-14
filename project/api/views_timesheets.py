"""
API Timesheets (frontend React, Phase 3).

Enveloppes fines des vues et services existants — aucune règle nouvelle :
* ``GET timesheet/week/?date=&user=`` → ``TimesheetCalendarView.get_week_context`` (sa semaine) ;
  avec ``user`` (subordonné visible) : résumé ``week_summary`` + lignes, en lecture seule ;
* ``GET timesheet/weeks/`` → semaines groupées de ``TimesheetEntryListView`` (visibilité N+1, ``can_review``) ;
* ``GET timesheet/entries/`` → historique (périmètre ``TimesheetEntryListView``) + filtres + totaux ;
* ``GET timesheet/export/`` → mêmes saisies et mêmes filtres, en classeur Excel ;
* ``GET timesheet/week/export/?date=&user=`` → feuille de temps d'une semaine (soi ou subordonné visible) en Excel ;
* écritures : ponts ``actions/timesheet-cell``, ``actions/timesheet-week``,
  ``actions/timesheet-entry-delete`` et ``forms/timesheet-entry/<pk>/`` (vues Django).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Q, Sum
from django.http import HttpResponse
from rest_framework import permissions
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.pagination import PageNumberPagination

from project.api.pagination import FlexiblePagination
from rest_framework.response import Response
from rest_framework.views import APIView

from project import models as dm
from project.services import timesheet_export as tx

User = get_user_model()
Status = dm.TimesheetEntry.ApprovalStatus
EDITABLE = {Status.DRAFT, Status.REJECTED}
EXPORT_MAX_ROWS = 50_000


def _f(value) -> float:
    return float(value or 0)


def _name(user) -> str:
    return (user.get_full_name() or user.get_username()) if user else ""


def _django_view(view_class, request):
    django_request = request._request
    django_request.user = request.user
    view = view_class()
    view.setup(django_request)
    return view, django_request


def _summary(s) -> dict | None:
    if s is None:
        return None
    log = s.last_log
    return {
        "monday": s.monday.isoformat(),
        "status": s.status,
        "status_label": s.status_label,
        "is_locked": s.is_locked,
        "total_hours": _f(s.total_hours),
        "planned_hours": _f(s.planned_hours),
        "capacity": _f(s.capacity),
        "expected": _f(s.expected),
        "missing_hours": _f(s.missing_hours),
        "completion_percent": s.completion_percent,
        "last_log": {
            "action": log.action, "action_label": log.get_action_display(), "actor": _name(log.actor),
            "comment": getattr(log, "comment", "") or "", "created_at": log.created_at.isoformat(),
        } if log else None,
    }


def _history(workspace, employee, monday) -> list[dict]:
    logs = dm.TimesheetApprovalLog.objects.filter(
        workspace=workspace, employee=employee, week_start=monday,
    ).select_related("actor").order_by("-created_at")[:20]
    return [
        {"action": l.action, "action_label": l.get_action_display(), "actor": _name(l.actor),
         "comment": getattr(l, "comment", "") or "", "created_at": l.created_at.isoformat()}
        for l in logs
    ]


def _date_param(params, key):
    try:
        return date.fromisoformat(params[key]) if params.get(key) else None
    except ValueError:
        raise ValidationError({"detail": "Date invalide (AAAA-MM-JJ)."})


def _int_param(params, key):
    value = (params.get(key) or "").strip()
    if not value:
        return None
    if not value.isdigit():
        raise ValidationError({key: "Identifiant invalide."})
    return int(value)


def _filtered_entries(request):
    """Saisies visibles (soi + subordonnés, workspace courant) filtrées comme l'historique."""
    from project.views import TimesheetEntryListView

    view, _ = _django_view(TimesheetEntryListView, request)
    scope = view.get_queryset()
    qs = scope.select_related("user", "project", "task")
    p = request.query_params
    date_from, date_to = _date_param(p, "date_from"), _date_param(p, "date_to")
    if date_from:
        qs = qs.filter(entry_date__gte=date_from)
    if date_to:
        qs = qs.filter(entry_date__lte=date_to)
    for param, lookup in (("user", "user_id"), ("project", "project_id")):
        value = _int_param(p, param)
        if value is not None:
            qs = qs.filter(**{lookup: value})
    if p.get("approval_status"):
        qs = qs.filter(approval_status=p["approval_status"])
    if p.get("is_billable") in ("true", "false"):
        qs = qs.filter(is_billable=p["is_billable"] == "true")
    team = _int_param(p, "team")
    if team is not None:
        qs = qs.filter(user__devflow_memberships__team_id=team).distinct()
    if p.get("search"):
        term = p["search"].strip()
        qs = qs.filter(
            Q(description__icontains=term) | Q(project__name__icontains=term) | Q(task__title__icontains=term)
            | Q(user__first_name__icontains=term) | Q(user__last_name__icontains=term) | Q(user__username__icontains=term)
        )
    return view, scope, qs


def _filter_lines(request, scope) -> list[str]:
    """Filtres appliqués, en clair, pour l'onglet « Informations » de l'export."""
    p = request.query_params
    lines = []
    date_from, date_to = _date_param(p, "date_from"), _date_param(p, "date_to")
    if date_from or date_to:
        lines.append(f"Période : {f'{date_from:%d/%m/%Y}' if date_from else '…'} → {f'{date_to:%d/%m/%Y}' if date_to else '…'}")
    user_id = _int_param(p, "user")
    if user_id is not None:
        user = User.objects.filter(pk=user_id, pk__in=scope.values("user_id")).first()
        lines.append(f"Collaborateur : {_name(user) if user else user_id}")
    project_id = _int_param(p, "project")
    if project_id is not None:
        project = dm.Project.objects.filter(pk=project_id, pk__in=scope.values("project_id")).first()
        lines.append(f"Projet : {project.name if project else project_id}")
    if p.get("approval_status"):
        lines.append(f"Statut : {tx.STATUS_LABELS.get(p['approval_status'], p['approval_status'])}")
    if p.get("is_billable") in ("true", "false"):
        lines.append("Facturable : oui" if p["is_billable"] == "true" else "Facturable : non")
    team_id = _int_param(p, "team")
    if team_id is not None:
        lines.append(f"Équipe : {team_id}")
    if p.get("search", "").strip():
        lines.append(f"Recherche : {p['search'].strip()}")
    return lines


def _xlsx_response(content: bytes, filename: str) -> HttpResponse:
    response = HttpResponse(content, content_type=tx.XLSX_MIME)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "no-store"
    return response


class TimesheetWeekView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from project.views import TimesheetCalendarView

        view, django_request = _django_view(TimesheetCalendarView, request)
        ws = view.get_current_workspace()
        target_id = request.query_params.get("user")
        if target_id and str(target_id) != str(request.user.pk):
            return self._other_user_week(request, ws, target_id)

        ctx = view.get_week_context(django_request)
        days = ctx["days"]
        rows = []
        for row in ctx["grid"]:
            task = row.get("task")
            project = row.get("project")
            rows.append({
                "kind": row["kind"],
                "row_id": row["row_id"],
                "label": row["label"],
                "task": {"id": task.pk, "title": task.title, "status_label": task.get_status_display()} if task else None,
                "project": {"id": project.pk, "name": project.name} if project else None,
                "description": row.get("description") or "",
                "cells": [{"date": c["date"].isoformat(), "hours": c["hours"]} for c in row["cells"]],
                "total": row["total"],
            })
        summary = ctx["week_summary"]
        return Response({
            "user": {"id": request.user.pk, "name": _name(request.user)},
            "is_self": True,
            "monday": ctx["monday"].isoformat(),
            "iso_week": ctx["iso_week"],
            "year": ctx["year"],
            "days": [{"date": d.isoformat(), "label": m["label"]} for d, m in zip(days, ctx["days_meta"])],
            "today": ctx["today"].isoformat(),
            "prev_week": ctx["prev_week"].isoformat(),
            "next_week": ctx["next_week"].isoformat(),
            "rows": rows,
            "day_totals": {d.isoformat(): v for d, v in ctx["day_totals"].items()},
            "week_total": ctx["week_total"],
            "week_status": ctx["week_status"],
            "week_status_label": ctx["week_status_label"],
            "is_locked": ctx["is_locked"],
            "can_submit": ctx["can_submit"],
            "can_review": False,
            "summary": _summary(summary),
            "history": _history(ws, request.user, ctx["monday"]) if ws else [],
            "projects": [{"id": p.pk, "name": p.name} for p in ctx["projects"]],
        })

    def _other_user_week(self, request, ws, target_id):
        """Semaine d'un subordonné (lecture + validation N+1) — périmètre ``visible_user_ids``."""
        from datetime import timedelta

        from django.utils import timezone

        from project.services import timesheet_workflow as tw

        if not ws or not str(target_id).isdigit() or int(target_id) not in tw.visible_user_ids(request.user, ws):
            raise NotFound()
        employee = User.objects.get(pk=target_id)
        try:
            day = date.fromisoformat(request.query_params.get("date") or "")
        except ValueError:
            day = timezone.localdate()
        monday, sunday = tw.week_bounds(day)
        entries = tw.week_entries(employee, ws, monday).select_related("task", "project")
        days = [monday + timedelta(days=i) for i in range(7)]
        labels = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
        grid: dict[tuple, dict] = {}
        day_totals = {d.isoformat(): 0.0 for d in days}
        for e in entries:
            key = ("task", e.task_id) if e.task_id else ("activity", e.project_id, (e.description or "Activité").strip().lower())
            row = grid.setdefault(key, {
                "kind": key[0], "row_id": "-".join(str(k) for k in key),
                "label": e.task.title if e.task_id else (e.description or "Activité").strip(),
                "task": {"id": e.task_id, "title": e.task.title, "status_label": e.task.get_status_display()} if e.task_id else None,
                "project": {"id": e.project_id, "name": e.project.name} if e.project_id else None,
                "description": "" if e.task_id else (e.description or ""),
                "cells": {d.isoformat(): 0.0 for d in days}, "total": 0.0,
            })
            row["cells"][e.entry_date.isoformat()] += _f(e.hours)
            row["total"] += _f(e.hours)
            day_totals[e.entry_date.isoformat()] += _f(e.hours)
        rows = [{**r, "cells": [{"date": k, "hours": v} for k, v in r["cells"].items()]} for r in grid.values()]
        summary = tw.week_summary(employee, ws, monday)
        return Response({
            "user": {"id": employee.pk, "name": _name(employee)},
            "is_self": False,
            "monday": monday.isoformat(), "iso_week": monday.isocalendar()[1], "year": monday.year,
            "days": [{"date": d.isoformat(), "label": labels[i]} for i, d in enumerate(days)],
            "today": timezone.localdate().isoformat(),
            "prev_week": (monday - timedelta(days=7)).isoformat(), "next_week": (monday + timedelta(days=7)).isoformat(),
            "rows": rows, "day_totals": day_totals, "week_total": sum(day_totals.values()),
            "week_status": summary.status, "week_status_label": summary.status_label,
            "is_locked": True, "can_submit": False,
            "can_review": tw.is_direct_manager(request.user, employee, ws),
            "summary": _summary(summary),
            "history": _history(ws, employee, monday),
            "projects": [],
        })


class TimesheetWeeksView(APIView):
    """Semaines groupées par collaborateur (même calcul que la liste Django)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from project.views import TimesheetEntryListView

        view, _ = _django_view(TimesheetEntryListView, request)
        view.object_list = view.get_queryset()
        groups = view.get_context_data()["weekly_groups"]
        status_filter = request.query_params.get("status")
        user_filter = request.query_params.get("user")
        scope = request.query_params.get("scope")  # "review" = semaines de mes N-1 à traiter
        date_from = _date_param(request.query_params, "date_from")
        date_to = _date_param(request.query_params, "date_to")
        rows = []
        for g in groups:
            if status_filter and g["status"] != status_filter:
                continue
            if user_filter and str(g["user"].pk) != user_filter:
                continue
            if scope == "review" and not g["can_review"]:
                continue
            if (date_from and g["sunday"] < date_from) or (date_to and g["monday"] > date_to):
                continue
            rows.append({
                "user": {"id": g["user"].pk, "name": _name(g["user"])},
                "monday": g["monday"].isoformat(), "sunday": g["sunday"].isoformat(),
                "iso_week": g["iso_week"], "year": g["year"],
                "total_hours": g["total_hours"], "entry_count": g["entry_count"],
                "status": g["status"], "status_label": g["status_label"],
                "can_review": g["can_review"], "is_mine": g["is_mine"],
            })
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        response = paginator.get_paginated_response(page)
        collaborators = User.objects.filter(pk__in=view.object_list.values("user_id")).order_by("first_name", "last_name", "username")
        response.data["collaborators"] = [{"id": u.pk, "name": _name(u)} for u in collaborators]
        return response


class TimesheetEntriesView(APIView):
    """Historique des saisies visibles + filtres + totaux (facturable / non facturable)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        _, scope, qs = _filtered_entries(request)

        totals = qs.aggregate(total=Sum("hours"), billable=Sum("hours", filter=Q(is_billable=True)))
        by_user, by_project = defaultdict(lambda: [Decimal(0), Decimal(0), ""]), defaultdict(lambda: [Decimal(0), Decimal(0), ""])
        for row in qs.values("user_id", "user__first_name", "user__last_name", "user__username", "project_id", "project__name", "is_billable").annotate(h=Sum("hours")):
            for bucket, key, label in (
                (by_user, row["user_id"], f'{row["user__first_name"]} {row["user__last_name"]}'.strip() or row["user__username"]),
                (by_project, row["project_id"], row["project__name"] or "Sans projet"),
            ):
                bucket[key][0] += row["h"] or 0
                if row["is_billable"]:
                    bucket[key][1] += row["h"] or 0
                bucket[key][2] = label

        def breakdown(bucket):
            items = [{"id": k, "name": v[2], "hours": _f(v[0]), "billable_hours": _f(v[1])} for k, v in bucket.items()]
            return sorted(items, key=lambda i: -i["hours"])[:10]

        collaborators = User.objects.filter(pk__in=scope.values("user_id")).order_by("first_name", "last_name", "username")
        projects = dm.Project.objects.filter(pk__in=scope.values("project_id")).order_by("name")
        paginator = FlexiblePagination()
        page = paginator.paginate_queryset(qs.order_by("-entry_date", "user_id", "-id"), request, view=self)
        me = request.user.pk
        response = paginator.get_paginated_response([
            {
                "id": e.pk, "entry_date": e.entry_date.isoformat(),
                "user": {"id": e.user_id, "name": _name(e.user)},
                "project": {"id": e.project_id, "name": e.project.name} if e.project_id else None,
                "task": {"id": e.task_id, "title": e.task.title} if e.task_id else None,
                "hours": _f(e.hours), "planned_hours": _f(e.planned_hours) if e.planned_hours is not None else None,
                "description": e.description, "is_billable": e.is_billable,
                "approval_status": e.approval_status, "approval_status_label": e.get_approval_status_display(),
                # Miroir UX de _editable_own_entries (Django refait le contrôle à l'écriture).
                "can_edit": e.user_id == me and e.approval_status in EDITABLE,
            }
            for e in page
        ])
        response.data["collaborators"] = [{"id": u.pk, "name": _name(u)} for u in collaborators]
        response.data["projects"] = [{"id": p.pk, "name": p.name} for p in projects]
        response.data["totals"] = {
            "hours": _f(totals["total"]), "billable_hours": _f(totals["billable"]),
            "non_billable_hours": _f((totals["total"] or 0) - (totals["billable"] or 0)),
            "by_user": breakdown(by_user), "by_project": breakdown(by_project),
        }
        return response


class TimesheetExportView(APIView):
    """Export Excel de l'historique : mêmes filtres et même périmètre que ``timesheet/entries/``."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        view, scope, qs = _filtered_entries(request)
        if qs.count() > EXPORT_MAX_ROWS:
            raise ValidationError({"detail": f"Export limité à {EXPORT_MAX_ROWS} saisies : affinez la période ou les filtres."})
        workspace = view.get_current_workspace()
        content = tx.entries_workbook(
            qs.order_by("-entry_date", "user__last_name", "user__first_name", "-id"),
            exporter=request.user, workspace=workspace, filter_lines=_filter_lines(request, scope),
        )
        p = request.query_params
        return _xlsx_response(content, tx.filename("Timesheets", p.get("date_from", ""), p.get("date_to", "")))


class TimesheetWeekExportView(APIView):
    """Feuille de temps d'une semaine en Excel — soi-même ou un subordonné visible (sinon 404)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from django.utils import timezone

        from project.services import timesheet_workflow as tw
        from project.views import TimesheetCalendarView

        view, _ = _django_view(TimesheetCalendarView, request)
        ws = view.get_current_workspace()
        target = request.query_params.get("user") or str(request.user.pk)
        if not ws or not target.isdigit() or int(target) not in tw.visible_user_ids(request.user, ws):
            raise NotFound()
        employee = User.objects.get(pk=target)
        try:
            day = date.fromisoformat(request.query_params.get("date") or "")
        except ValueError:
            day = timezone.localdate()
        monday, _ = tw.week_bounds(day)
        history = list(
            dm.TimesheetApprovalLog.objects.filter(workspace=ws, employee=employee, week_start=monday)
            .select_related("actor").order_by("-created_at")[:20]
        )
        content = tx.week_workbook(
            employee=employee, workspace=ws, monday=monday,
            entries=tw.week_entries(employee, ws, monday).select_related("user", "task", "project"),
            summary=tw.week_summary(employee, ws, monday), history=history, exporter=request.user,
        )
        return _xlsx_response(content, tx.filename("Timesheet", _name(employee), tx.week_label(monday)))
