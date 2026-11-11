"""
Suivi Pôle Développement : vue consolidée, indicateurs, synthèse et exports.

Rien n'est stocké ici. Chaque ligne est recalculée à partir des données
existantes : projets et tâches (porteurs, dates, avancement, statut), journal
d'activité et tâches terminées (actions menées), tâches ouvertes (actions à
venir), risques ouverts et décisions en attente (alertes / décisions).

Le périmètre (``board_scope``) est le seul point d'entrée des droits : la vue,
les indicateurs et tous les exports partent des mêmes lignes filtrées.
"""

from __future__ import annotations

import io
import math
from collections import Counter, defaultdict
from datetime import date, timedelta
from html import escape

from django.db.models import Q
from django.utils import timezone

from project import models as dm
from project.services.rbac import rbac_workspace_ids
from project.services.tracking_import import (
    ALERT_LABELS, CONTAINER_CATEGORY, PROJECTS, SOURCE, STATUS_LABELS, TASKS, key,
)

# Statuts DevFlow → vocabulaire du suivi (4 statuts).
PROJECT_STATUS_KEY = {
    "PLANNED": "en_cours", "IN_PROGRESS": "en_cours", "IN_DELIVERY": "en_cours", "DELAYED": "en_cours",
    "BLOCKED": "suspendu", "ON_HOLD": "suspendu", "DONE": "realise", "CANCELLED": "annule",
}
TASK_STATUS_KEY = {
    "TODO": "en_cours", "IN_PROGRESS": "en_cours", "REVIEW": "en_cours",
    "BLOCKED": "suspendu", "EXPIRED": "suspendu", "DONE": "realise", "CANCELLED": "annule",
}
CLOSED = ("realise", "annule")
SEVERITY_LABELS = {"LOW": "Faible", "MEDIUM": "Moyenne", "HIGH": "Élevée", "CRITICAL": "Critique"}
SEVERITY_ORDER = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
DUE_SOON_DAYS = 7
STALE_DAYS = 14
PORTEUR_ROLE = "Porteur"


class TrackingFilterError(ValueError):
    """Paramètre de filtre invalide (réponse 400)."""


# ---------------------------------------------------------------------------
# Périmètre
# ---------------------------------------------------------------------------
def board_scope(user) -> dict:
    """
    ``full`` : espaces où l'utilisateur voit tous les projets (``project.view``).
    ``assigned`` : espaces où il ne voit que ses projets et ses tâches.
    Un rôle sans accès aux tâches internes (client) n'a aucun périmètre.
    """
    full = set(rbac_workspace_ids(user, "project.view"))
    assigned = set(rbac_workspace_ids(user, "task.view_assigned")) - full
    return {"full": full, "assigned": assigned}


def all_workspaces_scope() -> dict:
    """Périmètre technique (tâches planifiées) : tous les espaces, sans utilisateur."""
    return {"full": set(dm.Workspace.objects.values_list("id", flat=True)), "assigned": set()}


def scope_label(scope) -> str:
    names = list(dm.Workspace.objects.filter(id__in=scope["full"] | scope["assigned"])
                 .order_by("name").values_list("id", "name"))
    parts = []
    full = [name for pk, name in names if pk in scope["full"]]
    mine = [name for pk, name in names if pk in scope["assigned"]]
    if full:
        parts.append("tous les projets de " + ", ".join(full))
    if mine:
        parts.append("vos projets et tâches de " + ", ".join(mine))
    return " ; ".join(parts) or "aucun"


def _name(user) -> str:
    return (user.get_full_name() or user.get_username()) if user else ""


def _scope_filters(scope, user):
    """Conditions « projets visibles » et « tâches visibles » du périmètre."""
    p_filter = Q(workspace_id__in=scope["full"])
    t_filter = Q(workspace_id__in=scope["full"])
    if scope["assigned"] and user is not None:
        p_filter |= Q(workspace_id__in=scope["assigned"]) & (
            Q(owner=user) | Q(product_manager=user) | Q(members__user=user))
        t_filter |= Q(workspace_id__in=scope["assigned"]) & (
            Q(assignee=user) | Q(assignments__user=user, assignments__is_active=True))
    return p_filter, t_filter


def visible_project(scope, user, pk):
    """Projet non archivé du périmètre de l'utilisateur, sinon ``None``."""
    p_filter, _t_filter = _scope_filters(scope, user)
    return (dm.Project.objects.filter(p_filter, pk=pk, is_archived=False)
            .select_related("workspace", "category", "owner").first())


# ---------------------------------------------------------------------------
# Lignes
# ---------------------------------------------------------------------------
def build_rows(scope, user=None, *, project_id=None, today=None) -> list[dict]:
    """Lignes « projet » puis « tâche / activité » visibles dans ``scope``."""
    today = today or timezone.localdate()
    if not scope["full"] and not scope["assigned"]:
        return []
    p_filter, t_filter = _scope_filters(scope, user)

    project_ids = dm.Project.objects.filter(p_filter, is_archived=False).exclude(category__code=CONTAINER_CATEGORY)
    activity_ids = dm.Task.objects.filter(
        t_filter, is_archived=False, parent__isnull=True,
        project__is_archived=False, project__category__code=CONTAINER_CATEGORY)
    if project_id is not None:
        project_ids = project_ids.filter(pk=project_id)
        activity_ids = activity_ids.filter(project_id=project_id)
    pids = set(project_ids.values_list("id", flat=True))
    tids = set(activity_ids.values_list("id", flat=True))

    projects = list(dm.Project.objects.filter(id__in=pids).select_related("owner", "workspace")
                    .order_by("workspace__name", "name"))
    activities = list(dm.Task.objects.filter(id__in=tids).select_related("assignee", "project", "workspace")
                      .order_by("workspace__name", "id"))

    companies_p, companies_t = defaultdict(list), defaultdict(list)
    for pk, name in (dm.ProjectLabel.objects.filter(project_id__in=pids, label__kind=dm.Label.Kind.COMPANY)
                     .order_by("label__name").values_list("project_id", "label__name")):
        companies_p[pk].append(name)
    for pk, name in (dm.TaskLabel.objects.filter(task_id__in=tids, label__kind=dm.Label.Kind.COMPANY)
                     .order_by("label__name").values_list("task_id", "label__name")):
        companies_t[pk].append(name)

    people = defaultdict(lambda: {"PORTEUR": [], "INTERLOCUTEUR": []})
    for pid, tid, role, name in (dm.ProjectStakeholder.objects
                                 .filter(Q(project_id__in=pids, task__isnull=True) | Q(task_id__in=tids))
                                 .order_by("id").values_list("project_id", "task_id", "role", "name")):
        people[("T", tid) if tid else ("P", pid)][role].append(name)

    members = defaultdict(list)
    for member in (dm.ProjectMember.objects.filter(project_id__in=pids, role__iexact=PORTEUR_ROLE)
                   .select_related("user").order_by("-is_primary", "id")):
        members[member.project_id].append(member.user)
    assignees = defaultdict(list)
    for link in (dm.TaskAssignment.objects.filter(task_id__in=tids, is_active=True)
                 .select_related("user").order_by("id")):
        assignees[link.task_id].append(link.user)

    done, upcoming = defaultdict(list), defaultdict(list)
    for pid, tid, text, title, created in (
            dm.ActivityLog.objects.filter(metadata__source=SOURCE, metadata__kind="action_done")
            .filter(Q(project_id__in=pids, task__isnull=True) | Q(task_id__in=tids))
            .order_by("id").values_list("project_id", "task_id", "description", "title", "created_at")):
        done[("T", tid) if tid else ("P", pid)].append(
            {"text": text or title, "date": created.date().isoformat(), "source": "history"})
    task_rows = (dm.Task.objects.filter(is_archived=False)
                 .filter(Q(project_id__in=pids, parent__isnull=True) | Q(parent_id__in=tids))
                 .order_by("due_date", "id")
                 .values_list("id", "project_id", "parent_id", "title", "status", "due_date", "completed_at"))
    for pk, pid, parent_id, title, status, due, completed in task_rows:
        ref = ("T", parent_id) if parent_id else ("P", pid)
        if status == dm.Task.Status.DONE:
            done[ref].append({"text": title, "date": completed.date().isoformat() if completed else None,
                              "source": "task", "id": pk})
        elif status != dm.Task.Status.CANCELLED:
            upcoming[ref].append({"id": pk, "text": title, "due": due.isoformat() if due else None,
                                  "status": status, "late": bool(due and due < today)})

    alerts = defaultdict(list)
    for pk, pid, tid, title, severity, category in (
            dm.Risk.objects.filter(is_archived=False, status__in=[dm.Risk.Status.OPEN, dm.Risk.Status.ESCALATED])
            .filter(Q(project_id__in=pids) | Q(task_id__in=tids))
            .order_by("id").values_list("id", "project_id", "task_id", "title", "severity", "category")):
        alerts[("T", tid) if tid in tids else ("P", pid)].append({
            "id": pk, "type": "risk", "kind": category, "kind_label": ALERT_LABELS.get(category, "Alerte"),
            "severity": severity, "severity_label": SEVERITY_LABELS.get(severity, severity), "text": title})
    through = dm.MeetingDecision.projects.through
    for pid, pk, title, tid in (
            through.objects.filter(meetingdecision__status=dm.MeetingDecision.Status.PENDING,
                                   meetingdecision__is_archived=False)
            .filter(Q(project_id__in=pids) | Q(meetingdecision__task_id__in=tids))
            .order_by("meetingdecision_id")
            .values_list("project_id", "meetingdecision_id", "meetingdecision__title", "meetingdecision__task_id")):
        alerts[("T", tid) if tid in tids else ("P", pid)].append({
            "id": pk, "type": "decision", "kind": "DECISION", "kind_label": ALERT_LABELS["DECISION"],
            "severity": None, "severity_label": "", "text": title})

    def people_of(ref, users):
        owners, seen = [], set()
        for user_obj in users:
            if user_obj and user_obj.pk not in seen:
                seen.add(user_obj.pk)
                owners.append({"name": _name(user_obj), "user_id": user_obj.pk})
        known = {key(o["name"]) for o in owners}
        for name in people[ref]["PORTEUR"]:  # porteurs sans compte DevFlow
            if key(name) not in known:
                known.add(key(name))
                owners.append({"name": name, "user_id": None})
        return owners, list(people[ref]["INTERLOCUTEUR"])

    def row(kind, obj, ref, *, title, status_key, start, end, owners, contacts, companies, project):
        done_items, seen = [], set()
        for item in done[ref]:  # une action importée puis créée en tâche n'apparaît qu'une fois
            if key(item["text"]) not in seen:
                seen.add(key(item["text"]))
                done_items.append(item)
        next_items, row_alerts = upcoming[ref], alerts[ref]
        is_open = status_key not in CLOSED
        late = bool(end and end < today and is_open)
        return {
            "id": f"{ref[0]}{obj.pk}", "kind": kind, "pk": obj.pk,
            "workspace": {"id": obj.workspace_id, "name": obj.workspace.name},
            "project": project, "title": title, "companies": companies,
            "owners": owners, "contacts": contacts,
            "progress": obj.progress_percent or 0,
            "status": obj.status, "status_label": obj.get_status_display(),
            "status_key": status_key, "sheet_status": STATUS_LABELS[status_key],
            "start": start.isoformat() if start else None, "end": end.isoformat() if end else None,
            "late": late, "days_late": (today - end).days if late else 0,
            "due_soon": bool(end and is_open and today <= end <= today + timedelta(days=DUE_SOON_DAYS)),
            "stale": bool(is_open and obj.updated_at and (timezone.now() - obj.updated_at).days >= STALE_DAYS),
            "done": done_items, "next": next_items, "alerts": row_alerts,
            "blocked": obj.status == "BLOCKED" or any(a["kind"] in ("BLOCKER", "DEPENDENCY") for a in row_alerts),
            "pending_decisions": sum(1 for a in row_alerts if a["type"] == "decision"),
            "updated_at": obj.updated_at.isoformat() if obj.updated_at else None,
        }

    rows = []
    for project in projects:
        ref = ("P", project.pk)
        owners, contacts = people_of(ref, [project.owner, *members[project.pk]])
        rows.append(row(
            "project", project, ref, title=project.name,
            status_key=PROJECT_STATUS_KEY.get(project.status, "en_cours"),
            start=project.start_date, end=project.target_date, owners=owners, contacts=contacts,
            companies=companies_p[project.pk], project={"id": project.pk, "name": project.name}))
    for task in activities:
        ref = ("T", task.pk)
        owners, contacts = people_of(ref, [task.assignee, *assignees[task.pk]])
        rows.append(row(
            "task", task, ref, title=task.title,
            status_key=TASK_STATUS_KEY.get(task.status, "en_cours"),
            start=task.start_date, end=task.due_date, owners=owners, contacts=contacts,
            companies=companies_t[task.pk], project={"id": task.project_id, "name": task.project.name}))
    return rows


# ---------------------------------------------------------------------------
# Filtres
# ---------------------------------------------------------------------------
FILTER_KEYS = ("section", "workspace", "company", "project", "owner", "status", "from", "to",
               "late", "alert", "progress_min", "progress_max", "q")
ALERT_FILTERS = ("DECISION", "DEPENDENCY", "BLOCKER", "RISK", "ALERT")


def _int(value, name, low=None, high=None):
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise TrackingFilterError(f"Paramètre « {name} » invalide.") from None
    if (low is not None and number < low) or (high is not None and number > high):
        raise TrackingFilterError(f"Paramètre « {name} » hors limites.")
    return number


def _day(value, name):
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        raise TrackingFilterError(f"Paramètre « {name} » invalide (AAAA-MM-JJ attendu).") from None


def parse_filters(params) -> dict:
    """Paramètres d'URL → filtres validés (``TrackingFilterError`` sinon)."""
    raw = {k: str(params.get(k) or "").strip() for k in FILTER_KEYS}
    filters: dict = {}
    if raw["section"]:
        if raw["section"] not in ("projects", "tasks"):
            raise TrackingFilterError("Paramètre « section » invalide.")
        filters["section"] = raw["section"]
    for name in ("workspace", "project"):
        if raw[name]:
            filters[name] = _int(raw[name], name, low=1)
    if raw["company"]:
        filters["company"] = raw["company"]
    if raw["owner"]:
        filters["owner"] = raw["owner"]
    if raw["status"]:
        values = [v for v in raw["status"].split(",") if v]
        if any(v not in STATUS_LABELS for v in values):
            raise TrackingFilterError("Paramètre « status » invalide.")
        filters["status"] = values
    for name in ("from", "to"):
        if raw[name]:
            filters[name] = _day(raw[name], name)
    if filters.get("from") and filters.get("to") and filters["to"] < filters["from"]:
        raise TrackingFilterError("La période se termine avant de commencer.")
    if raw["late"]:
        if raw["late"] not in ("1", "0"):
            raise TrackingFilterError("Paramètre « late » invalide.")
        filters["late"] = raw["late"] == "1"
    if raw["alert"]:
        if raw["alert"] not in ("1", "0", *ALERT_FILTERS):
            raise TrackingFilterError("Paramètre « alert » invalide.")
        filters["alert"] = raw["alert"]
    for name in ("progress_min", "progress_max"):
        if raw[name]:
            filters[name] = _int(raw[name], name, low=0, high=100)
    if raw["q"]:
        filters["q"] = raw["q"][:120]
    return filters


def _matches(row, f) -> bool:
    if f.get("section") and (row["kind"] == "project") != (f["section"] == "projects"):
        return False
    if f.get("workspace") and row["workspace"]["id"] != f["workspace"]:
        return False
    if f.get("project") and row["project"]["id"] != f["project"]:
        return False
    if f.get("company"):
        wanted = key(f["company"])
        if wanted == "aucune":
            if row["companies"]:
                return False
        elif wanted not in [key(c) for c in row["companies"]]:
            return False
    if f.get("owner"):
        owner = f["owner"]
        if owner.isdigit():
            if int(owner) not in [o["user_id"] for o in row["owners"]]:
                return False
        elif key(owner) not in [key(o["name"]) for o in row["owners"]]:
            return False
    if f.get("status") and row["status_key"] not in f["status"]:
        return False
    if f.get("from") or f.get("to"):
        days = [date.fromisoformat(d) for d in (row["start"], row["end"]) if d]
        if not days:
            return False
        if f.get("from") and max(days) < f["from"]:
            return False
        if f.get("to") and min(days) > f["to"]:
            return False
    if "late" in f and row["late"] != f["late"]:
        return False
    if f.get("alert"):
        if f["alert"] == "1" and not row["alerts"]:
            return False
        if f["alert"] == "0" and row["alerts"]:
            return False
        if f["alert"] in ALERT_FILTERS and f["alert"] not in [a["kind"] for a in row["alerts"]]:
            return False
    if "progress_min" in f and row["progress"] < f["progress_min"]:
        return False
    if "progress_max" in f and row["progress"] > f["progress_max"]:
        return False
    if f.get("q"):
        haystack = key(" ".join([
            row["title"], row["project"]["name"], *row["companies"], *[o["name"] for o in row["owners"]],
            *row["contacts"], *[i["text"] for i in row["done"]], *[i["text"] for i in row["next"]],
            *[a["text"] for a in row["alerts"]], row["sheet_status"]]))
        if any(token not in haystack for token in key(f["q"]).split()):
            return False
    return True


def apply_filters(rows, filters) -> list[dict]:
    return [row for row in rows if _matches(row, filters)] if filters else list(rows)


def describe_filters(filters, rows) -> list[str]:
    """Filtres actifs en clair (bandeau de l'écran et en-tête des exports)."""
    out = []
    if filters.get("section"):
        out.append("Bloc : " + ("projets" if filters["section"] == "projects" else "tâches / activités"))
    if filters.get("workspace"):
        name = next((r["workspace"]["name"] for r in rows if r["workspace"]["id"] == filters["workspace"]), None)
        out.append(f"Espace : {name or filters['workspace']}")
    if filters.get("company"):
        out.append(f"Entreprise : {filters['company']}")
    if filters.get("project"):
        name = next((r["project"]["name"] for r in rows if r["project"]["id"] == filters["project"]), None)
        out.append(f"Projet : {name or filters['project']}")
    if filters.get("owner"):
        owner = filters["owner"]
        if owner.isdigit():
            owner = next((o["name"] for r in rows for o in r["owners"] if o["user_id"] == int(owner)), owner)
        out.append(f"Porteur : {owner}")
    if filters.get("status"):
        out.append("Statut : " + ", ".join(STATUS_LABELS[s] for s in filters["status"]))
    if filters.get("from") or filters.get("to"):
        start = filters["from"].strftime("%d/%m/%Y") if filters.get("from") else "…"
        end = filters["to"].strftime("%d/%m/%Y") if filters.get("to") else "…"
        out.append(f"Période : {start} → {end}")
    if "late" in filters:
        out.append("En retard uniquement" if filters["late"] else "Sans retard")
    if filters.get("alert"):
        out.append({"1": "Avec alerte ou décision", "0": "Sans alerte"}.get(
            filters["alert"], "Alerte : " + ALERT_LABELS.get(filters["alert"], filters["alert"])))
    if "progress_min" in filters or "progress_max" in filters:
        out.append(f"Avancement : {filters.get('progress_min', 0)} % → {filters.get('progress_max', 100)} %")
    if filters.get("q"):
        out.append(f"Recherche : « {filters['q']} »")
    return out


def filter_options(rows) -> dict:
    """Valeurs proposées dans les filtres, limitées à ce que l'utilisateur voit."""
    companies = sorted({c for r in rows for c in r["companies"]}, key=key)
    owners = {}
    for r in rows:
        for o in r["owners"]:
            owners.setdefault(str(o["user_id"]) if o["user_id"] else o["name"], o["name"])
    projects = {r["project"]["id"]: r["project"]["name"] for r in rows}
    workspaces = {r["workspace"]["id"]: r["workspace"]["name"] for r in rows}
    return {
        "companies": companies,
        "owners": [{"value": v, "label": label} for v, label in sorted(owners.items(), key=lambda kv: key(kv[1]))],
        "projects": [{"value": pk, "label": name} for pk, name in sorted(projects.items(), key=lambda kv: key(kv[1]))],
        "workspaces": [{"value": pk, "label": name} for pk, name in sorted(workspaces.items(), key=lambda kv: kv[1])],
        "statuses": [{"value": k, "label": label} for k, label in STATUS_LABELS.items()],
        "alerts": [{"value": k, "label": ALERT_LABELS[k]} for k in ALERT_FILTERS],
    }


# ---------------------------------------------------------------------------
# Indicateurs et graphiques
# ---------------------------------------------------------------------------
PROGRESS_BUCKETS = (("0 %", 0, 0), ("1–25 %", 1, 25), ("26–50 %", 26, 50), ("51–75 %", 51, 75),
                    ("76–99 %", 76, 99), ("100 %", 100, 100))


def summarize(rows, today=None) -> dict:
    today = today or timezone.localdate()
    projects = [r for r in rows if r["kind"] == "project"]
    tasks = [r for r in rows if r["kind"] == "task"]
    live = [r for r in projects if r["status_key"] != "annule"]
    open_tasks = sum(len(r["next"]) for r in rows) + sum(1 for r in tasks if r["status_key"] not in CLOSED)
    late_tasks = sum(1 for r in rows for i in r["next"] if i["late"]) + sum(1 for r in tasks if r["late"])
    kpis = {
        "projects_total": len(projects),
        "projects_active": sum(1 for r in projects if r["status_key"] == "en_cours"),
        "projects_done": sum(1 for r in projects if r["status_key"] == "realise"),
        "projects_suspended": sum(1 for r in projects if r["status_key"] == "suspendu"),
        "projects_late": sum(1 for r in projects if r["late"]),
        "due_soon": sum(1 for r in rows if r["due_soon"]),
        "progress_avg": round(sum(r["progress"] for r in live) / len(live)) if live else 0,
        "projects_blocked": sum(1 for r in projects if r["blocked"]),
        "pending_decisions": sum(r["pending_decisions"] for r in rows),
        "tasks_open": open_tasks,
        "tasks_late": late_tasks,
        "activities_total": len(tasks),
    }

    by_company: Counter = Counter()
    for r in projects:
        for name in r["companies"] or ["Sans entreprise"]:
            by_company[name] += 1
    by_status = Counter(r["status_key"] for r in projects)
    progress = [{"label": label, "value": sum(1 for r in live if low <= r["progress"] <= high)}
                for label, low, high in PROGRESS_BUCKETS]
    deadlines: Counter = Counter()
    for r in rows:
        if r["end"] and r["status_key"] not in CLOSED:
            deadlines["En retard" if r["late"] else r["end"][:7]] += 1
    months = sorted(k for k in deadlines if k != "En retard")
    workload: dict[str, dict] = {}
    for r in rows:
        if r["status_key"] in CLOSED:
            continue
        for owner in r["owners"] or [{"name": "Non attribué"}]:
            entry = workload.setdefault(owner["name"], {"label": owner["name"], "projects": 0, "tasks": 0})
            entry["projects" if r["kind"] == "project" else "tasks"] += 1
    severities: Counter = Counter()
    for r in rows:
        for alert in r["alerts"]:
            severities["DECISION" if alert["type"] == "decision" else alert["severity"]] += 1
    charts = {
        "by_company": [{"label": k, "value": v} for k, v in by_company.most_common()],
        "by_status": [{"key": k, "label": STATUS_LABELS[k], "value": by_status.get(k, 0)} for k in STATUS_LABELS],
        "progress": progress,
        "deadlines": ([{"label": "En retard", "value": deadlines["En retard"]}] if deadlines.get("En retard") else [])
        + [{"label": f"{m[5:]}/{m[:4]}", "value": deadlines[m]} for m in months[:8]],
        "workload": sorted(workload.values(), key=lambda e: -(e["projects"] + e["tasks"]))[:12],
        "alerts": [{"key": k, "label": SEVERITY_LABELS[k], "value": severities.get(k, 0)} for k in SEVERITY_ORDER]
        + [{"key": "DECISION", "label": "Décision attendue", "value": severities.get("DECISION", 0)}],
    }
    return {"kpis": kpis, "charts": charts}


# ---------------------------------------------------------------------------
# Synthèse (faits réels, sans IA obligatoire)
# ---------------------------------------------------------------------------
def _titles(rows, limit=4) -> str:
    names = [r["title"] for r in rows[:limit]]
    return ", ".join(names) + (f" et {len(rows) - limit} autre(s)" if len(rows) > limit else "")


def build_brief(rows, today=None) -> dict:
    """Faits de pilotage tirés des lignes visibles : aucun état n'est inventé."""
    today = today or timezone.localdate()
    facts = []

    def fact(kind, text, items):
        facts.append({"kind": kind, "text": text, "rows": [r["id"] for r in items]})

    decisions = [r for r in rows if r["pending_decisions"]]
    if decisions:
        fact("decision", f"{len(decisions)} élément(s) attendent une décision : {_titles(decisions)}.", decisions)
    for r in [r for r in rows if r["blocked"] and r["status_key"] not in CLOSED][:5]:
        cause = next((a["text"] for a in r["alerts"] if a["kind"] in ("BLOCKER", "DEPENDENCY")), "")
        label = "Projet" if r["kind"] == "project" else "Activité"
        fact("blocker", f"{label} {r['title']} bloqué{'' if r['kind'] == 'project' else 'e'}"
             + (f" : {cause}." if cause else "."), [r])
    late = sorted([r for r in rows if r["late"]], key=lambda r: -r["days_late"])
    if late:
        worst = late[0]
        fact("late", f"{len(late)} échéance(s) dépassée(s) : {_titles(late)} "
             f"(retard maximal : {worst['days_late']} j sur {worst['title']}).", late)
    soon = [r for r in rows if r["due_soon"]]
    if soon:
        fact("deadline", f"{len(soon)} échéance(s) dans les {DUE_SOON_DAYS} prochains jours : {_titles(soon)}.", soon)
    risky = [r for r in rows if r["status_key"] not in CLOSED
             and any(a["severity"] in ("HIGH", "CRITICAL") for a in r["alerts"])]
    if risky:
        fact("risk", f"{len(risky)} élément(s) portent une alerte élevée ou critique : {_titles(risky)}.", risky)
    stale = [r for r in rows if r["stale"] and r["kind"] == "project"]
    if stale:
        fact("stale", f"{len(stale)} projet(s) sans mise à jour depuis {STALE_DAYS} jours : {_titles(stale)}.", stale)
    load = Counter()
    for r in rows:
        if r["status_key"] not in CLOSED:
            for owner in r["owners"]:
                load[owner["name"]] += 1
    if load:
        top = ", ".join(f"{name} ({count})" for name, count in load.most_common(3))
        fact("workload", f"Charge la plus élevée (éléments ouverts) : {top}.", [])
    week_end = today + timedelta(days=DUE_SOON_DAYS)
    priorities = sorted(
        [(i["due"], i["text"], r) for r in rows for i in r["next"] if i["due"] and i["due"] <= week_end.isoformat()],
        key=lambda t: t[0])
    if priorities:
        listing = " ; ".join(f"{text} ({r['title']}, {date.fromisoformat(due).strftime('%d/%m')})"
                             for due, text, r in priorities[:5])
        fact("priority", f"Priorités de la semaine : {listing}.", [r for _d, _t, r in priorities[:5]])
    if not facts:
        fact("ok", "Aucun retard, blocage ni décision en attente sur le périmètre affiché.", [])
    return {"generated_at": timezone.now().isoformat(), "facts": facts,
            "text": " ".join(f["text"] for f in facts), "source": "rules"}


def rewrite_brief_with_ai(brief) -> dict:
    """
    Reformulation facultative par l'IA DevFlow. L'IA ne reçoit que les faits
    calculés et ne peut rien y ajouter ; en cas d'échec le texte factuel reste.
    """
    from project.services.ai.base import AIMessage
    from project.services.ai.factory import get_ai_provider

    try:
        provider = get_ai_provider()
        if not provider.is_available():
            return brief
        response = provider.generate([
            AIMessage(role="system", content=(
                "Tu rédiges une note de pilotage pour une direction, en français, en 6 phrases au plus. "
                "Utilise exclusivement les faits fournis. N'ajoute aucun chiffre, nom, état, cause ou "
                "échéance absent de la liste. Pas de recommandation inventée.")),
            AIMessage(role="user", content="\n".join(f"- {f['text']}" for f in brief["facts"])),
        ], temperature=0.1, max_tokens=500)
        text = (response.text or "").strip()
    except Exception:  # fournisseur indisponible : la synthèse factuelle suffit
        return brief
    return {**brief, "text": text, "source": "ai"} if text else brief


# ---------------------------------------------------------------------------
# Export Excel « Direction » : même structure que le classeur historique
# ---------------------------------------------------------------------------
SHEET_NAME = "PROJET"
SECTION_TITLES = {PROJECTS: "SUIVI DES PROJETS - POLE DEVELOPPEMENT", TASKS: "SUIVI DES TACHES - POLE DEVELOPPEMENT"}
COMMON_HEADERS = ["INTERLOCUTEUR", "ACTIONS MENEES", "ACTIONS A VENIR", "ALERTE/DECISION", "Date de début",
                  "Date de fin prévue", "État d’avancement (%)", "STATUT"]
SECTION_HEADERS = {
    PROJECTS: ["ENTREPRISE", "PROJET", "PORTEUR DU PROJET", *COMMON_HEADERS],
    TASKS: ["ENTREPRISE", "TACHE / ACTIVITE", "PORTEUR", *COMMON_HEADERS],
}
COLUMN_WIDTHS = [23.3, 54.5, 24.7, 21.7, 62.7, 59.3, 34.3, 12.5, 14.8, 19.2, 12.0]
GENERATED_MENTION = "Généré automatiquement depuis DevFlow"
EMPTY_MENTION = "Aucun élément pour le périmètre et les filtres appliqués."
MAX_CELL_ITEMS = 60


def _bullets(items) -> str:
    texts = [i["text"] if isinstance(i, dict) else i for i in items]
    lines = [f"— {t}" for t in texts[:MAX_CELL_ITEMS]]
    if len(texts) > MAX_CELL_ITEMS:
        lines.append(f"(+ {len(texts) - MAX_CELL_ITEMS} autres dans DevFlow)")
    return "\n".join(lines)


def sheet_values(row) -> list:
    """Valeurs d'une ligne dans l'ordre des colonnes du classeur."""
    return [
        " / ".join(row["companies"]),
        row["title"],
        "\n".join(o["name"] for o in row["owners"]),
        "\n".join(row["contacts"]),
        _bullets(row["done"]),
        _bullets(row["next"]),
        "\n".join(a["text"] for a in row["alerts"]),
        date.fromisoformat(row["start"]) if row["start"] else None,
        date.fromisoformat(row["end"]) if row["end"] else None,
        row["progress"],
        row["sheet_status"],
    ]


def _row_height(values) -> float:
    lines = 1
    for value, width in zip(values, COLUMN_WIDTHS):
        if isinstance(value, str) and value:
            per_line = max(8, int(width * 1.15))
            lines = max(lines, sum(max(1, math.ceil(len(part) / per_line)) for part in value.split("\n")))
    return float(min(409, max(32, 15 * lines + 6)))


def export_xlsx(rows, *, user, scope_text, filter_lines, now=None) -> bytes:
    """
    Classeur de suivi au format utilisé par la Direction : feuille ``PROJET``
    avec le bloc projets puis le bloc tâches, mêmes colonnes et intitulés.
    """
    from openpyxl import Workbook
    from openpyxl.formatting.rule import CellIsRule, ColorScaleRule
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.worksheet.datavalidation import DataValidation

    now = timezone.localtime(now or timezone.now())
    font = "Aptos Narrow"
    thin = Side(style="thin", color="000000")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    title_fill = PatternFill("solid", start_color="E97132", end_color="E97132")
    header_fill = PatternFill("solid", start_color="FBE3D6", end_color="FBE3D6")
    status_fill = PatternFill("solid", start_color="F2CEEF", end_color="F2CEEF")
    wrap_left = Alignment(horizontal="left", vertical="center", wrap_text=True)
    wrap_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    last_col = "K"

    wb = Workbook()
    ws = wb.active
    ws.title = SHEET_NAME
    ws.sheet_view.zoomScale = 75
    for index, width in enumerate(COLUMN_WIDTHS):
        ws.column_dimensions["ABCDEFGHIJK"[index]].width = width

    filters_text = " · ".join(filter_lines) if filter_lines else "aucun"
    exporter = _name(user) or "DevFlow"
    ws.merge_cells(f"A1:{last_col}1")
    ws["A1"] = (f"{GENERATED_MENTION} — le {now:%d/%m/%Y} à {now:%H:%M} — exporté par {exporter}\n"
                f"Périmètre : {scope_text}\nFiltres : {filters_text}")
    ws["A1"].font = Font(name=font, size=10, italic=True, color="595959")
    ws["A1"].alignment = wrap_left
    ws.row_dimensions[1].height = 56.5

    status_ranges, progress_ranges = [], []
    cursor = 2
    first_header = None
    for section, kind in ((PROJECTS, "project"), (TASKS, "task")):
        section_rows = [r for r in rows if r["kind"] == kind]
        ws.merge_cells(f"A{cursor}:{last_col}{cursor}")
        cell = ws.cell(row=cursor, column=1, value=SECTION_TITLES[section])
        cell.font = Font(name=font, size=18, bold=True)
        cell.fill = title_fill
        cell.alignment = wrap_center
        ws.row_dimensions[cursor].height = 24
        header_row = cursor + 2
        first_header = first_header or header_row
        for col, label in enumerate(SECTION_HEADERS[section], start=1):
            cell = ws.cell(row=header_row, column=col, value=label)
            cell.font = Font(name=font, size=11, bold=True)
            cell.fill = header_fill
            cell.alignment = wrap_center
            cell.border = border
        ws.row_dimensions[header_row].height = 32
        cursor = header_row + 1
        first_data = cursor
        for item in section_rows:
            values = sheet_values(item)
            for col, value in enumerate(values, start=1):
                cell = ws.cell(row=cursor, column=col, value=value)
                cell.font = Font(name=font, size=11, bold=col in (1, 8, 9))
                cell.alignment = wrap_center if col >= 8 else wrap_left
                cell.border = border
                if col in (8, 9):
                    cell.number_format = "DD/MM/YYYY"
                elif col == 10:
                    cell.number_format = '0"%"'
                elif col == 11:
                    cell.fill = status_fill
            ws.row_dimensions[cursor].height = _row_height(values)
            cursor += 1
        if section_rows:
            status_ranges.append(f"K{first_data}:K{cursor - 1}")
            progress_ranges.append(f"J{first_data}:J{cursor - 1}")
            if section == PROJECTS:
                ws.auto_filter.ref = f"A{header_row}:{last_col}{cursor - 1}"
        else:
            ws.merge_cells(f"A{cursor}:{last_col}{cursor}")
            cell = ws.cell(row=cursor, column=1, value=EMPTY_MENTION)
            cell.font = Font(name=font, size=11, italic=True, color="595959")
            cell.alignment = wrap_left
            ws.row_dimensions[cursor].height = 24
            cursor += 1
        cursor += 1  # ligne vide entre les blocs

    if status_ranges:
        validation = DataValidation(type="list", formula1='"En cours,réalisé,suspendu,Annulé"', allow_blank=True)
        ws.add_data_validation(validation)
        for ref in status_ranges:
            validation.add(ref)
            for text, fill, color in (("suspendu", "FFEB9C", "9C5700"), ("réalisé", "C6EFCE", "006100"),
                                      ("Annulé", "FFC7CE", "9C0006"), ("En cours", "DDEBF7", "1F4E78")):
                ws.conditional_formatting.add(ref, CellIsRule(
                    operator="equal", formula=[f'"{text}"'],
                    fill=PatternFill("solid", start_color=fill, end_color=fill), font=Font(color=color)))
        for ref in progress_ranges:
            ws.conditional_formatting.add(ref, ColorScaleRule(
                start_type="num", start_value=0, start_color="FF0000", mid_type="num", mid_value=50,
                mid_color="FFFF00", end_type="num", end_value=100, end_color="00FF00"))

    ws.freeze_panes = ws.cell(row=first_header + 1, column=1)  # titres et en-tête figés
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A3
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = f"{first_header}:{first_header}"
    ws.oddFooter.left.text = GENERATED_MENTION
    ws.oddFooter.right.text = "Page &P / &N"

    statuses = wb.create_sheet("Statut")
    for index, label in enumerate(("En cours", "suspendu", "réalisé", "Annulé"), start=1):
        statuses.cell(row=index, column=1, value=label)
    info = wb.create_sheet("Informations")
    info.column_dimensions["A"].width = 26
    info.column_dimensions["B"].width = 110
    for index, (label, value) in enumerate((
            ("Origine", GENERATED_MENTION),
            ("Date de génération", f"{now:%d/%m/%Y %H:%M}"),
            ("Exporté par", exporter),
            ("Périmètre appliqué", scope_text),
            ("Filtres appliqués", "\n".join(filter_lines) if filter_lines else "aucun"),
            ("Projets", sum(1 for r in rows if r["kind"] == "project")),
            ("Tâches / activités", sum(1 for r in rows if r["kind"] == "task")),
    ), start=1):
        info.cell(row=index, column=1, value=label).font = Font(name=font, bold=True)
        info.cell(row=index, column=2, value=value).alignment = Alignment(wrap_text=True, vertical="top")

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Export PDF (rapports hebdomadaire, mensuel, Direction)
# ---------------------------------------------------------------------------
REPORTS = {
    "direction": {"title": "Rapport Direction", "days": None},
    "weekly": {"title": "Rapport hebdomadaire", "days": 7},
    "monthly": {"title": "Rapport mensuel", "days": 30},
}


def _fr(day) -> str:
    return date.fromisoformat(day).strftime("%d/%m/%Y") if day else "—"


def report_rows(rows, variant, today=None) -> list[dict]:
    """
    Rapport Direction : toutes les lignes. Rapports périodiques : uniquement les
    lignes actives sur la période (action réalisée, échéance, retard ou alerte).
    """
    days = REPORTS[variant]["days"]
    if days is None:
        return list(rows)
    today = today or timezone.localdate()
    since, until = (today - timedelta(days=days)).isoformat(), (today + timedelta(days=days)).isoformat()
    kept = []
    for row in rows:
        recent = [i for i in row["done"] if i["date"] and i["date"] >= since]
        ahead = [i for i in row["next"] if i["late"] or (i["due"] and i["due"] <= until)]
        active = row["status_key"] not in CLOSED
        if recent or ahead or (active and (row["late"] or row["alerts"] or (row["end"] and row["end"] <= until))):
            kept.append({**row, "done": recent, "next": ahead or (row["next"] if active else [])})
    return kept


def export_pdf(rows, *, user, scope_text, filter_lines, variant="direction", now=None) -> bytes:
    from weasyprint import HTML

    now = timezone.localtime(now or timezone.now())
    spec = REPORTS[variant]
    rows = report_rows(rows, variant, now.date())
    kpis = summarize(rows, now.date())["kpis"]
    brief = build_brief(rows, now.date())
    period = ""
    if spec["days"]:
        period = (f"Période : {(now.date() - timedelta(days=spec['days'])):%d/%m/%Y} → "
                  f"{(now.date() + timedelta(days=spec['days'])):%d/%m/%Y}")

    def items(values, limit=8):
        texts = [escape(v["text"]) for v in values[:limit]]
        more = f"<li class='more'>+ {len(values) - limit} autre(s)</li>" if len(values) > limit else ""
        return f"<ul>{''.join(f'<li>{t}</li>' for t in texts)}{more}</ul>" if texts else "—"

    def table(kind, title, column):
        section = [r for r in rows if r["kind"] == kind]
        if not section:
            return f"<h2>{title}</h2><p class='empty'>{EMPTY_MENTION}</p>"
        body = []
        for r in section:
            flags = "".join([
                f"<span class='tag late'>Retard {r['days_late']} j</span>" if r["late"] else "",
                "<span class='tag block'>Bloqué</span>" if r["blocked"] else ""])
            alerts = "".join(f"<li><b>{escape(a['kind_label'])}</b> — {escape(a['text'])}</li>" for a in r["alerts"])
            body.append(
                f"<tr><td>{escape(' / '.join(r['companies'])) or '—'}</td>"
                f"<td><b>{escape(r['title'])}</b>{flags}</td>"
                f"<td>{'<br>'.join(escape(o['name']) for o in r['owners']) or '—'}</td>"
                f"<td>{items(r['done'])}</td><td>{items(r['next'])}</td>"
                f"<td>{f'<ul>{alerts}</ul>' if alerts else '—'}</td>"
                f"<td class='c'>{_fr(r['start'])}<br>{_fr(r['end'])}</td>"
                f"<td class='c'>{r['progress']} %</td><td class='c s-{r['status_key']}'>{escape(r['sheet_status'])}</td></tr>")
        return (f"<h2>{title} ({len(section)})</h2><table><thead><tr><th>Entreprise</th><th>{column}</th>"
                "<th>Porteur</th><th>Actions menées</th><th>Actions à venir</th><th>Alertes / décisions</th>"
                "<th>Début<br>Échéance</th><th>Avanc.</th><th>Statut</th></tr></thead>"
                f"<tbody>{''.join(body)}</tbody></table>")

    cards = "".join(f"<div class='kpi'><b>{value}</b><span>{label}</span></div>" for label, value in (
        ("Projets actifs", kpis["projects_active"]), ("Réalisés", kpis["projects_done"]),
        ("Suspendus", kpis["projects_suspended"]), ("En retard", kpis["projects_late"]),
        ("Échéances proches", kpis["due_soon"]), ("Avancement moyen", f"{kpis['progress_avg']} %"),
        ("Bloqués", kpis["projects_blocked"]), ("Décisions en attente", kpis["pending_decisions"]),
        ("Tâches ouvertes", kpis["tasks_open"]), ("Tâches en retard", kpis["tasks_late"])))
    facts = "".join(f"<li>{escape(f['text'])}</li>" for f in brief["facts"])
    html = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><style>
@page {{ size: A4 landscape; margin: 12mm 10mm 14mm;
  @bottom-left {{ content: "{GENERATED_MENTION}"; font-size: 7.5pt; color: #777; }}
  @bottom-right {{ content: "Page " counter(page) " / " counter(pages); font-size: 7.5pt; color: #777; }} }}
body {{ font-family: Helvetica, Arial, sans-serif; font-size: 8pt; color: #1f2933; }}
h1 {{ font-size: 16pt; margin: 0 0 2pt; }} h2 {{ font-size: 11pt; margin: 12pt 0 4pt; color: #b4530f; }}
.meta {{ color: #555; margin: 0 0 8pt; }}
.kpis {{ display: flex; flex-wrap: wrap; gap: 5pt; margin: 6pt 0; }}
.kpi {{ border: 0.5pt solid #d6d9de; border-radius: 4pt; padding: 4pt 7pt; min-width: 68pt; }}
.kpi b {{ display: block; font-size: 12pt; }} .kpi span {{ color: #555; font-size: 7pt; }}
table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
th {{ background: #fbe3d6; text-align: left; }} th, td {{ border: 0.5pt solid #c9cdd3; padding: 3pt 4pt; vertical-align: top; }}
td.c, th.c {{ text-align: center; }} ul {{ margin: 0; padding-left: 9pt; }} li.more {{ list-style: none; color: #777; }}
tr {{ page-break-inside: avoid; }} thead {{ display: table-header-group; }}
.tag {{ display: inline-block; margin-left: 4pt; padding: 0 3pt; border-radius: 3pt; font-size: 6.5pt; }}
.late {{ background: #ffc7ce; color: #9c0006; }} .block {{ background: #ffeb9c; color: #9c5700; }}
.s-realise {{ background: #c6efce; }} .s-suspendu {{ background: #ffeb9c; }} .s-annule {{ background: #ffc7ce; }}
.empty {{ color: #777; font-style: italic; }}
col.w1 {{ width: 8%; }} col.w2 {{ width: 15%; }}
</style></head><body>
<h1>Suivi Pôle Développement — {spec['title']}</h1>
<p class="meta">{GENERATED_MENTION} le {now:%d/%m/%Y} à {now:%H:%M} par {escape(_name(user) or 'DevFlow')}<br>
Périmètre : {escape(scope_text)} · Filtres : {escape(' · '.join(filter_lines) if filter_lines else 'aucun')}
{('<br>' + period) if period else ''}</p>
<div class="kpis">{cards}</div>
<h2>Points d'attention</h2><ul>{facts}</ul>
{table('project', 'Projets', 'Projet')}
{table('task', 'Tâches / activités', 'Tâche / activité')}
</body></html>"""
    out = io.BytesIO()
    HTML(string=html).write_pdf(target=out)
    return out.getvalue()
