"""
Service IA : estimation d'effort pour une tâche ou un backlog.

Renvoie une estimation en heures + intervalle de confiance, basée sur le
contenu de la tâche (titre, description, type, priorité, points). Heuristique
de fallback : type-based si IA indisponible.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from project import models as dm
from project.services.ai.base import AIMessage
from project.services.ai.factory import get_ai_provider
from project.services.ai.openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)


@dataclass
class EffortEstimate:
    estimate_hours: float
    optimistic_hours: float
    pessimistic_hours: float
    confidence: str
    rationale: str
    used_provider: str = "heuristic"


# Heuristique : moyenne en heures par type de tâche
_BASE_HOURS_BY_TYPE = {
    "BUG": 4,
    "FEATURE": 16,
    "STORY": 12,
    "EPIC": 40,
    "TASK": 6,
    "CHORE": 3,
    "RESEARCH": 8,
}


class EffortEstimationService:
    @classmethod
    def estimate_task(cls, task: dm.Task, use_ai: bool = True) -> EffortEstimate:
        baseline = cls._heuristic(task)

        if use_ai:
            try:
                refined = cls._ai(task, baseline)
                if refined is not None:
                    return refined
            except Exception as exc:
                logger.warning("AI effort estimation failed for task %s: %s", task.pk, exc)

        return baseline

    # ---------------------------------------------------------------------
    @classmethod
    def _heuristic(cls, task: dm.Task) -> EffortEstimate:
        task_type = (getattr(task, "task_type", "") or "TASK").upper()
        base = _BASE_HOURS_BY_TYPE.get(task_type, 6)

        # Modulation par priorité
        priority = (getattr(task, "priority", "") or "MEDIUM").upper()
        priority_factor = {
            "LOW": 0.85,
            "MEDIUM": 1.0,
            "HIGH": 1.15,
            "CRITICAL": 1.3,
        }.get(priority, 1.0)

        # Modulation par story_points (si présent)
        sp = getattr(task, "story_points", None) or 0
        sp_factor = 1.0
        if sp:
            sp_factor = max(0.5, min(3.0, float(sp) / 5.0))

        estimate = base * priority_factor * sp_factor
        return EffortEstimate(
            estimate_hours=round(estimate, 1),
            optimistic_hours=round(estimate * 0.7, 1),
            pessimistic_hours=round(estimate * 1.5, 1),
            confidence="medium",
            rationale=(
                f"Heuristique : base {base}h ({task_type}) × {priority_factor} (priorité) "
                f"× {sp_factor:.2f} (story points)."
            ),
        )

    @classmethod
    def _ai(cls, task: dm.Task, baseline: EffortEstimate) -> EffortEstimate | None:
        provider = get_ai_provider()
        if not provider.is_available():
            return None

        payload = {
            "task": {
                "title": task.title,
                "description": (task.description or "")[:1500],
                "type": getattr(task, "task_type", "TASK"),
                "priority": getattr(task, "priority", "MEDIUM"),
                "story_points": getattr(task, "story_points", None),
                "tech_stack": getattr(task.project, "tech_stack", "") if task.project_id else "",
            },
            "baseline": {
                "estimate_hours": baseline.estimate_hours,
                "rationale": baseline.rationale,
            },
        }

        messages = [
            AIMessage(
                role="system",
                content=(
                    "Tu es un tech lead expert en estimation Agile. Donne une estimation en "
                    "heures pour cette tâche. Réponds STRICTEMENT en JSON : "
                    '{"estimate_hours": float, "optimistic_hours": float, '
                    '"pessimistic_hours": float, "confidence": "low|medium|high", '
                    '"rationale": "string en français"}.'
                ),
            ),
            AIMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
        ]

        response = provider.generate(
            messages=messages,
            temperature=0.2,
            json_mode=provider.supports_json_mode(),
        )

        if isinstance(provider, OpenAIProvider):
            data = OpenAIProvider.parse_json(response)
        else:
            try:
                data = json.loads(response.text)
            except Exception:
                return None

        if not data:
            return None

        try:
            return EffortEstimate(
                estimate_hours=float(data.get("estimate_hours") or baseline.estimate_hours),
                optimistic_hours=float(data.get("optimistic_hours") or baseline.optimistic_hours),
                pessimistic_hours=float(data.get("pessimistic_hours") or baseline.pessimistic_hours),
                confidence=str(data.get("confidence") or "medium").lower(),
                rationale=str(data.get("rationale") or baseline.rationale),
                used_provider=provider.name,
            )
        except Exception:
            return None
