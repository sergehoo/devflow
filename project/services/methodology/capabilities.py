"""
DevFlow — Capacités spécialisées de l'IA méthodologie (PR10-PR12).

Chaque fonction est branchable comme tool dans le copilote conversationnel
(PR16-19). Elles renvoient des structures JSON-friendly pour l'UI.

Workspace-safe : ne lisent que des données du ``project`` passé.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import timedelta
from typing import Optional

from django.utils import timezone

from project import models as dm
from project.services.ai.base import AIMessage
from project.services.ai.factory import get_ai_provider

logger = logging.getLogger(__name__)


def _provider():
    p = get_ai_provider()
    return p if (p and p.is_available()) else None


def _parse_json_tolerant(text: str) -> dict:
    if not text:
        return {}
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[-1]
        if t.startswith("json"):
            t = t[4:]
        t = t.rsplit("```", 1)[0]
    try:
        return json.loads(t.strip())
    except Exception:
        return {}


# ════════════════════════════════════════════════════════════════════════════
# CAPACITÉS SCRUM
# ════════════════════════════════════════════════════════════════════════════
def create_backlog_from_brief(project, brief: str, max_stories: int = 15) -> list[dict]:
    """
    À partir d'un brief textuel, génère un backlog de user stories au format
    INVEST. Retourne ``[{title, story, acceptance_criteria, story_points}, ...]``.
    """
    p = _provider()
    if not p:
        return []
    system = (
        "Tu es un Scrum Master expert. À partir d'un brief, génère un "
        f"backlog de {max_stories} user stories au format JSON STRICT :\n"
        '{"stories": [{"title": "...", "story": "As a..., I want..., so that...", '
        '"acceptance_criteria": ["...", "..."], "story_points": 1|2|3|5|8, '
        '"epic_hint": "..."}]}'
    )
    try:
        resp = p.generate(
            messages=[
                AIMessage(role="system", content=system),
                AIMessage(role="user", content=f"Brief : {brief[:4000]}"),
            ],
            temperature=0.4, max_tokens=2500, json_mode=True,
        )
        data = _parse_json_tolerant(resp.text or "")
        return data.get("stories", [])[:max_stories]
    except Exception as exc:
        logger.warning("create_backlog_from_brief failed: %s", exc)
        return []


def estimate_story_points(project, story_text: str) -> dict:
    """Propose des SP (Fibonacci) + justification pour une user story."""
    p = _provider()
    if not p:
        return {}
    system = (
        "Tu es un Scrum Master. Estime cette user story en story points "
        'Fibonacci (1, 2, 3, 5, 8, 13). Réponds en JSON :\n'
        '{"story_points": int, "justification": "...", '
        '"complexity": "low|medium|high|unknown", "uncertainty": "low|medium|high"}'
    )
    try:
        resp = p.generate(
            messages=[
                AIMessage(role="system", content=system),
                AIMessage(role="user", content=story_text[:2000]),
            ],
            temperature=0.2, max_tokens=400, json_mode=True,
        )
        return _parse_json_tolerant(resp.text or "")
    except Exception:
        return {}


def detect_blockers(project) -> list[dict]:
    """
    Analyse le sprint actif pour détecter les tâches qui semblent bloquées
    (en wip depuis > 5 jours, pas de mise à jour récente, statut BLOCKED).
    """
    blockers = []
    now = timezone.now()
    sprint = project.sprints.filter(status="ACTIVE").first()
    if not sprint:
        return blockers
    tasks = project.tasks.filter(
        sprint=sprint,
        status__in=["IN_PROGRESS", "REVIEW", "BLOCKED"],
    ).select_related("assignee")[:30]
    for t in tasks:
        age = (now - t.updated_at).days if t.updated_at else 0
        if t.status == "BLOCKED" or age >= 5:
            blockers.append({
                "task_id": t.pk,
                "title": t.title,
                "status": t.status,
                "assignee": str(t.assignee) if t.assignee else None,
                "days_idle": age,
                "reason": "Statut BLOCKED" if t.status == "BLOCKED"
                          else f"Pas de MAJ depuis {age} jours",
            })
    return blockers


def generate_retrospective(project, sprint=None) -> dict:
    """
    Génère un brouillon de rétro Sprint avec 3 colonnes basées sur les
    données objectives (vélocité, blocages, completion rate).
    """
    if sprint is None:
        sprint = (
            project.sprints
            .filter(status__in=["DONE", "REVIEW"])
            .order_by("-end_date")
            .first()
        )
    if not sprint:
        return {"error": "Aucun sprint terminé à rétrospecter."}

    completed = sprint.completed_story_points or 0
    total = sprint.total_story_points or 0
    completion = (completed / total * 100) if total else 0

    p = _provider()
    if not p:
        return {"went_well": [], "didnt_go_well": [], "actions": []}

    facts = (
        f"Sprint : {sprint.name}\n"
        f"Story points complétés : {completed}/{total} ({completion:.0f}%)\n"
        f"Durée : {(sprint.end_date - sprint.start_date).days if sprint.end_date and sprint.start_date else '—'} jours\n"
    )

    system = (
        "Tu es un Scrum Master. Génère un brouillon de rétrospective à "
        'partir des faits objectifs. Format JSON :\n'
        '{"went_well": ["...", "..."], "didnt_go_well": ["...", "..."], '
        '"actions": [{"title": "...", "owner_hint": "...", "priority": "high|medium|low"}]}'
    )
    try:
        resp = p.generate(
            messages=[
                AIMessage(role="system", content=system),
                AIMessage(role="user", content=facts),
            ],
            temperature=0.5, max_tokens=1200, json_mode=True,
        )
        return _parse_json_tolerant(resp.text or "")
    except Exception:
        return {}


# ════════════════════════════════════════════════════════════════════════════
# CAPACITÉS KANBAN
# ════════════════════════════════════════════════════════════════════════════
def analyze_flow(project) -> dict:
    """Analyse complète du flux Kanban : WIP, cycle time, goulots."""
    from project.services.methodology.kpis import compute_kpi

    wip = compute_kpi(project, "wip_count")
    cycle = compute_kpi(project, "cycle_time")
    lead = compute_kpi(project, "lead_time")
    throughput = compute_kpi(project, "throughput_weekly")

    # Identifie les colonnes WIP au-dessus de leur limite
    methodology = dm.Methodology.objects.filter(
        code=(project.methodology or "").lower()
    ).first()
    bottlenecks = []
    if methodology:
        for status in methodology.statuses.filter(category__in=["wip", "review"]):
            count = project.tasks.filter(status=status.code.upper()).count()
            if status.wip_limit and count > status.wip_limit:
                bottlenecks.append({
                    "column": status.name,
                    "count": count,
                    "wip_limit": status.wip_limit,
                    "excess": count - status.wip_limit,
                })

    return {
        "wip": wip,
        "cycle_time": cycle,
        "lead_time": lead,
        "throughput": throughput,
        "bottlenecks": bottlenecks,
    }


def recommend_wip_limits(project) -> list[dict]:
    """Recommande des WIP limits par colonne basé sur la taille équipe."""
    members = project.members.count() if hasattr(project, "members") else 3
    base_limit = max(2, int(members * 1.5))
    methodology = dm.Methodology.objects.filter(
        code=(project.methodology or "").lower()
    ).first()
    if not methodology:
        return []
    out = []
    for status in methodology.statuses.filter(category__in=["wip", "review"]):
        current = project.tasks.filter(status=status.code.upper()).count()
        out.append({
            "column": status.name,
            "current_count": current,
            "current_limit": status.wip_limit,
            "recommended_limit": base_limit,
            "rationale": f"≈ 1.5 × {members} membres",
        })
    return out


def identify_aging_tickets(project, days_threshold: int = 7) -> list[dict]:
    """Liste les tickets en cours qui n'ont pas bougé depuis > N jours."""
    cutoff = timezone.now() - timedelta(days=days_threshold)
    aging = (
        project.tasks
        .filter(status__in=["IN_PROGRESS", "REVIEW", "BLOCKED"])
        .filter(updated_at__lt=cutoff)
        .select_related("assignee")
        .order_by("updated_at")[:20]
    )
    return [
        {
            "task_id": t.pk, "title": t.title, "status": t.status,
            "assignee": str(t.assignee) if t.assignee else None,
            "days_idle": (timezone.now() - t.updated_at).days,
        }
        for t in aging
    ]


# ════════════════════════════════════════════════════════════════════════════
# CAPACITÉS WATERFALL
# ════════════════════════════════════════════════════════════════════════════
def generate_planning_from_charter(project, charter_text: str) -> dict:
    """À partir d'une note de cadrage, génère phases + tâches + dépendances."""
    p = _provider()
    if not p:
        return {}
    system = (
        "Tu es un PMP senior. À partir d'une note de cadrage, génère un "
        'plan projet structuré en JSON :\n'
        '{"phases": [{"name": "...", "duration_days": int, '
        '"deliverables": ["..."], "tasks": [{"title": "...", '
        '"duration_days": int, "predecessors": ["task_id_or_name"]}]}]}'
    )
    try:
        resp = p.generate(
            messages=[
                AIMessage(role="system", content=system),
                AIMessage(role="user", content=charter_text[:4000]),
            ],
            temperature=0.3, max_tokens=3000, json_mode=True,
        )
        return _parse_json_tolerant(resp.text or "")
    except Exception:
        return {}


def detect_delays(project) -> list[dict]:
    """Détecte les jalons/phases en retard."""
    delays = []
    now = timezone.now().date()
    if hasattr(project, "phases"):
        for phase in project.phases.all():
            if (phase.end_date and phase.end_date < now
                    and phase.status not in ["DONE"]):
                delays.append({
                    "type": "phase",
                    "name": phase.name,
                    "due_date": phase.end_date.isoformat(),
                    "days_late": (now - phase.end_date).days,
                    "progress": float(phase.progress_percent or 0),
                })
    if hasattr(project, "milestones"):
        for m in project.milestones.all():
            if (m.due_date and m.due_date < now
                    and m.status not in ["DONE"]):
                delays.append({
                    "type": "milestone",
                    "name": m.name,
                    "due_date": m.due_date.isoformat(),
                    "days_late": (now - m.due_date).days,
                    "progress": float(m.progress_percent or 0),
                })
    return sorted(delays, key=lambda d: -d["days_late"])


def compute_critical_path(project) -> dict:
    """
    Calcule un proxy de chemin critique : somme des durées des phases
    en cours / restantes ordonnées par position.
    Retourne le path + durée totale + bottleneck identifié.
    """
    if not hasattr(project, "phases"):
        return {"path": [], "total_days": 0}
    phases = project.phases.exclude(status="DONE").order_by("position")
    path = []
    total = 0
    for phase in phases:
        if phase.start_date and phase.end_date:
            d = (phase.end_date - phase.start_date).days
            total += d
            path.append({
                "name": phase.name,
                "duration_days": d,
                "progress": float(phase.progress_percent or 0),
            })
    longest = max(path, key=lambda p: p["duration_days"], default=None)
    return {
        "path": path,
        "total_days": total,
        "bottleneck": longest,
    }


def suggest_replanification(project, target_deadline: str) -> dict:
    """Propose une replanification pour respecter une nouvelle deadline."""
    p = _provider()
    if not p:
        return {}
    delays = detect_delays(project)
    critical = compute_critical_path(project)
    context = (
        f"Projet : {project.name}\n"
        f"Deadline cible : {target_deadline}\n"
        f"Retards actuels : {len(delays)}\n"
        f"Chemin critique : {critical.get('total_days', 0)} jours\n"
    )
    system = (
        "Tu es un Project Manager senior. Propose 3-5 actions concrètes pour "
        'respecter la nouvelle deadline. Format JSON :\n'
        '{"actions": [{"title": "...", "category": "scope|resources|timeline|quality", '
        '"impact_days": int, "owner_role": "...", "risk_if_not_done": "..."}], '
        '"feasibility": "high|medium|low", "explanation": "..."}'
    )
    try:
        resp = p.generate(
            messages=[
                AIMessage(role="system", content=system),
                AIMessage(role="user", content=context),
            ],
            temperature=0.4, max_tokens=1500, json_mode=True,
        )
        return _parse_json_tolerant(resp.text or "")
    except Exception:
        return {}
