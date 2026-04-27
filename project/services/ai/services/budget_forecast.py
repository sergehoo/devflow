"""
Service IA : prévision budgétaire basée sur le TJM.

Combine :
1. Heuristique déterministe (toujours disponible) : utilise les TJM, les
   allocations des membres, la durée du projet, les dépenses engagées.
2. Couche IA (optionnelle) : enrichit avec une analyse qualitative,
   détecte des risques de dépassement, propose une fourchette.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from django.utils import timezone

from project import models as dm
from project.services.ai.base import AIMessage
from project.services.ai.factory import get_ai_provider
from project.services.ai.openai_provider import OpenAIProvider
from project.services.budget import ProjectBudgetService

logger = logging.getLogger(__name__)


@dataclass
class BudgetForecast:
    project_id: int
    horizon_end: date
    base_cost: Decimal = Decimal("0")
    optimistic_cost: Decimal = Decimal("0")
    pessimistic_cost: Decimal = Decimal("0")
    base_revenue: Decimal = Decimal("0")
    expected_margin: Decimal = Decimal("0")
    expected_margin_percent: Decimal = Decimal("0")
    overrun_risk_percent: int = 0
    confidence: str = "medium"  # low | medium | high
    drivers: list[str] = field(default_factory=list)
    ai_summary: str = ""
    ai_recommendations: list[str] = field(default_factory=list)
    used_provider: str = "heuristic"

    def to_dict(self) -> dict:
        d = asdict(self)
        # Decimals → str pour la sérialisation JSON
        for k, v in d.items():
            if isinstance(v, Decimal):
                d[k] = str(v)
            if isinstance(v, date):
                d[k] = v.isoformat()
        return d


class BudgetForecastService:
    @classmethod
    def forecast(
        cls,
        project: dm.Project,
        horizon_end: date | None = None,
        use_ai: bool = True,
    ) -> BudgetForecast:
        horizon = horizon_end or project.target_date or timezone.localdate()

        forecast = cls._heuristic_forecast(project, horizon)

        if use_ai:
            try:
                cls._enrich_with_ai(project, forecast)
            except Exception as exc:
                logger.warning("AI enrichment failed for project %s: %s", project.pk, exc)

        return forecast

    # ---------------------------------------------------------------------
    # Heuristique
    # ---------------------------------------------------------------------
    @classmethod
    def _heuristic_forecast(cls, project: dm.Project, horizon: date) -> BudgetForecast:
        overview = ProjectBudgetService.build_budget_overview(project)

        # Coût RH attendu sur l'horizon = somme des estimations membres
        members_cost = Decimal("0")
        for member in project.members.select_related("user"):
            cost, _ = ProjectBudgetService.estimate_member_period_cost(
                user=member.user,
                start=timezone.localdate(),
                end=horizon,
                allocation_percent=member.allocation_percent or 0,
            )
            members_cost += cost

        # Base = ce qui est déjà sorti + engagé non payé + RAF + projection RH
        base_cost = (
            overview["actual_cost"]
            + overview["committed_cost"]
            + overview["raf_cost"]
            + members_cost
        )

        # Optimiste / pessimiste basés sur l'historique de précision
        optimistic_cost = base_cost * Decimal("0.92")
        pessimistic_cost = base_cost * Decimal("1.18")

        base_revenue = overview["planned_revenue"] or overview["estimate_summary"]["total_sale"]
        expected_margin = base_revenue - base_cost
        expected_margin_percent = (
            (expected_margin / base_revenue * Decimal("100")) if base_revenue > 0 else Decimal("0")
        )

        # Risque de dépassement : ratio forecast / budget approuvé
        approved = overview["approved_budget"]
        overrun_risk = 0
        if approved > 0:
            ratio = pessimistic_cost / approved
            if ratio >= Decimal("1.2"):
                overrun_risk = 90
            elif ratio >= Decimal("1.05"):
                overrun_risk = 70
            elif ratio >= Decimal("0.95"):
                overrun_risk = 45
            elif ratio >= Decimal("0.8"):
                overrun_risk = 25
            else:
                overrun_risk = 10

        confidence = "high" if approved > 0 and project.members.count() >= 3 else "medium"
        if not project.members.exists() or not project.start_date:
            confidence = "low"

        drivers = []
        if members_cost > Decimal("0"):
            drivers.append(f"Projection RH TJM × allocation : {members_cost:.0f}")
        if overview["raf_cost"] > 0:
            drivers.append(f"Reste à faire estimé : {overview['raf_cost']:.0f}")
        if overview["committed_cost"] > 0:
            drivers.append(f"Engagements non décaissés : {overview['committed_cost']:.0f}")
        if overrun_risk >= 70:
            drivers.append("Risque élevé de dépassement budget approuvé")

        return BudgetForecast(
            project_id=project.pk,
            horizon_end=horizon,
            base_cost=base_cost.quantize(Decimal("0.01")),
            optimistic_cost=optimistic_cost.quantize(Decimal("0.01")),
            pessimistic_cost=pessimistic_cost.quantize(Decimal("0.01")),
            base_revenue=base_revenue.quantize(Decimal("0.01")),
            expected_margin=expected_margin.quantize(Decimal("0.01")),
            expected_margin_percent=expected_margin_percent.quantize(Decimal("0.01")),
            overrun_risk_percent=overrun_risk,
            confidence=confidence,
            drivers=drivers,
        )

    # ---------------------------------------------------------------------
    # Enrichissement IA
    # ---------------------------------------------------------------------
    @classmethod
    def _enrich_with_ai(cls, project: dm.Project, forecast: BudgetForecast) -> None:
        provider = get_ai_provider()
        if not provider.is_available():
            return

        prompt_user = json.dumps(
            {
                "project": {
                    "name": project.name,
                    "status": project.status,
                    "priority": project.priority,
                    "members_count": project.members.count(),
                    "tasks_count": project.tasks.filter(is_archived=False).count(),
                    "start_date": project.start_date.isoformat() if project.start_date else None,
                    "target_date": project.target_date.isoformat() if project.target_date else None,
                },
                "forecast": forecast.to_dict(),
            },
            ensure_ascii=False,
        )

        messages = [
            AIMessage(
                role="system",
                content=(
                    "Tu es un CFO senior spécialisé en projets logiciels. "
                    "Analyse la prévision budgétaire fournie. Réponds STRICTEMENT en JSON avec "
                    "les clefs : ai_summary (string, 1-2 phrases en français), "
                    "ai_recommendations (liste de 2-4 strings actionnables, en français), "
                    "confidence_override (low|medium|high|null), "
                    "overrun_risk_override (entier 0-100 ou null)."
                ),
            ),
            AIMessage(role="user", content=prompt_user),
        ]

        response = provider.generate(
            messages=messages,
            temperature=0.2,
            json_mode=provider.supports_json_mode(),
        )

        if isinstance(provider, OpenAIProvider):
            data = OpenAIProvider.parse_json(response)
        else:
            data = _safe_json(response.text)

        if not data:
            return

        forecast.ai_summary = (data.get("ai_summary") or "").strip()
        recos = data.get("ai_recommendations") or []
        if isinstance(recos, list):
            forecast.ai_recommendations = [str(r) for r in recos if str(r).strip()]
        if data.get("confidence_override") in {"low", "medium", "high"}:
            forecast.confidence = data["confidence_override"]
        if isinstance(data.get("overrun_risk_override"), int):
            forecast.overrun_risk_percent = max(0, min(100, data["overrun_risk_override"]))
        forecast.used_provider = provider.name


def _safe_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[-1]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except Exception:
        return {}
