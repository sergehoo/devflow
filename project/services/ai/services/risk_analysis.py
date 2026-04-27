"""
Service IA : analyse de risques projet.

Combine signaux quantitatifs (retards, dépassement budget, vélocité) +
analyse qualitative LLM. Persiste les risques détectés sous forme
d'AInsight (type=RISK).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from decimal import Decimal

from django.utils import timezone

from project import models as dm
from project.services.ai.base import AIMessage
from project.services.ai.factory import get_ai_provider
from project.services.ai.openai_provider import OpenAIProvider
from project.services.budget import ProjectBudgetService

logger = logging.getLogger(__name__)


@dataclass
class RiskSignal:
    code: str
    severity: str  # INFO | LOW | MEDIUM | HIGH | CRITICAL
    title: str
    description: str
    score: int


class RiskAnalysisService:
    @classmethod
    def analyze(cls, project: dm.Project, persist: bool = True, use_ai: bool = True) -> list[RiskSignal]:
        signals = cls._heuristic_signals(project)

        if use_ai:
            try:
                ai_signals = cls._ai_signals(project, signals)
                signals.extend(ai_signals)
            except Exception as exc:
                logger.warning("Risk AI step failed for project %s: %s", project.pk, exc)

        if persist:
            cls._persist_signals(project, signals)

        # Met à jour le risk_label sur le projet selon la sévérité max
        cls._update_project_risk_label(project, signals)

        return signals

    # ---------------------------------------------------------------------
    # Heuristique
    # ---------------------------------------------------------------------
    @classmethod
    def _heuristic_signals(cls, project: dm.Project) -> list[RiskSignal]:
        signals: list[RiskSignal] = []
        overview = ProjectBudgetService.build_budget_overview(project)

        # Risque budgétaire
        if overview["approved_budget"] > 0:
            if overview["expense_ratio_percent"] >= 100:
                signals.append(
                    RiskSignal(
                        code="BUDGET_OVERRUN",
                        severity="CRITICAL",
                        title="Budget dépassé",
                        description=f"Coût réel à {overview['expense_ratio_percent']}% du budget approuvé.",
                        score=95,
                    )
                )
            elif overview["expense_ratio_percent"] >= 80:
                signals.append(
                    RiskSignal(
                        code="BUDGET_ALERT",
                        severity="HIGH",
                        title="Budget proche du seuil d'alerte",
                        description=f"Coût réel à {overview['expense_ratio_percent']}% du budget approuvé.",
                        score=75,
                    )
                )

        if overview["forecast_consumption_percent"] >= 110:
            signals.append(
                RiskSignal(
                    code="FORECAST_OVERRUN",
                    severity="HIGH",
                    title="Forecast au-delà du budget",
                    description=(
                        f"La projection ({overview['forecast_final_cost']:.0f}) dépasse le "
                        f"budget approuvé ({overview['approved_budget']:.0f})."
                    ),
                    score=70,
                )
            )

        # Risque planning
        if project.target_date and timezone.localdate() > project.target_date:
            if project.status not in [dm.Project.Status.DONE, dm.Project.Status.CANCELLED]:
                signals.append(
                    RiskSignal(
                        code="DEADLINE_PASSED",
                        severity="HIGH",
                        title="Date cible dépassée",
                        description="Le projet n'est pas livré et la date cible est passée.",
                        score=80,
                    )
                )

        # Risque ressources
        if not project.members.exists():
            signals.append(
                RiskSignal(
                    code="NO_TEAM",
                    severity="MEDIUM",
                    title="Aucun membre assigné",
                    description="Aucune ressource n'est affectée à ce projet.",
                    score=55,
                )
            )

        # Risque marge
        if overview["forecast_margin"] < Decimal("0"):
            signals.append(
                RiskSignal(
                    code="NEGATIVE_MARGIN",
                    severity="HIGH",
                    title="Marge prévisionnelle négative",
                    description="Les coûts projetés dépassent les revenus planifiés.",
                    score=80,
                )
            )

        return signals

    # ---------------------------------------------------------------------
    # AI
    # ---------------------------------------------------------------------
    @classmethod
    def _ai_signals(cls, project: dm.Project, current_signals: list[RiskSignal]) -> list[RiskSignal]:
        provider = get_ai_provider()
        if not provider.is_available():
            return []

        overview = ProjectBudgetService.build_budget_overview(project)
        payload = {
            "project": {
                "name": project.name,
                "status": project.status,
                "priority": project.priority,
                "members_count": project.members.count(),
                "tasks_open": project.tasks.exclude(
                    status__in=[dm.Task.Status.DONE, dm.Task.Status.CANCELLED]
                ).count(),
                "tasks_blocked": project.tasks.filter(status=dm.Task.Status.BLOCKED).count(),
                "start_date": project.start_date.isoformat() if project.start_date else None,
                "target_date": project.target_date.isoformat() if project.target_date else None,
            },
            "financials": {
                "approved_budget": str(overview["approved_budget"]),
                "actual_cost": str(overview["actual_cost"]),
                "forecast_final_cost": str(overview["forecast_final_cost"]),
                "forecast_margin": str(overview["forecast_margin"]),
                "expense_ratio_percent": overview["expense_ratio_percent"],
            },
            "current_signals": [s.code for s in current_signals],
        }

        messages = [
            AIMessage(
                role="system",
                content=(
                    "Tu es un PMO senior. Identifie 0 à 3 risques projet supplémentaires "
                    "non déjà couverts par current_signals. Réponds STRICTEMENT en JSON : "
                    '{"signals": [{"code": "...", "severity": "INFO|LOW|MEDIUM|HIGH|CRITICAL", '
                    '"title": "...", "description": "...", "score": 0-100}]}'
                ),
            ),
            AIMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
        ]

        response = provider.generate(
            messages=messages,
            temperature=0.3,
            json_mode=provider.supports_json_mode(),
        )

        if isinstance(provider, OpenAIProvider):
            data = OpenAIProvider.parse_json(response)
        else:
            try:
                data = json.loads(response.text)
            except Exception:
                data = {}

        out: list[RiskSignal] = []
        for item in data.get("signals", []) or []:
            severity = (item.get("severity") or "MEDIUM").upper()
            if severity not in {"INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"}:
                severity = "MEDIUM"
            try:
                score = int(item.get("score") or 0)
            except Exception:
                score = 0
            out.append(
                RiskSignal(
                    code=str(item.get("code") or "AI_RISK").upper()[:60],
                    severity=severity,
                    title=str(item.get("title") or "Risque IA")[:200],
                    description=str(item.get("description") or "")[:1000],
                    score=max(0, min(100, score)),
                )
            )
        return out

    # ---------------------------------------------------------------------
    # Persistence
    # ---------------------------------------------------------------------
    @classmethod
    def _persist_signals(cls, project: dm.Project, signals: list[RiskSignal]) -> None:
        for signal in signals:
            dm.AInsight.objects.update_or_create(
                workspace=project.workspace,
                project=project,
                insight_type=dm.AInsight.InsightType.RISK,
                title=signal.title,
                defaults={
                    "severity": signal.severity,
                    "summary": signal.description,
                    "recommendation": "",
                    "score": signal.score,
                    "detected_at": timezone.now(),
                    "is_dismissed": False,
                },
            )

    @classmethod
    def _update_project_risk_label(cls, project: dm.Project, signals: list[RiskSignal]) -> None:
        if not signals:
            project.ai_risk_label = "Faible"
            project.risk_score = 10
            project.save(update_fields=["ai_risk_label", "risk_score", "updated_at"])
            return

        order = {"INFO": 1, "LOW": 2, "MEDIUM": 3, "HIGH": 4, "CRITICAL": 5}
        max_signal = max(signals, key=lambda s: order.get(s.severity, 0))

        label_map = {
            "INFO": "Faible",
            "LOW": "Faible",
            "MEDIUM": "Moyen",
            "HIGH": "Élevé",
            "CRITICAL": "Critique",
        }
        project.ai_risk_label = label_map.get(max_signal.severity, "Moyen")
        project.risk_score = max_signal.score
        project.save(update_fields=["ai_risk_label", "risk_score", "updated_at"])
