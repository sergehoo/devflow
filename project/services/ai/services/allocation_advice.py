"""
Service IA : recommandation d'allocation des ressources.

Analyse les membres workspace + projets en cours, et propose qui affecter
sur quel projet en optimisant : compétences, charge actuelle, TJM, marge
projet attendue.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from decimal import Decimal

from django.db.models import Sum

from project import models as dm
from project.services.ai.base import AIMessage
from project.services.ai.factory import get_ai_provider
from project.services.ai.openai_provider import OpenAIProvider
from project.services.budget import ProjectBudgetService

logger = logging.getLogger(__name__)


@dataclass
class AllocationRecommendation:
    user_id: int
    user_label: str
    project_id: int
    project_name: str
    suggested_allocation_percent: int
    expected_cost: str
    expected_margin: str
    rationale: str


@dataclass
class AllocationAdvice:
    workspace_id: int
    recommendations: list[AllocationRecommendation] = field(default_factory=list)
    underloaded_users: list[str] = field(default_factory=list)
    overloaded_users: list[str] = field(default_factory=list)
    ai_summary: str = ""
    used_provider: str = "heuristic"

    def to_dict(self) -> dict:
        return {
            "workspace_id": self.workspace_id,
            "recommendations": [asdict(r) for r in self.recommendations],
            "underloaded_users": self.underloaded_users,
            "overloaded_users": self.overloaded_users,
            "ai_summary": self.ai_summary,
            "used_provider": self.used_provider,
        }


class AllocationAdviceService:
    @classmethod
    def advise(cls, workspace: dm.Workspace, use_ai: bool = True) -> AllocationAdvice:
        advice = AllocationAdvice(workspace_id=workspace.pk)

        cls._compute_loads(workspace, advice)
        cls._suggest_assignments(workspace, advice)

        if use_ai:
            try:
                cls._ai_summary(workspace, advice)
            except Exception as exc:
                logger.warning("Allocation AI step failed for workspace %s: %s", workspace.pk, exc)

        return advice

    # ---------------------------------------------------------------------
    @classmethod
    def _compute_loads(cls, workspace: dm.Workspace, advice: AllocationAdvice) -> None:
        memberships = (
            dm.TeamMembership.objects.filter(workspace=workspace)
            .exclude(status=dm.TeamMembership.Status.INACTIVE)
            .select_related("user", "team")
        )

        loads: dict[int, dict] = {}
        for m in memberships:
            if not m.user_id:
                continue
            entry = loads.setdefault(
                m.user_id,
                {"user": m.user, "alloc_total": 0, "projects": []},
            )

            user_alloc = (
                dm.ProjectMember.objects.filter(user_id=m.user_id, project__workspace=workspace)
                .aggregate(total=Sum("allocation_percent"))
                .get("total")
                or 0
            )
            entry["alloc_total"] = user_alloc

        for entry in loads.values():
            label = str(entry["user"])
            if entry["alloc_total"] >= 110:
                advice.overloaded_users.append(f"{label} ({entry['alloc_total']}%)")
            elif entry["alloc_total"] <= 60:
                advice.underloaded_users.append(f"{label} ({entry['alloc_total']}%)")

    @classmethod
    def _suggest_assignments(cls, workspace: dm.Workspace, advice: AllocationAdvice) -> None:
        active_projects = workspace.projects.filter(
            status__in=[dm.Project.Status.PLANNED, dm.Project.Status.IN_PROGRESS]
        )

        # Membres encore disponibles : on prend ceux qui ont moins de 80% alloués
        candidates = (
            dm.UserProfile.objects.filter(workspace=workspace, is_active=True)
            .select_related("user")
        )

        for project in active_projects[:6]:
            for profile in candidates:
                user = profile.user
                if not user:
                    continue

                current_alloc = (
                    dm.ProjectMember.objects.filter(user=user, project__workspace=workspace)
                    .aggregate(total=Sum("allocation_percent"))
                    .get("total")
                    or 0
                )
                if current_alloc >= 90:
                    continue
                if dm.ProjectMember.objects.filter(project=project, user=user).exists():
                    continue

                free_capacity = max(100 - current_alloc, 0)
                if free_capacity < 20:
                    continue

                suggested = min(40, free_capacity)
                cost, sale = ProjectBudgetService.estimate_member_period_cost(
                    user=user,
                    start=project.start_date,
                    end=project.target_date,
                    allocation_percent=suggested,
                )
                margin = sale - cost

                advice.recommendations.append(
                    AllocationRecommendation(
                        user_id=user.pk,
                        user_label=str(user),
                        project_id=project.pk,
                        project_name=project.name,
                        suggested_allocation_percent=int(suggested),
                        expected_cost=str(cost.quantize(Decimal("0.01"))),
                        expected_margin=str(margin.quantize(Decimal("0.01"))),
                        rationale=(
                            f"{user} a {free_capacity}% de capacité libre. "
                            f"Allocation suggérée {suggested}% sur « {project.name} » : "
                            f"coût ≈ {cost:.0f}, marge attendue ≈ {margin:.0f}."
                        ),
                    )
                )
                if len(advice.recommendations) >= 12:
                    return

    @classmethod
    def _ai_summary(cls, workspace: dm.Workspace, advice: AllocationAdvice) -> None:
        provider = get_ai_provider()
        if not provider.is_available():
            return

        messages = [
            AIMessage(
                role="system",
                content=(
                    "Tu es un Resource Manager. À partir des recommandations heuristiques fournies, "
                    "rédige une synthèse de 2-3 phrases en français pour le COMEX, listant les arbitrages "
                    "principaux (qui surcharger, qui rééquilibrer). Réponds en JSON : "
                    '{"ai_summary": "..."}'
                ),
            ),
            AIMessage(
                role="user",
                content=json.dumps(advice.to_dict(), ensure_ascii=False),
            ),
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

        advice.ai_summary = (data.get("ai_summary") or "").strip()
        advice.used_provider = provider.name
