"""
DevFlow — Registre des stratégies de calcul des KPIs méthodologiques.

Chaque ``MethodologyKPI.compute_strategy`` pointe vers une fonction de
ce module via le registre ``KPI_REGISTRY``. Permet d'ajouter de nouveaux
KPIs sans modifier les modèles ni les vues.

Chaque fonction prend ``(project, days_window=30)`` et retourne un dict :
    {
        "value": float | int | str,              # valeur principale
        "label": str,                            # label court
        "unit": str,                             # "story_points", "%", "days"
        "trend": "up" | "down" | "stable",       # tendance
        "delta": float,                          # variation période/N-1
        "series": [{"x": ..., "y": ...}, ...],   # série pour line/bar
        "extra": {...},                          # données chart-specific
    }
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Callable

from django.db.models import Avg, Count, F, Q, Sum
from django.utils import timezone

logger = logging.getLogger(__name__)


KPI_REGISTRY: dict[str, Callable] = {}


def register(strategy_code: str):
    """Décorateur pour enregistrer une stratégie de calcul KPI."""
    def _wrap(fn):
        KPI_REGISTRY[strategy_code] = fn
        return fn
    return _wrap


def _empty(value=0, **extra) -> dict:
    return {
        "value": value, "label": "—", "unit": "",
        "trend": "stable", "delta": 0, "series": [], "extra": extra,
    }


# ════════════════════════════════════════════════════════════════════════════
# KPIs Scrum
# ════════════════════════════════════════════════════════════════════════════
@register("velocity")
def velocity(project, days_window: int = 90) -> dict:
    """Moyenne de story points complétés par sprint (3 derniers)."""
    from project import models as dm
    try:
        sprints = (
            project.sprints
            .filter(status__in=["DONE", "REVIEW"])
            .order_by("-end_date")[:3]
        )
        if not sprints:
            return _empty(label="Vélocité — pas encore mesurée")
        values = [float(s.completed_story_points or 0) for s in sprints]
        avg = sum(values) / len(values) if values else 0
        return {
            "value": round(avg, 1),
            "label": f"Vélocité moyenne ({len(sprints)} sprints)",
            "unit": "story_points",
            "trend": "up" if len(values) >= 2 and values[0] >= values[-1] else "down",
            "delta": values[0] - values[-1] if len(values) >= 2 else 0,
            "series": [
                {"x": s.name, "y": float(s.completed_story_points or 0)}
                for s in reversed(sprints)
            ],
            "extra": {},
        }
    except Exception as exc:
        logger.warning("velocity KPI failed: %s", exc)
        return _empty()


@register("burndown_sprint")
def burndown_sprint(project, days_window: int = 30) -> dict:
    """Burndown du sprint actif (story points restants par jour)."""
    from project import models as dm
    try:
        sprint = project.sprints.filter(status="ACTIVE").first()
        if not sprint:
            return _empty(label="Aucun sprint actif")
        total_sp = float(sprint.total_story_points or 0)
        remaining = float(sprint.remaining_story_points or total_sp)
        # On simule une ligne idéale + une ligne réelle (à enrichir avec daily logs)
        days = max(1, (sprint.end_date - sprint.start_date).days if sprint.end_date and sprint.start_date else 10)
        ideal_burn = [total_sp - (total_sp / days) * d for d in range(days + 1)]
        return {
            "value": remaining,
            "label": f"Burndown — {sprint.name}",
            "unit": "story_points",
            "trend": "down" if remaining < total_sp else "stable",
            "delta": remaining - total_sp,
            "series": [{"x": f"J{d}", "y": round(v, 1)} for d, v in enumerate(ideal_burn)],
            "extra": {"total": total_sp, "remaining": remaining},
        }
    except Exception:
        return _empty()


@register("sprint_success_rate")
def sprint_success_rate(project, days_window: int = 90) -> dict:
    """% de sprints terminés avec ≥ 85% des story points complétés."""
    try:
        sprints = project.sprints.filter(status__in=["DONE", "REVIEW"])[:10]
        if not sprints:
            return _empty(label="Pas de sprint terminé")
        success = 0
        for s in sprints:
            total = float(s.total_story_points or 0)
            done = float(s.completed_story_points or 0)
            if total > 0 and done / total >= 0.85:
                success += 1
        rate = (success / len(sprints)) * 100
        return {
            "value": round(rate, 1), "label": "Taux de succès sprint",
            "unit": "%", "trend": "up" if rate >= 75 else "down",
            "delta": 0,
            "series": [], "extra": {"success": success, "total": len(sprints)},
        }
    except Exception:
        return _empty()


@register("story_completion")
def story_completion(project, days_window: int = 90) -> dict:
    """Nombre de stories complétées sur les N derniers jours."""
    try:
        cutoff = timezone.now() - timedelta(days=days_window)
        items = project.backlog_items.filter(
            item_type__in=["STORY", "EPIC", "FEATURE"],
            updated_at__gte=cutoff,
        )
        done = items.filter(status__in=["DONE", "CLOSED"]).count()
        return {
            "value": done, "label": f"Stories complétées ({days_window}j)",
            "unit": "stories", "trend": "stable", "delta": 0,
            "series": [], "extra": {"total": items.count()},
        }
    except Exception:
        return _empty()


@register("team_capacity")
def team_capacity(project, days_window: int = 30) -> dict:
    """Capacité estimée de l'équipe (membres × jours dispo)."""
    try:
        members_count = project.members.count() if hasattr(project, "members") else 0
        return {
            "value": members_count * 20,  # 20 jours/mois × membres (simpliste)
            "label": "Capacité équipe (jours/mois)",
            "unit": "jours", "trend": "stable", "delta": 0,
            "series": [], "extra": {"members": members_count},
        }
    except Exception:
        return _empty()


# ════════════════════════════════════════════════════════════════════════════
# KPIs Kanban
# ════════════════════════════════════════════════════════════════════════════
@register("wip_count")
def wip_count(project, days_window: int = 30) -> dict:
    """Nombre de tâches en cours (statut WIP)."""
    try:
        in_progress = project.tasks.filter(status="IN_PROGRESS").count()
        review = project.tasks.filter(status="REVIEW").count()
        wip = in_progress + review
        return {
            "value": wip, "label": "Work In Progress",
            "unit": "tickets", "trend": "stable", "delta": 0,
            "series": [], "extra": {"in_progress": in_progress, "review": review},
        }
    except Exception:
        return _empty()


@register("cycle_time")
def cycle_time(project, days_window: int = 30) -> dict:
    """Cycle time moyen (jours entre IN_PROGRESS et DONE)."""
    try:
        cutoff = timezone.now() - timedelta(days=days_window)
        done_tasks = project.tasks.filter(
            status="DONE", updated_at__gte=cutoff,
        )
        if not done_tasks.exists():
            return _empty(label="Pas de tâche terminée")
        # Approx : (updated_at - created_at) — à raffiner avec historique de statut
        durations = []
        for t in done_tasks[:50]:
            if t.updated_at and t.created_at:
                d = (t.updated_at - t.created_at).days
                if d >= 0:
                    durations.append(d)
        avg = sum(durations) / len(durations) if durations else 0
        return {
            "value": round(avg, 1), "label": "Cycle time moyen",
            "unit": "jours", "trend": "down" if avg < 7 else "up",
            "delta": 0,
            "series": [{"x": f"#{i}", "y": d} for i, d in enumerate(durations[:30])],
            "extra": {"samples": len(durations)},
        }
    except Exception:
        return _empty()


@register("lead_time")
def lead_time(project, days_window: int = 30) -> dict:
    """Lead time moyen (jours entre création et DONE)."""
    return cycle_time(project, days_window)  # approximation identique


@register("throughput_weekly")
def throughput_weekly(project, days_window: int = 56) -> dict:
    """Tâches DONE par semaine sur les 8 dernières semaines."""
    try:
        weeks = []
        now = timezone.now()
        for w in range(8):
            start = now - timedelta(days=(w + 1) * 7)
            end = now - timedelta(days=w * 7)
            count = project.tasks.filter(
                status="DONE",
                updated_at__gte=start, updated_at__lt=end,
            ).count()
            weeks.append({"x": f"S-{w}", "y": count})
        weeks.reverse()
        avg = sum(w["y"] for w in weeks) / len(weeks) if weeks else 0
        return {
            "value": round(avg, 1), "label": "Throughput moyen / semaine",
            "unit": "tickets", "trend": "stable", "delta": 0,
            "series": weeks, "extra": {},
        }
    except Exception:
        return _empty()


@register("cumulative_flow")
def cumulative_flow(project, days_window: int = 30) -> dict:
    """Cumulative Flow Diagram (compte de tickets par statut sur N jours)."""
    try:
        statuses = ["TODO", "IN_PROGRESS", "REVIEW", "DONE", "BLOCKED"]
        result = {s: project.tasks.filter(status=s).count() for s in statuses}
        return {
            "value": sum(result.values()), "label": "CFD — Distribution actuelle",
            "unit": "tickets", "trend": "stable", "delta": 0,
            "series": [{"x": s, "y": v} for s, v in result.items()],
            "extra": result,
        }
    except Exception:
        return _empty()


# ════════════════════════════════════════════════════════════════════════════
# KPIs Waterfall
# ════════════════════════════════════════════════════════════════════════════
@register("advancement_global")
def advancement_global(project, days_window: int = 30) -> dict:
    """% d'avancement global (moyenne pondérée des phases)."""
    try:
        phases = project.phases.all() if hasattr(project, "phases") else []
        if not phases:
            return {
                "value": float(project.progress_percent or 0),
                "label": "% Avancement global",
                "unit": "%", "trend": "up", "delta": 0,
                "series": [], "extra": {},
            }
        total_pct = sum(float(p.progress_percent or 0) for p in phases) / len(phases)
        return {
            "value": round(total_pct, 1),
            "label": "% Avancement (moyenne phases)",
            "unit": "%", "trend": "up", "delta": 0,
            "series": [{"x": p.name, "y": float(p.progress_percent or 0)} for p in phases],
            "extra": {"phases_count": len(phases)},
        }
    except Exception:
        return _empty()


@register("schedule_adherence")
def schedule_adherence(project, days_window: int = 30) -> dict:
    """% de jalons respectés (livrés à temps)."""
    try:
        if not hasattr(project, "milestones"):
            return _empty()
        milestones = project.milestones.all()
        if not milestones.exists():
            return _empty(label="Pas de jalon défini")
        done = milestones.filter(status="DONE").count()
        missed = milestones.filter(status="MISSED").count()
        total_passed = done + missed
        if total_passed == 0:
            return _empty(label="Aucun jalon échu")
        rate = (done / total_passed) * 100
        return {
            "value": round(rate, 1), "label": "Respect du planning",
            "unit": "%", "trend": "up" if rate >= 80 else "down", "delta": 0,
            "series": [], "extra": {"done": done, "missed": missed},
        }
    except Exception:
        return _empty()


@register("budget_consumption")
def budget_consumption(project, days_window: int = 30) -> dict:
    """% du budget consommé."""
    try:
        budget = getattr(project, "budget", None) or 0
        if not budget:
            return _empty(label="Pas de budget défini")
        # Approx : si Project a une property computed_eac
        spent = float(getattr(project, "actual_cost", None) or 0)
        ratio = (spent / float(budget)) * 100 if budget else 0
        return {
            "value": round(ratio, 1), "label": "Budget consommé",
            "unit": "%", "trend": "down" if ratio > 80 else "up",
            "delta": 0,
            "series": [], "extra": {"budget": float(budget), "spent": spent},
        }
    except Exception:
        return _empty()


@register("critical_path_length")
def critical_path_length(project, days_window: int = 30) -> dict:
    """Longueur estimée du chemin critique (en jours)."""
    try:
        phases = project.phases.all() if hasattr(project, "phases") else []
        total = 0
        for p in phases:
            if p.end_date and p.start_date:
                total += (p.end_date - p.start_date).days
        return {
            "value": total, "label": "Chemin critique",
            "unit": "jours", "trend": "stable", "delta": 0,
            "series": [], "extra": {},
        }
    except Exception:
        return _empty()


@register("phase_progress")
def phase_progress(project, days_window: int = 30) -> dict:
    """Avancement par phase Waterfall."""
    try:
        phases = project.phases.all() if hasattr(project, "phases") else []
        return {
            "value": len(phases), "label": "Avancement par phase",
            "unit": "phases", "trend": "stable", "delta": 0,
            "series": [
                {"x": p.name, "y": float(p.progress_percent or 0)}
                for p in phases
            ],
            "extra": {},
        }
    except Exception:
        return _empty()


@register("gantt_data")
def gantt_data(project, days_window: int = 30) -> dict:
    """Données pour rendre un Gantt simple."""
    try:
        phases = project.phases.all() if hasattr(project, "phases") else []
        bars = []
        for p in phases:
            if p.start_date and p.end_date:
                bars.append({
                    "name": p.name,
                    "start": p.start_date.isoformat(),
                    "end": p.end_date.isoformat(),
                    "progress": float(p.progress_percent or 0),
                })
        return {
            "value": len(bars), "label": "Diagramme de Gantt",
            "unit": "tâches", "trend": "stable", "delta": 0,
            "series": [], "extra": {"bars": bars},
        }
    except Exception:
        return _empty()


def compute_kpi(project, strategy_code: str, **kwargs) -> dict:
    """
    Point d'entrée unique pour calculer un KPI.

    Si la stratégie n'est pas enregistrée, retourne un dict 'unknown'
    (best-effort, n'explose jamais).
    """
    fn = KPI_REGISTRY.get(strategy_code)
    if not fn:
        return {
            "value": "—", "label": f"KPI inconnu : {strategy_code}",
            "unit": "", "trend": "stable", "delta": 0,
            "series": [], "extra": {},
        }
    try:
        return fn(project, **kwargs)
    except Exception as exc:
        logger.warning("KPI %s computation failed: %s", strategy_code, exc)
        return _empty(label=f"Erreur calcul {strategy_code}")
