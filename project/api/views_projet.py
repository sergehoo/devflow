"""
Chantier « projet » — fiche détaillée complète du projet pour le frontend React.

Aucune règle métier n'est réécrite : chaque endpoint exécute la vue Django
historique (``dispatch`` complet) puis sérialise son contexte / sa réponse.

* ``GET  projects/<pk>/detail-tabs/?tab=<clé>``
    contexte de ``ProjectDetailView`` (mêmes sélections et calculs) : en-tête,
    bandeau KPI, bandeau d'informations, onglets (compteurs) et données de
    l'onglet demandé uniquement (chargement paresseux côté React).
* ``POST projects/<pk>/detail-tabs/ai-forecast/``       → ``ProjectBudgetForecastView`` (IA, throttle)
* ``POST projects/<pk>/detail-tabs/ai-risk-analysis/``  → ``ProjectRiskAnalysisView`` (IA, throttle)
* ``GET  projects/<pk>/detail-tabs/ai-generation/``     → ``ProjectAIProposalStatusView`` (polling)
* ``POST projects/<pk>/detail-tabs/ai-generation/``     → ``ProjectAIProposalTriggerView`` (mode AJAX, throttle)
* ``GET|POST projects/<pk>/detail-tabs/invoice-generate/`` → ``InvoiceGenerateFromProjectView``

Sécurité (Django reste l'autorité) :
* projet résolu dans les workspaces de l'utilisateur (404 sinon), puis vue
  Django exécutée avec ``?workspace=<workspace du projet>`` validé par
  ``DevflowBaseMixin.get_workspace_id`` ;
* données financières (montants, factures) servies uniquement si
  ``ProjectFinancialPermissionMixin.can_view_financials`` (RBAC ``budget.view``,
  même règle que les vues budget et l'API ``budget-panel``) ; TJM individuels
  (coûts équipe) : RBAC ``billing.view`` en plus (comme l'API ``billing-rates``) ;
  génération de facture : RBAC ``invoice.create`` ;
* gestion des membres : ``can_manage_project_members`` (drapeau
  ``can_manage_members`` ; les vues Django ProjectMember* l'imposent) ;
* actions IA payantes limitées par ``AIActionRateThrottle``.
"""

from __future__ import annotations

import json
import posixpath
from decimal import Decimal
from functools import lru_cache

from django.core.exceptions import ObjectDoesNotExist, PermissionDenied as DjangoPermissionDenied
from django.db.models import Count
from django.http import Http404, JsonResponse
from django.urls import Resolver404, resolve
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.text import Truncator
from rest_framework import permissions, status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from project import models as dm
from project.api.throttles import AIActionRateThrottle
from project.utils.workspaces import get_user_workspace_ids

ZERO = Decimal("0.00")
FINANCIAL_TABS = {"budget_estimatif", "budget_previsionnel", "facturation_client", "depenses"}
TAB_LABELS = {
    "planification": "Planification",
    "budget_estimatif": "Budget estimatif",
    "budget_previsionnel": "Budget prévisionnel",
    "facturation_client": "Facturation client",
    "depenses": "Dépenses",
    "equipes": "Équipes",
    "evolution": "Évolution",
    "taches": "Tâches",
    "kpi_roi": "KPI & ROI",
    "documents": "Documents",
    "meetings": "Réunions",
}
DOC_TYPES = {
    "pdf": "PDF", "doc": "Word", "docx": "Word", "xls": "Excel", "xlsx": "Excel", "ppt": "PowerPoint",
    "pptx": "PowerPoint", "txt": "Texte", "csv": "CSV", "png": "Image", "jpg": "Image", "jpeg": "Image",
    "webp": "Image", "gif": "Image", "svg": "Image", "html": "HTML", "htm": "HTML",
}
INVOICE_FORM_LABELS = {
    "mode": "Mode de facturation", "period_start": "Période — début", "period_end": "Période — fin",
    "tax_rate": "Taux de TVA (%)", "currency": "Devise", "title": "Titre (optionnel)", "notes": "Notes",
}
# Barre de progression de la roadmap visuelle (règle du template _planification.html).
ROADMAP_BAR = {"DONE": 100, "IN_PROGRESS": 65, "AT_RISK": 85}


# ─── Helpers ────────────────────────────────────────────────────────────────
def _user(u) -> str:
    return (u.get_full_name() or u.get_username()) if u else ""


def _d(value):
    return value.isoformat() if value else None


def _m(value) -> str:
    """Montant / heures (Decimal) → chaîne, comme les sérialiseurs DRF existants."""
    if value is None:
        return "0"
    return str(value)


def _money_dict(data: dict) -> dict:
    return {k: (_m(v) if isinstance(v, Decimal) else v) for k, v in data.items()}


def _display(obj, field: str) -> str:
    getter = getattr(obj, f"get_{field}_display", None)
    return str(getter()) if getter else str(getattr(obj, field, "") or "")


def _scoped_project(request, pk) -> dm.Project:
    """SECURITY : projet hors des workspaces de l'utilisateur → 404 (avant toute vue Django)."""
    project = (
        dm.Project.objects.select_related("workspace")
        .filter(pk=pk, workspace_id__in=get_user_workspace_ids(request.user))
        .first()
    )
    if project is None:
        raise NotFound("Projet introuvable.")
    return project


def _can_view_financials(request, project) -> bool:
    from project.views_budget import ProjectFinancialPermissionMixin

    checker = ProjectFinancialPermissionMixin()
    checker.request = request._request if hasattr(request, "_request") else request
    return checker.can_view_financials(project)


def _rbac(request, action: str, project) -> bool:
    """Permission RBAC stricte (sans repli historique TeamMembership.role) dans le workspace du projet."""
    from project.services.rbac import RBACService

    return RBACService.can(request.user, action, workspace=project.workspace)


def _prepare(request, project):
    """Requête Django transmise à la vue historique : utilisateur DRF + workspace du projet (validé par la vue)."""
    django_request = request._request
    django_request.user = request.user
    query = django_request.GET.copy()
    query["workspace"] = str(project.workspace_id)
    django_request.GET = query
    return django_request


def _dispatch(request, project, view_class, kwargs: dict):
    django_request = _prepare(request, project)
    view = view_class()
    view.setup(django_request, **kwargs)
    try:
        return view, view.dispatch(django_request, **kwargs)
    except (Http404, ObjectDoesNotExist):
        raise NotFound()
    except DjangoPermissionDenied as exc:
        raise PermissionDenied(str(exc) or None)


def _json_passthrough(response, denied_message: str):
    """Réponse JSON d'une vue Django → Response DRF (403 → message français)."""
    if not isinstance(response, JsonResponse):
        raise NotFound()
    data = json.loads(response.content or b"{}")
    if response.status_code == 403:
        raise PermissionDenied(denied_message)
    if response.status_code == 404:
        raise NotFound()
    return Response(data, status=response.status_code)


# ─── Contexte de la fiche (ProjectDetailView) ───────────────────────────────
@lru_cache(maxsize=1)
def _detail_view_class():
    """
    ``ProjectDetailView`` telle quelle, sauf le prédicat financier aligné sur
    ``ProjectFinancialPermissionMixin.can_view_financials`` (RBAC ``budget.view``,
    PR26) — même règle que les vues budget Django et l'API ``budget-panel``.
    Les calculs financiers restent ceux de la vue.
    """
    from project.views import ProjectDetailView

    class _ReactProjectDetailView(ProjectDetailView):
        def can_view_financial_data(self, project):
            return _can_view_financials(self.request, project)

    return _ReactProjectDetailView


def _deps(ctx) -> dict:
    qs = ctx["task_dependencies"]
    return {
        **ctx["dependency_summary"],
        "items": [
            {
                "id": dep.pk,
                "from_task": {"id": dep.from_task_id, "title": dep.from_task.title},
                "to_task": {"id": dep.to_task_id, "title": dep.to_task.title},
                "type": dep.dependency_type,
                "type_label": _display(dep, "dependency_type"),
            }
            for dep in qs[:12]
        ],
    }


def _tab_planification(ctx, fin, request):
    return {
        "stats": ctx["planning_stats"],
        "milestones": [
            {"id": m.pk, "name": m.name, "due_date": _d(m.due_date), "owner": _user(m.owner),
             "status": m.status, "status_label": _display(m, "status"), "progress_percent": m.progress_percent or 0}
            for m in ctx["milestones"].select_related("owner")
        ],
        "sprints": [
            {"id": s.pk, "name": s.name, "start_date": _d(s.start_date), "end_date": _d(s.end_date),
             "status": s.status, "status_label": _display(s, "status"),
             "tasks_count": s.tasks_count, "backlog_count": s.backlog_count, "metrics_count": s.metrics_count}
            for s in ctx["sprints"]
        ],
        "releases": [
            {"id": r.pk, "name": r.name, "release_date": _d(r.release_date), "tag": r.tag or "",
             "status": r.status, "status_label": _display(r, "status")}
            for r in ctx["releases"]
        ],
        "roadmap_items": [
            {"id": i.pk, "title": i.title, "color": i.color or "", "status": i.status, "status_label": _display(i, "status"),
             "roadmap": i.roadmap.name if i.roadmap_id else "", "roadmap_id": i.roadmap_id,
             "start_date": _d(i.start_date), "end_date": _d(i.end_date), "duration_days": i.duration_days or 0,
             "milestone": i.milestone.name if i.milestone_id else "", "bar_percent": ROADMAP_BAR.get(i.status, 25)}
            for i in ctx["roadmap_items"]
        ],
        "backlog": [
            {"id": b.pk, "title": b.title, "item_type_label": _display(b, "item_type"),
             "sprint": b.sprint.name if b.sprint_id else "", "story_points": b.story_points or 0,
             "reporter": _user(b.reporter)}
            for b in ctx["all_backlog_items"].select_related("sprint", "reporter")
        ],
        "dependencies": _deps(ctx),
        "ai_alerts": [
            {"id": a.pk, "title": a.title, "summary": a.summary, "recommendation": a.recommendation or "",
             "severity": a.severity, "severity_label": _display(a, "severity")}
            for a in ctx["planning_ai_insights"]
        ],
    }


def _tab_budget_estimatif(ctx, fin, request):
    budget, ov, est = ctx["budget_obj"], ctx["financial_overview"], ctx["estimate_stats"]
    return {
        "currency": ov["currency"],
        "budget_id": budget.pk if budget else None,
        "cards": {
            "labor_cost": _m(budget.estimated_labor_cost if budget else est["labor_cost"]),
            "software_cost": _m(budget.estimated_software_cost if budget else ZERO),
            "infra_cost": _m(budget.estimated_infra_cost if budget else ZERO),
            "subcontract_cost": _m(budget.estimated_subcontract_cost if budget else ZERO),
            "total_estimated": _m(ov["estimated_cost"]),
        },
        "markup_percent": _m(budget.markup_percent if budget else ZERO),
        "total_estimated_sale": _m(est["total_estimated_sale"]),
        "planned_revenue": _m(ov["planned_revenue"]),
        "total_estimated_margin": _m(est["total_estimated_margin"]),
        "baseline_cost": _m(est["baseline_cost"]),
        "forecast_cost": _m(est["forecast_cost"]),
        "raf_cost": _m(est["raf_cost"]),
        "lines": [
            {"id": line.pk, "label": line.label, "category": str(line.category) if line.category_id else "",
             "budget_stage_label": _display(line, "budget_stage"), "source_type_label": _display(line, "source_type"),
             "quantity": _m(line.quantity), "cost_unit_amount": _m(line.cost_unit_amount),
             "cost_amount": _m(line.cost_amount), "sale_amount": _m(line.sale_amount),
             "margin_amount": _m(line.margin_amount) if line.margin_amount is not None else "0"}
            for line in ctx["estimate_lines"]
        ],
    }


def _tab_budget_previsionnel(ctx, fin, request):
    budget, ov, rev = ctx["budget_obj"], ctx["financial_overview"], ctx["revenue_stats"]
    return {
        "currency": ov["currency"],
        "budget_id": budget.pk if budget else None,
        "approved_budget": _m(ov["approved_budget"]),
        "planned_revenue": _m(ov["planned_revenue"]),
        "actual_cost": _m(ov["actual_cost"]),
        "forecast_margin": _m(ov["forecast_margin"]),
        "target_margin_percent": budget.target_margin_percent if budget else 0,
        "profit_margin_percent": ov["profit_margin_percent"],
        "expense_ratio_percent": ov["expense_ratio_percent"],
        "invoiced_revenue": _m(rev["invoiced_revenue"]),
        "received_revenue": _m(rev["received_revenue"]),
        "remaining_to_invoice": _m(rev["remaining_to_invoice"]),
        "remaining_to_collect": _m(rev["remaining_to_collect"]),
        "revenues": [
            {"id": r.pk, "title": r.title, "revenue_type_label": _display(r, "revenue_type"),
             "amount": _m(r.amount), "invoiced_amount": _m(r.invoiced_amount), "received_amount": _m(r.received_amount),
             "currency": r.currency or ov["currency"], "expected_date": _d(r.expected_date), "is_received": bool(r.is_received)}
            for r in ctx["revenues"]
        ],
    }


def _tab_depenses(ctx, fin, request):
    return {
        "currency": ctx["financial_overview"]["currency"],
        "stats": _money_dict(ctx["expense_stats"]),
        "expenses": [
            {"id": e.pk, "expense_date": _d(e.expense_date), "created_at": _d(e.created_at), "title": e.title,
             "description": Truncator(strip_tags(e.description or "")).chars(90), "reference": e.reference or "",
             "is_direct_cost": e.is_direct_cost, "is_labor_cost": e.is_labor_cost,
             "status": e.status, "status_label": _display(e, "status"),
             "approval_state": e.approval_state, "approval_state_label": _display(e, "approval_state"),
             "amount": _m(e.amount), "currency": e.currency or "XOF", "can_be_edited": bool(e.can_be_edited)}
            for e in ctx["all_expenses"]
        ],
    }


def _tab_facturation_client(ctx, fin, request):
    all_invoices = ctx["all_project_invoices"]
    return {
        "currency": ctx["financial_overview"]["currency"],
        "invoice_summary": _money_dict(ctx["invoice_summary"]),
        "invoices": [
            {"id": inv.pk, "number": inv.number or "", "billing_mode_label": _display(inv, "billing_mode"),
             "client": inv.client.name if inv.client_id else "", "issue_date": _d(inv.issue_date),
             "due_date": _d(inv.due_date), "total_ttc": _m(inv.total_ttc), "paid_amount": _m(inv.paid_amount),
             "currency": inv.currency or "", "status": inv.status, "status_label": _display(inv, "status")}
            for inv in ctx["project_invoices"]
        ],
        "invoices_total": len(all_invoices) if isinstance(all_invoices, list) else all_invoices.count(),
        # Génération = écriture : ``invoice.create`` (comme l'outil copilote ``create_invoice``) ; onglet servi si ``fin``.
        "can_generate_invoice": bool(fin and _rbac(request, "invoice.create", ctx["project_obj"])),
        "billing": _money_dict(ctx["client_billing_summary"]),
        "revenues": [
            {"id": r.pk, "title": r.title, "notes": Truncator(r.notes or "").chars(90),
             "revenue_type_label": _display(r, "revenue_type"), "amount": _m(r.amount), "currency": r.currency or "XOF",
             "invoiced_amount": _m(r.invoiced_amount), "received_amount": _m(r.received_amount),
             "remaining_to_invoice": _m(r.remaining_to_invoice), "remaining_to_collect": _m(r.remaining_to_collect),
             "expected_date": _d(r.expected_date), "status": r.status, "status_label": _display(r, "status")}
            for r in ctx["all_revenues"]
        ],
    }


def _tab_equipes(ctx, fin, request):
    from project.services.project_member_permissions import can_manage_project_members

    project = ctx["project_obj"]
    members = list(ctx["members"])
    team_summary = list(ctx["team_summary"])
    allocations = [m.allocation_percent or 0 for m in members]
    # TJM individuels (BillingRate) : ``billing.view`` — même règle que l'API ``billing-rates`` (PR25).
    can_view_rates = bool(fin and _rbac(request, "billing.view", project))
    data = {
        # Mêmes droits que les vues Django ProjectMember* (ProjectMemberRightsMixin).
        "can_manage_members": can_manage_project_members(request.user, project),
        "members": [
            {"id": m.pk, "user_id": m.user_id, "name": _user(m.user), "team": m.team.name if m.team_id else "",
             "role": m.role or "", "allocation_percent": m.allocation_percent or 0, "is_primary": m.is_primary}
            for m in members
        ],
        "team_summary": [
            {"team_id": row["team__id"], "team": row["team__name"] or "", "members_count": row["members_count"],
             "primary_count": row["primary_count"] or 0}
            for row in team_summary
        ],
        "primary_total": sum(row["primary_count"] or 0 for row in team_summary),
        "allocation_average": round(sum(allocations) / len(allocations)) if allocations else 0,
        "timesheet_stats": _money_dict(ctx["timesheet_stats"]),
        "member_costs": None,
        # Droits financiers sans ``billing.view`` : la section TJM est masquée (pas même la synthèse,
        # qui révèle le TJM d'un membre seul).
        "member_costs_restricted": bool(fin and not can_view_rates),
    }
    if can_view_rates:
        # Coûts RH calculés par la vue (BillingRate / TJM × allocation) — TJM : ``billing.view`` requis
        # (comme l'API ``billing-rates``) ; le repli historique TeamMembership.role ne suffit pas.
        data["member_costs"] = {
            "currency": ctx["financial_overview"]["currency"],
            "summary": _money_dict(ctx["member_cost_summary"]),
            "rows": [
                {"member_id": row["member"].pk, "name": _user(row["user"]),
                 "allocation_percent": _m(row["allocation_percent"]),
                 "daily_cost": _m(row["daily_cost"]), "daily_sale": _m(row["daily_sale"]),
                 "allocated_daily_cost": _m(row["allocated_daily_cost"]),
                 "allocated_monthly_cost": _m(row["allocated_monthly_cost"]),
                 "allocated_project_cost": _m(row["allocated_project_cost"]),
                 "allocated_project_sale": _m(row["allocated_project_sale"])}
                for row in ctx["member_cost_rows"]
            ],
        }
    return data


def _tab_evolution(ctx, fin, request):
    return {
        "summary": ctx["evolution_summary"],
        "activities": [
            {"id": log.pk, "title": log.title or "Activité projet", "description": log.description or "",
             "created_at": _d(log.created_at), "actor": _user(log.actor)}
            for log in ctx["activity_logs"]
        ],
        "pull_requests": [
            {"id": pr.pk, "title": pr.title, "repository": pr.repository or "", "branch_name": pr.branch_name or "",
             "author": _user(pr.author), "status_label": _display(pr, "status"), "url": pr.url or ""}
            for pr in ctx["all_pull_requests"]
        ],
        "risks": [
            {"id": r.pk, "title": r.title, "severity": r.severity, "severity_label": _display(r, "severity"),
             "status_label": _display(r, "status"), "owner": _user(r.owner)}
            for r in ctx["all_risks"].select_related("owner")
        ],
        "insights": [
            {"id": i.pk, "title": i.title, "summary": i.summary, "task": str(i.task) if i.task_id else "",
             "task_id": i.task_id, "sprint": str(i.sprint) if i.sprint_id else "",
             "insight_type_label": _display(i, "insight_type"), "severity": i.severity,
             "severity_label": _display(i, "severity"), "is_dismissed": i.is_dismissed}
            for i in ctx["all_ai_insights"]
        ],
    }


def _board(columns, tasks) -> list[dict]:
    """
    Board Kanban du projet (``BoardColumn`` : section « Board Kanban » de _taches.html) :
    tâches regroupées par ``mapped_status`` ; ``wip_limit`` 0 = illimitée (help_text du modèle).
    """
    by_status: dict[str, list[int]] = {}
    for task in tasks:
        by_status.setdefault(task.status, []).append(task.pk)
    board = []
    for col in columns:
        ids = by_status.get(col.mapped_status, []) if col.mapped_status else []
        limit = col.wip_limit or None
        board.append({
            "id": col.pk, "name": col.name, "mapped_status": col.mapped_status or "",
            "color": col.color or "", "wip_limit": limit, "is_done_column": col.is_done_column,
            "count": len(ids), "over_wip": bool(limit and len(ids) > limit), "task_ids": ids,
        })
    return board


def _tab_taches(ctx, fin, request):
    tasks = list(ctx["all_tasks"].select_related("assignee", "backlog_item", "parent"))
    columns = sorted(ctx["board_columns"], key=lambda c: (c.position, c.pk))
    return {
        "stats": _money_dict(ctx["task_stats"]),
        "has_board": bool(columns),
        "board": _board(columns, tasks),
        "tasks": [
            {"id": t.pk, "title": t.title, "backlog_item": str(t.backlog_item) if t.backlog_item_id else "",
             "parent": str(t.parent) if t.parent_id else "", "parent_id": t.parent_id,
             "status": t.status, "status_label": _display(t, "status"),
             "priority": t.priority, "priority_label": _display(t, "priority"),
             "assignee": _user(t.assignee), "assignee_id": t.assignee_id,
             "estimate_hours": _m(t.estimate_hours), "spent_hours": _m(t.spent_hours), "due_date": _d(t.due_date)}
            for t in tasks
        ],
        "dependencies": _deps(ctx),
    }


def _tab_kpi_roi(ctx, fin, request):
    roi = ctx["roi_summary"]
    data = {
        "kpi_summary": ctx["kpi_summary"],
        "roi_summary": {"count": roi["count"], "global_roi_percent": _m(roi["global_roi_percent"]),
                        "total_cost": _m(roi["total_cost"]) if fin else None,
                        "total_revenue": _m(roi["total_revenue"]) if fin else None},
        "kpis": [
            {"id": k.pk, "name": k.name, "module_name": k.module_name or "",
             "value": _m(k.value) if k.value is not None else None, "value_text": k.value_text or "", "unit": k.unit or ""}
            for k in ctx["project_kpis"]
        ],
        # Montants des modules : droits financiers uniquement (le ROI % reste visible).
        "module_rois": [
            {"id": r.pk, "module_name": r.module_name, "roi_percent": _m(r.roi_percent),
             "estimated_cost": _m(r.estimated_cost) if fin else None,
             "estimated_revenue": _m(r.estimated_revenue) if fin else None}
            for r in ctx["project_module_rois"]
        ],
        "sprint_finance": None,
        "feature_finance": None,
    }
    if fin:
        data["sprint_finance"] = _money_dict(ctx["sprint_financial_summary"])
        data["feature_finance"] = _money_dict(ctx["feature_financial_summary"])
    return data


def _document(item) -> dict:
    name = posixpath.basename(item.file.name) if item.file else "Document"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return {
        "id": item.pk, "name": name, "url": item.file.url if item.file else None, "ext": ext,
        "type_label": DOC_TYPES.get(ext, ext.upper() or "Fichier"), "has_text": bool(item.extracted_text),
        "status": item.status, "status_label": _display(item, "status"), "uploaded_by": _user(item.uploaded_by),
        "created_at": _d(item.created_at), "error_message": item.error_message or "",
    }


def _tab_documents(ctx, fin, request):
    return {"summary": ctx["import_summary"], "documents": [_document(i) for i in ctx["project_imports"]]}


def _tab_meetings(ctx, fin, request):
    # Même sélection que _meetings.html : ``object.meetings.all`` (15 premières).
    qs = ctx["project_obj"].meetings.all()
    return {
        "count": qs.count(),
        "meetings": [
            {"id": m.pk, "title": m.title, "scheduled_at": _d(m.scheduled_at),
             "meeting_type_label": _display(m, "meeting_type"), "status": m.status,
             "status_label": _display(m, "status"), "status_color": m.status_color,
             "action_items_count": m.action_items_count}
            for m in qs.annotate(action_items_count=Count("action_items"))[:15]
        ],
    }


TAB_BUILDERS = {
    "planification": _tab_planification,
    "budget_estimatif": _tab_budget_estimatif,
    "budget_previsionnel": _tab_budget_previsionnel,
    "facturation_client": _tab_facturation_client,
    "depenses": _tab_depenses,
    "equipes": _tab_equipes,
    "evolution": _tab_evolution,
    "taches": _tab_taches,
    "kpi_roi": _tab_kpi_roi,
    "documents": _tab_documents,
    "meetings": _tab_meetings,
}


def _mode(ctx) -> dict | None:
    """Partial méthodologie (project/modes/*.html) : phases, rapports terrain, lots, dossiers."""
    methodology = ctx["methodology"]
    M = dm.Project.Methodology
    if methodology == M.WATERFALL:
        return {"kind": "waterfall", "phases": [
            {"id": p.pk, "name": p.name, "description": Truncator(p.description or "").chars(120),
             "gate_required": p.gate_required, "status": p.status, "status_label": _display(p, "status"),
             "start_date": _d(p.start_date), "end_date": _d(p.end_date), "owner": _user(p.owner),
             "progress_percent": p.progress_percent or 0}
            for p in ctx["mode_phases"]
        ]}
    if methodology == M.FIELD:
        reports = []
        for r in ctx["mode_field_reports"]:
            photos = list(r.photos.all())
            reports.append({
                "id": r.pk, "report_date": _d(r.report_date), "location_name": r.location_name or "",
                "location": f"{r.location_lat}, {r.location_lng}" if r.location_lat and r.location_lng else "",
                "weather": r.weather or "", "weather_label": _display(r, "weather") if r.weather else "",
                "workforce_count": r.workforce_count or 0, "notes": Truncator(r.notes or "").chars(200),
                "incidents": Truncator(r.incidents or "").chars(160), "reporter": _user(r.reporter),
                "created_at": _d(r.created_at), "photos_count": len(photos),
                "photos": [{"id": ph.pk, "url": ph.image.url if ph.image else None, "caption": ph.caption or ""}
                           for ph in photos[:6]],
            })
        return {"kind": "field", "reports": reports}
    if methodology == M.REAL_ESTATE:
        lots = list(ctx["mode_lots"])
        groups: dict[str, dict] = {}
        for lot in lots:
            group = groups.setdefault(lot.status, {"status": lot.status, "label": _display(lot, "status"), "count": 0})
            group["count"] += 1
        return {"kind": "real_estate", "groups": list(groups.values()), "lots": [
            {"id": lot.pk, "lot_number": lot.lot_number, "floor": lot.floor or "", "surface_m2": _m(lot.surface_m2),
             "bedrooms": lot.bedrooms, "price": _m(lot.price) if lot.price else None, "currency": lot.currency or "",
             "status": lot.status, "status_label": _display(lot, "status"), "buyer_name": lot.buyer_name or ""}
            for lot in lots
        ]}
    if methodology == M.ADMINISTRATIVE:
        today = timezone.localdate()
        closed = {"APPROVED", "CLOSED", "REJECTED"}
        return {"kind": "administrative", "cases": [
            {"id": c.pk, "reference": c.reference, "title": c.title, "applicant": c.applicant or "",
             "document_type": c.document_type or "", "status": c.status, "status_label": _display(c, "status"),
             "deadline": _d(c.deadline), "sla_days": c.sla_days,
             "is_overdue": bool(c.deadline and c.deadline < today and c.status not in closed),
             "assignee": _user(c.assignee)}
            for c in ctx["mode_cases"]
        ]}
    return None


class ProjectDetailTabsView(APIView):
    """``GET projects/<pk>/detail-tabs/?tab=<clé>`` — fiche projet complète (contexte ProjectDetailView)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        from project.templatetags.devflow_extras import safe_html

        project = _scoped_project(request, pk)
        _view, response = _dispatch(request, project, _detail_view_class(), {"pk": project.pk})
        ctx = getattr(response, "context_data", None) or {}
        if "project_obj" not in ctx:
            raise NotFound()
        project = ctx["project_obj"]
        fin = bool(ctx["can_view_financials"])
        ov, task_stats, budget = ctx["financial_overview"], ctx["task_stats"], ctx["budget_obj"]
        members_count = ctx["members"].count()

        tabs = [{"key": t["key"], "label": TAB_LABELS.get(t["key"], t["label"]), "count": t["count"] or 0}
                for t in ctx["tabs"]]
        meetings_count = project.meetings.count()
        tabs += [
            {"key": "documents", "label": TAB_LABELS["documents"], "count": ctx["import_summary"]["count"]},
            {"key": "meetings", "label": TAB_LABELS["meetings"], "count": meetings_count},
        ]
        keys = {t["key"] for t in tabs}
        requested = request.query_params.get("tab") or "planification"
        active = requested if requested in keys else "planification"
        if active in FINANCIAL_TABS and not fin:  # défense en profondeur (déjà exclu de ``keys``)
            active = "planification"

        money = (lambda v: _m(v)) if fin else (lambda v: None)
        return Response({
            "project": {
                "id": project.pk, "name": project.name, "code": project.code or "",
                "category": project.category.name if project.category_id else "",
                "status": project.status, "status_label": _display(project, "status"),
                "priority": project.priority, "priority_label": _display(project, "priority"),
                "health_status": project.health_status, "health_status_label": _display(project, "health_status"),
                "methodology": project.methodology or "", "methodology_label": str(ctx["methodology_label"] or ""),
                "progress_percent": project.progress_percent or 0, "risk_score": project.risk_score or 0,
                "ai_risk_label": project.ai_risk_label or "",
                "description_html": str(safe_html(project.description)),
                "owner": _user(project.owner), "product_manager": _user(project.product_manager),
                "workspace": ctx["workspace_obj"].name, "workspace_id": project.workspace_id,
                "start_date": _d(project.start_date), "target_date": _d(project.target_date),
                "delivered_at": _d(project.delivered_at),
                "team": project.team.name if project.team_id else "", "team_id": project.team_id,
                "tech_stack": project.tech_stack or "",
                "labels": [{"id": pl.label_id, "name": pl.label.name, "color": pl.label.color or ""}
                           for pl in ctx["labels"]],
                "budget_id": budget.pk if fin and budget else None,
                "budget_status_label": _display(budget, "status") if fin and budget else "",
            },
            "can_view_financials": fin,
            "kpis": {
                "progress_percent": project.progress_percent or 0, "risk_score": project.risk_score or 0,
                "tasks_total": task_stats["total"], "members_count": members_count,
                "actual_cost": money(ov["actual_cost"]), "received_revenue": money(ov["received_revenue"]),
                "currency": ov["currency"],
            },
            "band": {
                "todo": task_stats["todo"], "in_progress": task_stats["in_progress"],
                "blocked": task_stats["blocked"], "overdue": task_stats["overdue"],
                "imports": ctx["import_summary"]["count"], "imports_completed": ctx["import_summary"]["completed"],
                "insights_total": ctx["ai_summary"]["total"], "insights_critical": ctx["ai_summary"]["critical"],
                "approved_budget": money(ov["approved_budget"]), "actual_cost": money(ov["actual_cost"]),
                "forecast_margin": money(ov["forecast_margin"]),
            },
            "mode": _mode(ctx),
            "tabs": tabs,
            "active_tab": active,
            "tab": {"key": active, **TAB_BUILDERS[active](ctx, fin, request)},
        })


# ─── IA financière (vues views_financial_ai) ────────────────────────────────
class _AIProjectView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [AIActionRateThrottle]
    parser_classes = [JSONParser, FormParser, MultiPartParser]


class ProjectAIForecastView(_AIProjectView):
    """``POST projects/<pk>/detail-tabs/ai-forecast/`` — prévision budgétaire IA (droits financiers)."""

    def post(self, request, pk):
        from project.views_financial_ai import ProjectBudgetForecastView

        project = _scoped_project(request, pk)
        _view, response = _dispatch(request, project, ProjectBudgetForecastView, {"project_id": project.pk})
        return _json_passthrough(response, "Accès aux données financières non autorisé.")


class ProjectAIRiskAnalysisView(_AIProjectView):
    """``POST projects/<pk>/detail-tabs/ai-risk-analysis/`` — analyse de risques IA (persiste les insights)."""

    def post(self, request, pk):
        from project.views_financial_ai import ProjectRiskAnalysisView

        project = _scoped_project(request, pk)
        _view, response = _dispatch(request, project, ProjectRiskAnalysisView, {"project_id": project.pk})
        return _json_passthrough(response, "Accès aux données financières non autorisé.")


class ProjectAIGenerationView(APIView):
    """
    Génération IA de la structure (roadmap, jalons, sprints, backlog, tâches) depuis la fiche :
    ``POST`` → ``ProjectAIProposalTriggerView`` en mode AJAX (proposition PENDING + Celery) ;
    ``GET``  → ``ProjectAIProposalStatusView`` (progression, sans throttle : polling).
    """

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get_throttles(self):
        throttles = super().get_throttles()
        if self.request.method == "POST":  # lancement IA payant ; le polling (GET) n'est pas limité
            throttles.append(AIActionRateThrottle())
        return throttles

    def get(self, request, pk):
        from project.views_ai_proposal import ProjectAIProposalStatusView

        project = _scoped_project(request, pk)
        _view, response = _dispatch(request, project, ProjectAIProposalStatusView, {"project_pk": project.pk})
        return _json_passthrough(response, "Accès non autorisé.")

    def post(self, request, pk):
        from project.views_ai_proposal import ProjectAIProposalTriggerView

        project = _scoped_project(request, pk)
        django_request = _prepare(request, project)
        django_request.META["HTTP_X_REQUESTED_WITH"] = "XMLHttpRequest"  # mode asynchrone de la vue
        django_request.__dict__.pop("headers", None)  # en-têtes mis en cache (cached_property)
        _view, response = _dispatch(request, project, ProjectAIProposalTriggerView, {"project_pk": project.pk})
        return _json_passthrough(response, "Accès non autorisé.")


# ─── Génération de facture depuis le projet ─────────────────────────────────
class ProjectInvoiceGenerateView(APIView):
    """
    ``GET``  → champs d'``InvoiceGenerateForm`` (même contrat que ``/api/v1/forms/``) ;
    ``POST`` → ``InvoiceGenerateFromProjectView`` (service ``generate_invoice_for_project``) :
    ``{id, messages, link}`` (201) ou erreurs du formulaire (400).
    Génération = écriture : ``can_view_financials`` + RBAC ``invoice.create`` (un chef de projet,
    lecture seule sur la finance, est refusé — même règle que l'outil copilote ``create_invoice``).
    """

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def _project(self, request, pk):
        project = _scoped_project(request, pk)
        if not _can_view_financials(request, project):
            raise PermissionDenied("Accès aux données financières non autorisé.")
        if not _rbac(request, "invoice.create", project):
            raise PermissionDenied("Génération de facture non autorisée pour votre rôle.")
        return project

    def get(self, request, pk):
        from project.api.form_bridge import describe_form
        from project.forms import InvoiceGenerateForm

        self._project(request, pk)
        schema = describe_form(InvoiceGenerateForm())
        for field in schema["fields"]:  # libellés du template project/invoice/generate.html
            field["label"] = INVOICE_FORM_LABELS.get(field["name"], field["label"])
        return Response(schema)

    def post(self, request, pk):
        from django.contrib import messages as dj_messages
        from django.contrib.messages import get_messages

        from project.api.form_bridge import form_errors
        from project.forms import InvoiceGenerateForm
        from project.views import InvoiceGenerateFromProjectView

        project = self._project(request, pk)
        form = InvoiceGenerateForm(request.data)
        if not form.is_valid():
            return Response(form_errors(form), status=status.HTTP_400_BAD_REQUEST)
        _view, response = _dispatch(request, project, InvoiceGenerateFromProjectView, {"project_pk": project.pk})
        notices = list(get_messages(request._request))
        if response.status_code in (301, 302):
            try:
                match = resolve(response["Location"].split("?", 1)[0])
            except Resolver404:
                match = None
            invoice_id = match.kwargs.get("pk") if match and match.url_name == "invoice_detail" else None
            if invoice_id:
                return Response(
                    {"id": invoice_id, "link": f"/m/invoice/{invoice_id}", "messages": [str(m) for m in notices]},
                    status=status.HTTP_201_CREATED,
                )
        errors = [str(m) for m in notices if m.level >= dj_messages.WARNING]
        return Response({"detail": " ".join(errors) or "Génération impossible."}, status=status.HTTP_400_BAD_REQUEST)


__all__ = [
    "ProjectDetailTabsView", "ProjectAIForecastView", "ProjectAIRiskAnalysisView",
    "ProjectAIGenerationView", "ProjectInvoiceGenerateView",
]
