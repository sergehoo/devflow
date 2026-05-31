"""
Services IA Phase 4 (PR18) — résumé, recommandations, génération roadmap.

Trois services qui suivent le pattern DevFlow :
  1. Heuristique déterministe (toujours dispo)
  2. Enrichissement IA optionnel (DeepSeek/OpenAI/Local via factory)
  3. Quota check + record via ``AIQuotaService``
  4. Prompt résolution via ``AIPromptLibrary`` (workspace > default)

Aucun appel API direct — tout passe par ``get_ai_provider()`` qui aiguille
sur le provider configuré (DeepSeek prioritaire en Phase 4).
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.utils import timezone

from project import models as dm
from project.services.ai.base import AIMessage
from project.services.ai.factory import get_ai_provider
from project.services.ai.openai_provider import OpenAIProvider
from project.services.ai.quota import AIPromptLibrary, AIQuotaService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Project Summary
# ---------------------------------------------------------------------------
@dataclass
class ProjectSummary:
    project_id: int
    summary: str
    health_summary: str
    progress_summary: str
    risk_summary: str
    used_provider: str = "heuristic"
    tokens_used: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


_DEFAULT_SUMMARY_PROMPT = """\
Tu es un assistant de pilotage projet. Rédige un résumé concis et factuel
du projet, en 3 paragraphes courts en français :

1. État d'avancement (% complétion, sprint actuel, échéance)
2. Risques principaux (au plus 3, classés par criticité)
3. Recommandations immédiates (au plus 3 actions concrètes)

Réponds en JSON strict :
{
  "summary": "...",
  "health_summary": "...",
  "progress_summary": "...",
  "risk_summary": "..."
}

Données projet :
- Nom : {project_name}
- Description : {project_description}
- Statut : {project_status}
- Progression : {progress_percent}%
- Risque IA : {risk_label} ({risk_score}/100)
- Échéance : {target_date}
- Équipe : {team_name}
- Tâches : {tasks_total} total, {tasks_done} terminées, {tasks_overdue} en retard
"""


class ProjectSummaryService:
    """
    Génère un résumé projet 3 paragraphes en JSON structuré.

    Heuristique : si l'IA est indisponible, on renvoie un résumé construit
    factuellement depuis les attributs du projet (jamais d'erreur user).
    """

    @classmethod
    def summarize(
        cls,
        project: dm.Project,
        *,
        use_ai: bool = True,
        actor=None,
    ) -> ProjectSummary:
        # Heuristique baseline — sert aussi de fallback
        result = cls._heuristic(project)
        if not use_ai:
            return result

        # Quota check
        quota_check = AIQuotaService.can_consume(project.workspace, estimated_tokens=800)
        if not quota_check.allowed:
            logger.info("Quota IA dépassé pour summary projet %s", project.pk)
            return result

        try:
            cls._enrich_with_ai(project, result)
        except Exception as exc:
            logger.warning("ProjectSummary AI enrichment failed: %s", exc)

        return result

    @classmethod
    def _heuristic(cls, project: dm.Project) -> ProjectSummary:
        tasks_total = project.tasks.filter(is_archived=False).count()
        tasks_done = project.tasks.filter(
            is_archived=False, status="DONE",
        ).count()
        today = timezone.localdate()
        tasks_overdue = project.tasks.filter(
            is_archived=False, due_date__lt=today,
        ).exclude(status__in=["DONE", "CANCELLED", "EXPIRED"]).count()

        progress_summary = (
            f"Avancement {project.progress_percent}% — {tasks_done}/{tasks_total} "
            f"tâches terminées."
        )
        health_summary = f"Statut : {project.get_status_display()}."
        risk_summary = (
            f"{tasks_overdue} tâche{'s' if tasks_overdue > 1 else ''} en retard."
            if tasks_overdue
            else "Aucune tâche en retard détectée."
        )
        summary = (
            f"Projet {project.name} : {progress_summary} "
            f"{health_summary} {risk_summary}"
        )
        return ProjectSummary(
            project_id=project.pk,
            summary=summary,
            health_summary=health_summary,
            progress_summary=progress_summary,
            risk_summary=risk_summary,
        )

    @classmethod
    def _enrich_with_ai(cls, project: dm.Project, result: ProjectSummary) -> None:
        provider = get_ai_provider()
        if not provider.is_available():
            return

        team_name = project.team.name if project.team_id else "—"
        tasks_total = project.tasks.filter(is_archived=False).count()
        tasks_done = project.tasks.filter(
            is_archived=False, status="DONE",
        ).count()
        today = timezone.localdate()
        tasks_overdue = project.tasks.filter(
            is_archived=False, due_date__lt=today,
        ).exclude(status__in=["DONE", "CANCELLED", "EXPIRED"]).count()

        prompt_template = AIPromptLibrary.get_prompt(
            "project_summary", project.workspace, _DEFAULT_SUMMARY_PROMPT,
        )
        prompt = AIPromptLibrary.render(
            prompt_template,
            project_name=project.name,
            project_description=(project.description or "")[:500],
            project_status=project.get_status_display(),
            progress_percent=project.progress_percent,
            risk_label=project.ai_risk_label or "—",
            risk_score=project.risk_score or 0,
            target_date=project.target_date or "—",
            team_name=team_name,
            tasks_total=tasks_total,
            tasks_done=tasks_done,
            tasks_overdue=tasks_overdue,
        )

        response = provider.generate(
            [
                AIMessage(role="system",
                          content="Tu réponds toujours en JSON strict valide."),
                AIMessage(role="user", content=prompt),
            ],
            temperature=0.2,
            max_tokens=600,
            json_mode=provider.supports_json_mode(),
        )

        # Track quota
        if response.tokens_used:
            AIQuotaService.record_usage(project.workspace, response.tokens_used)
            result.tokens_used = response.tokens_used
        result.used_provider = response.provider or "ai"

        try:
            data = OpenAIProvider.parse_json(response)  # tolérant aux artefacts
        except Exception:
            data = {}

        for key in ("summary", "health_summary", "progress_summary", "risk_summary"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                setattr(result, key, value.strip())


# ---------------------------------------------------------------------------
# Project Recommendations
# ---------------------------------------------------------------------------
@dataclass
class ProjectRecommendation:
    title: str
    priority: str  # CRITICAL / HIGH / MEDIUM / LOW
    description: str = ""
    rationale: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ProjectRecommendationsResult:
    project_id: int
    recommendations: list[ProjectRecommendation] = field(default_factory=list)
    used_provider: str = "heuristic"
    tokens_used: int = 0

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "recommendations": [r.to_dict() for r in self.recommendations],
            "used_provider": self.used_provider,
            "tokens_used": self.tokens_used,
        }


_DEFAULT_RECOMMENDATIONS_PROMPT = """\
Tu es un coach senior en gestion de projet. Génère 3 à 5 recommandations
actionnables pour faire progresser ce projet. Chaque recommandation doit
être concrète (commencer par un verbe : "Réviser", "Planifier", "Réaffecter"…)
et associée à une priorité (CRITICAL/HIGH/MEDIUM/LOW).

Réponds en JSON strict :
{
  "recommendations": [
    {"title": "...", "priority": "HIGH", "description": "...", "rationale": "..."}
  ]
}

Données projet :
- Nom : {project_name}
- Description : {project_description}
- Statut : {project_status}
- Progression : {progress_percent}%
- Risque : {risk_label} ({risk_score}/100)
- Échéance : {target_date}
- Tâches en retard : {tasks_overdue}
- Budget consommé : {budget_consumed_percent}%
"""


class ProjectRecommendationsService:
    @classmethod
    def recommend(
        cls,
        project: dm.Project,
        *,
        use_ai: bool = True,
    ) -> ProjectRecommendationsResult:
        result = cls._heuristic(project)
        if not use_ai:
            return result

        quota_check = AIQuotaService.can_consume(project.workspace, estimated_tokens=600)
        if not quota_check.allowed:
            logger.info("Quota IA dépassé pour recommendations projet %s", project.pk)
            return result

        try:
            cls._enrich_with_ai(project, result)
        except Exception as exc:
            logger.warning("ProjectRecommendations AI enrichment failed: %s", exc)

        return result

    @classmethod
    def _heuristic(cls, project: dm.Project) -> ProjectRecommendationsResult:
        recos: list[ProjectRecommendation] = []
        today = timezone.localdate()
        tasks_overdue = project.tasks.filter(
            is_archived=False, due_date__lt=today,
        ).exclude(status__in=["DONE", "CANCELLED", "EXPIRED"]).count()

        if tasks_overdue >= 5:
            recos.append(ProjectRecommendation(
                title="Replanifier les tâches en retard",
                priority="HIGH",
                description=f"{tasks_overdue} tâches dépassent leur échéance.",
                rationale="Risque de glissement global du projet.",
            ))
        if project.progress_percent < 30 and project.target_date:
            days_left = (project.target_date - today).days
            if days_left < 30:
                recos.append(ProjectRecommendation(
                    title="Reprioriser le scope restant",
                    priority="CRITICAL",
                    description=(
                        f"Seulement {project.progress_percent}% d'avancement "
                        f"à {days_left} jours de l'échéance."
                    ),
                ))
        if not project.product_manager_id:
            recos.append(ProjectRecommendation(
                title="Nommer un product manager",
                priority="MEDIUM",
                description="Aucun PM affecté à ce projet.",
            ))
        if project.risk_score and project.risk_score >= 70:
            recos.append(ProjectRecommendation(
                title="Refaire une analyse de risques détaillée",
                priority="HIGH",
                description=f"Score risque IA actuel : {project.risk_score}/100.",
            ))
        if not recos:
            recos.append(ProjectRecommendation(
                title="Maintenir la cadence actuelle",
                priority="LOW",
                description="Aucun signal d'alerte détecté.",
            ))
        return ProjectRecommendationsResult(
            project_id=project.pk, recommendations=recos,
        )

    @classmethod
    def _enrich_with_ai(cls, project, result):
        provider = get_ai_provider()
        if not provider.is_available():
            return

        today = timezone.localdate()
        tasks_overdue = project.tasks.filter(
            is_archived=False, due_date__lt=today,
        ).exclude(status__in=["DONE", "CANCELLED", "EXPIRED"]).count()

        budget = getattr(project, "budgetestimatif", None)
        budget_pct = 0
        if budget:
            try:
                from project.services.budget import ProjectBudgetService
                overview = ProjectBudgetService.build_budget_overview(project)
                budget_pct = int(overview.get("forecast_consumption_percent") or 0)
            except Exception:
                pass

        prompt_template = AIPromptLibrary.get_prompt(
            "project_recommendations", project.workspace,
            _DEFAULT_RECOMMENDATIONS_PROMPT,
        )
        prompt = AIPromptLibrary.render(
            prompt_template,
            project_name=project.name,
            project_description=(project.description or "")[:400],
            project_status=project.get_status_display(),
            progress_percent=project.progress_percent,
            risk_label=project.ai_risk_label or "—",
            risk_score=project.risk_score or 0,
            target_date=project.target_date or "—",
            tasks_overdue=tasks_overdue,
            budget_consumed_percent=budget_pct,
        )

        response = provider.generate(
            [
                AIMessage(role="system",
                          content="Tu réponds toujours en JSON strict valide."),
                AIMessage(role="user", content=prompt),
            ],
            temperature=0.3,
            max_tokens=700,
            json_mode=provider.supports_json_mode(),
        )

        if response.tokens_used:
            AIQuotaService.record_usage(project.workspace, response.tokens_used)
            result.tokens_used = response.tokens_used
        result.used_provider = response.provider or "ai"

        try:
            data = OpenAIProvider.parse_json(response)
        except Exception:
            data = {}

        items = data.get("recommendations") or []
        ai_recos: list[ProjectRecommendation] = []
        for raw in items[:5]:
            if not isinstance(raw, dict):
                continue
            title = (raw.get("title") or "").strip()
            if not title:
                continue
            priority = (raw.get("priority") or "MEDIUM").upper()
            if priority not in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}:
                priority = "MEDIUM"
            ai_recos.append(ProjectRecommendation(
                title=title[:140],
                priority=priority,
                description=(raw.get("description") or "")[:400],
                rationale=(raw.get("rationale") or "")[:400],
            ))

        if ai_recos:
            result.recommendations = ai_recos


# ---------------------------------------------------------------------------
# Project Roadmap Generation
# ---------------------------------------------------------------------------
@dataclass
class RoadmapGenerationResult:
    project_id: int
    proposal_id: int | None
    items_created: int
    used_provider: str

    def to_dict(self) -> dict:
        return asdict(self)


class ProjectRoadmapGenerationService:
    """
    Wrapper léger sur ``ProjectAIStructureService.generate_for_project``
    avec quota check + tracking. Idempotent : si une proposition non
    terminale existe, on la retourne sans en créer une nouvelle.
    """

    @classmethod
    def generate(
        cls,
        project: dm.Project,
        *,
        actor=None,
        use_ai: bool = True,
    ) -> RoadmapGenerationResult:
        # Idempotence
        existing = dm.ProjectAIProposal.objects.filter(
            project=project,
            status__in=[
                dm.ProjectAIProposal.Status.PENDING,
                dm.ProjectAIProposal.Status.GENERATING,
                dm.ProjectAIProposal.Status.READY,
            ],
        ).first()
        if existing and existing.items.exists():
            return RoadmapGenerationResult(
                project_id=project.pk,
                proposal_id=existing.pk,
                items_created=existing.items.count(),
                used_provider=existing.used_provider or "heuristic",
            )

        # Quota check (estimation ~3000 tokens pour une roadmap complète)
        if use_ai:
            quota_check = AIQuotaService.can_consume(
                project.workspace, estimated_tokens=3000,
            )
            if not quota_check.allowed:
                use_ai = False
                logger.info(
                    "Quota IA dépassé pour génération roadmap projet %s — "
                    "fallback heuristique", project.pk,
                )

        # Import local pour éviter cycle ↔ services/ai/services/project_structure.py
        from project.services.ai.services.project_structure import (
            ProjectAIStructureService,
        )

        result = ProjectAIStructureService.generate_for_project(
            project=project,
            triggered_by=actor,
            use_ai=use_ai,
        )

        # Track quota après l'appel réel
        proposal = result.proposal
        if proposal.tokens_used:
            AIQuotaService.record_usage(project.workspace, proposal.tokens_used)

        return RoadmapGenerationResult(
            project_id=project.pk,
            proposal_id=proposal.pk,
            items_created=result.items_created,
            used_provider=result.used_provider or "heuristic",
        )
