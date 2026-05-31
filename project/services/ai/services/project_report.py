"""
DevFlow — Service de rapport projet IA (Phase 5, PR22).

Génère un rapport hebdomadaire structuré en Markdown :
  * Résumé exécutif (2-3 phrases)
  * Avancement (tâches done / in progress / overdue)
  * Risques (alertes budget, insights IA, retards)
  * Recommandations (3-5 actions priorisées)
  * KPIs (chiffres clés)

Pattern DevFlow respecté :
  1. ``_build_context(project, period_start, period_end)`` — données factuelles
  2. ``_heuristic_markdown(context)`` — rapport baseline déterministe (fallback)
  3. ``_enrich_with_ai(context, report)`` — rédige un rapport plus naturel
     via DeepSeek/OpenAI/Local, sans casser la structure
  4. Quota check via ``AIQuotaService`` avant l'appel
  5. Persistance comme ``ProjectAIReport``
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from project import models as dm
from project.services.ai.base import AIMessage
from project.services.ai.factory import get_ai_provider
from project.services.ai.quota import AIPromptLibrary, AIQuotaService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constantes & dataclass
# ---------------------------------------------------------------------------
DEFAULT_REPORT_PROMPT = """\
Tu es un rédacteur de rapports projet expérimenté. À partir du contexte
factuel ci-dessous, rédige un rapport hebdomadaire en Markdown structuré
EXACTEMENT en 5 sections :

# {project_name} — Rapport semaine du {period_start} au {period_end}

## Résumé exécutif
(2-3 phrases qui synthétisent l'état du projet)

## Avancement
(Décris ce qui a bougé : tâches terminées, en cours, en retard ; sprints
actifs ; jalons franchis. Sois factuel, pas marketing.)

## Risques
(Liste 1 à 5 risques avec leur niveau : 🔴 critique / 🟡 moyen / 🟢 maîtrisé.
Reprends les alertes budget et insights IA fournis.)

## Recommandations
(3 à 5 actions concrètes prioritaires pour la semaine à venir. Commence
chaque ligne par un verbe d'action.)

## KPIs
(Tableau Markdown des chiffres clés : avancement %, tâches done/total,
retards, budget consommé %, etc.)

Contraintes : sortie 100% Markdown, pas de blabla introductif, ton
professionnel et direct, en français.

Contexte factuel :
- Statut : {project_status}
- Progression : {progress_percent}%
- Risque IA : {risk_label} (score {risk_score}/100)
- Tâches : {tasks_total} total · {tasks_done_period} terminées sur la
  période · {tasks_overdue} en retard
- Sprint actif : {sprint_name}
- Budget : consommé {budget_consumed_percent}% sur {approved_budget} {currency}
- Alertes budget : {budget_alert}
- Insights IA récents : {recent_insights_brief}
"""


@dataclass
class ProjectReportResult:
    project_id: int
    report_id: int | None
    title: str
    content_markdown: str
    summary: str
    period_start: date
    period_end: date
    used_provider: str = "heuristic"
    tokens_used: int = 0

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "report_id": self.report_id,
            "title": self.title,
            "summary": self.summary,
            "content_markdown": self.content_markdown,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "used_provider": self.used_provider,
            "tokens_used": self.tokens_used,
        }


# ---------------------------------------------------------------------------
# Service public
# ---------------------------------------------------------------------------
class ProjectAIReportService:
    """Génère et persiste un rapport projet IA."""

    @classmethod
    def _default_period(cls) -> tuple[date, date]:
        """Semaine N-1 : lundi de la semaine passée → dimanche dernier."""
        today = timezone.localdate()
        # ISO weekday : 1=lun, 7=dim → cette semaine commence à today - (weekday-1)
        this_monday = today - timedelta(days=today.weekday())
        last_sunday = this_monday - timedelta(days=1)
        last_monday = last_sunday - timedelta(days=6)
        return last_monday, last_sunday

    @classmethod
    @transaction.atomic
    def generate(
        cls,
        project: dm.Project,
        *,
        period: str = "WEEKLY",
        period_start: date | None = None,
        period_end: date | None = None,
        use_ai: bool = True,
        actor=None,
    ) -> ProjectReportResult:
        """
        Génère un rapport pour la période donnée et le persiste.

        Idempotence : si un rapport existe déjà pour
        ``(project, period, period_start)``, on le retourne tel quel
        (anti-doublon via UniqueConstraint).
        """
        if period_start is None or period_end is None:
            period_start, period_end = cls._default_period()

        # Anti-doublon strict (cohérent avec la UniqueConstraint)
        existing = dm.ProjectAIReport.objects.filter(
            project=project, period=period, period_start=period_start,
        ).first()
        if existing and existing.status == dm.ProjectAIReport.ReportStatus.READY:
            return ProjectReportResult(
                project_id=project.pk,
                report_id=existing.pk,
                title=existing.title,
                content_markdown=existing.content_markdown,
                summary=existing.summary,
                period_start=existing.period_start,
                period_end=existing.period_end,
                used_provider=existing.used_provider,
                tokens_used=existing.tokens_used,
            )

        context = cls._build_context(project, period_start, period_end)
        markdown_content = cls._heuristic_markdown(project, context, period_start, period_end)
        used_provider = "heuristic"
        tokens_used = 0

        # Quota check + enrichissement IA optionnel
        if use_ai:
            quota_check = AIQuotaService.can_consume(
                project.workspace, estimated_tokens=1500,
            )
            if quota_check.allowed:
                try:
                    enriched_markdown, used_provider, tokens_used = cls._enrich_with_ai(
                        project, context, period_start, period_end,
                    )
                    if enriched_markdown.strip():
                        markdown_content = enriched_markdown
                except Exception as exc:
                    logger.warning(
                        "ProjectAIReport AI enrichment failed for %s: %s",
                        project.pk, exc,
                    )
            else:
                logger.info("Quota IA dépassé pour rapport projet %s — fallback heuristique",
                             project.pk)

        title = (
            f"Rapport semaine du {period_start:%d %b %Y} "
            f"au {period_end:%d %b %Y}"
        )
        summary = cls._extract_summary(markdown_content)

        # Persist (create ou update si on retomberait sur un FAILED précédent)
        report, _ = dm.ProjectAIReport.objects.update_or_create(
            project=project, period=period, period_start=period_start,
            defaults={
                "workspace": project.workspace,
                "period_end": period_end,
                "title": title,
                "status": dm.ProjectAIReport.ReportStatus.READY,
                "content_markdown": markdown_content,
                "summary": summary,
                "payload": context,
                "used_provider": used_provider,
                "tokens_used": tokens_used,
                "generated_at": timezone.now(),
                "generated_by": actor,
                "failure_reason": "",
            },
        )

        return ProjectReportResult(
            project_id=project.pk,
            report_id=report.pk,
            title=title,
            content_markdown=markdown_content,
            summary=summary,
            period_start=period_start,
            period_end=period_end,
            used_provider=used_provider,
            tokens_used=tokens_used,
        )

    # ─── Contexte factuel ─────────────────────────────────────────────────
    @classmethod
    def _build_context(
        cls,
        project: dm.Project,
        period_start: date,
        period_end: date,
    ) -> dict:
        today = timezone.localdate()
        tasks_qs = project.tasks.filter(is_archived=False)
        tasks_total = tasks_qs.count()
        tasks_done_period = tasks_qs.filter(
            status="DONE",
            completed_at__date__gte=period_start,
            completed_at__date__lte=period_end,
        ).count()
        tasks_done_total = tasks_qs.filter(status="DONE").count()
        tasks_overdue = tasks_qs.filter(
            due_date__lt=today,
        ).exclude(status__in=["DONE", "CANCELLED", "EXPIRED"]).count()
        tasks_in_progress = tasks_qs.filter(status="IN_PROGRESS").count()

        sprint = project.sprints.filter(
            is_archived=False, status="ACTIVE",
        ).first()
        sprint_name = sprint.name if sprint else "—"

        # Insights IA récents (5 dernières sévérité ≥ MEDIUM)
        insights = list(
            project.ai_insights.filter(
                detected_at__date__gte=period_start - timedelta(days=14),
                is_dismissed=False,
            )
            .order_by("-score", "-detected_at")[:5]
        )
        recent_insights_brief = (
            "; ".join(
                f"{i.severity} · {i.title[:80]}" for i in insights
            ) or "Aucun signal récent."
        )

        # Budget overview (best-effort)
        budget_consumed_percent = 0
        approved_budget = Decimal("0")
        currency = "XOF"
        budget_alert = "Aucune alerte."
        try:
            from project.services.budget import ProjectBudgetService
            from project.services.budget_snapshots import BudgetAlertService

            overview = ProjectBudgetService.build_budget_overview(project)
            budget_consumed_percent = int(overview.get("forecast_consumption_percent") or 0)
            approved_budget = Decimal(str(overview.get("approved_budget") or "0"))
            currency = overview.get("currency") or "XOF"
            alert = BudgetAlertService.for_project(project)
            if alert:
                budget_alert = (
                    f"{alert.severity.upper()} — consommation "
                    f"{alert.consumption_percent}% (seuil {alert.alert_threshold_percent}%)"
                )
        except Exception:
            pass

        return {
            "project_name": project.name,
            "project_status": project.get_status_display(),
            "progress_percent": project.progress_percent,
            "risk_label": project.ai_risk_label or "—",
            "risk_score": project.risk_score or 0,
            "tasks_total": tasks_total,
            "tasks_done_total": tasks_done_total,
            "tasks_done_period": tasks_done_period,
            "tasks_overdue": tasks_overdue,
            "tasks_in_progress": tasks_in_progress,
            "sprint_name": sprint_name,
            "budget_consumed_percent": budget_consumed_percent,
            "approved_budget": str(approved_budget),
            "currency": currency,
            "budget_alert": budget_alert,
            "recent_insights": [
                {
                    "title": i.title,
                    "severity": i.severity,
                    "score": i.score,
                }
                for i in insights
            ],
            "recent_insights_brief": recent_insights_brief,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
        }

    # ─── Rapport baseline déterministe ───────────────────────────────────
    @classmethod
    def _heuristic_markdown(
        cls,
        project: dm.Project,
        ctx: dict,
        period_start: date,
        period_end: date,
    ) -> str:
        """Rapport markdown garanti même si l'IA est down."""
        risks_lines = []
        if ctx["tasks_overdue"] > 0:
            risks_lines.append(
                f"- 🟡 **{ctx['tasks_overdue']} tâche(s) en retard** "
                f"à replanifier ou marquer expirées."
            )
        if ctx["budget_alert"] != "Aucune alerte.":
            risks_lines.append(f"- 🔴 **Budget** — {ctx['budget_alert']}.")
        if ctx["risk_score"] >= 70:
            risks_lines.append(
                f"- 🔴 **Risque IA élevé** ({ctx['risk_score']}/100) — "
                f"déclencher une analyse détaillée."
            )
        if not risks_lines:
            risks_lines.append("- 🟢 Aucun risque majeur détecté sur la période.")

        recos_lines = []
        if ctx["tasks_overdue"] >= 3:
            recos_lines.append("- Replanifier les tâches en retard avant vendredi.")
        if ctx["progress_percent"] < 30:
            recos_lines.append("- Reprioriser le scope restant si la date cible est proche.")
        if ctx["budget_consumed_percent"] >= 80:
            recos_lines.append("- Réviser le budget ou demander une rallonge.")
        if ctx["tasks_in_progress"] > 10:
            recos_lines.append("- Réduire le WIP : trop de tâches actives en parallèle.")
        if not recos_lines:
            recos_lines.append("- Maintenir la cadence — tout est en ligne.")

        md = (
            f"# {project.name} — Rapport semaine du "
            f"{period_start:%d %b %Y} au {period_end:%d %b %Y}\n\n"
            f"## Résumé exécutif\n"
            f"Avancement à {ctx['progress_percent']}%. "
            f"{ctx['tasks_done_period']} tâche(s) terminée(s) sur la période, "
            f"{ctx['tasks_overdue']} en retard. "
            f"Statut : {ctx['project_status']}.\n\n"
            f"## Avancement\n"
            f"- Tâches terminées sur la période : **{ctx['tasks_done_period']}**\n"
            f"- Tâches en cours : **{ctx['tasks_in_progress']}**\n"
            f"- Tâches en retard : **{ctx['tasks_overdue']}**\n"
            f"- Sprint actif : *{ctx['sprint_name']}*\n\n"
            f"## Risques\n"
            + "\n".join(risks_lines) + "\n\n"
            f"## Recommandations\n"
            + "\n".join(recos_lines) + "\n\n"
            f"## KPIs\n\n"
            f"| Indicateur | Valeur |\n"
            f"|---|---|\n"
            f"| Avancement | {ctx['progress_percent']}% |\n"
            f"| Tâches done / total | {ctx['tasks_done_total']} / {ctx['tasks_total']} |\n"
            f"| Tâches en retard | {ctx['tasks_overdue']} |\n"
            f"| Budget consommé | {ctx['budget_consumed_percent']}% |\n"
            f"| Risque IA | {ctx['risk_label']} ({ctx['risk_score']}/100) |\n"
        )
        return md

    # ─── Enrichissement IA ────────────────────────────────────────────────
    @classmethod
    def _enrich_with_ai(
        cls,
        project: dm.Project,
        ctx: dict,
        period_start: date,
        period_end: date,
    ) -> tuple[str, str, int]:
        """Retourne (markdown, used_provider, tokens_used) ou ('', 'heuristic', 0)."""
        provider = get_ai_provider()
        if not provider.is_available():
            return "", "heuristic", 0

        prompt_template = AIPromptLibrary.get_prompt(
            "project_report", project.workspace, DEFAULT_REPORT_PROMPT,
        )
        prompt = AIPromptLibrary.render(
            prompt_template,
            project_name=ctx["project_name"],
            project_status=ctx["project_status"],
            progress_percent=ctx["progress_percent"],
            risk_label=ctx["risk_label"],
            risk_score=ctx["risk_score"],
            tasks_total=ctx["tasks_total"],
            tasks_done_period=ctx["tasks_done_period"],
            tasks_overdue=ctx["tasks_overdue"],
            sprint_name=ctx["sprint_name"],
            budget_consumed_percent=ctx["budget_consumed_percent"],
            approved_budget=ctx["approved_budget"],
            currency=ctx["currency"],
            budget_alert=ctx["budget_alert"],
            recent_insights_brief=ctx["recent_insights_brief"],
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
        )

        response = provider.generate(
            [
                AIMessage(role="system",
                          content="Tu es un rédacteur de rapports projet."),
                AIMessage(role="user", content=prompt),
            ],
            temperature=0.3,
            max_tokens=1200,
            json_mode=False,
        )

        markdown = (response.text or "").strip()
        if markdown:
            # Quota tracking
            if response.tokens_used:
                AIQuotaService.record_usage(project.workspace, response.tokens_used)
            return markdown, response.provider or "ai", response.tokens_used or 0

        return "", "heuristic", 0

    # ─── Résumé exécutif extrait du markdown ─────────────────────────────
    @classmethod
    def _extract_summary(cls, markdown: str) -> str:
        """Récupère la première phrase non vide du markdown (hors titre)."""
        for line in (markdown or "").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("|") or line.startswith("-"):
                continue
            return line[:280]
        return ""
