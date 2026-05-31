"""
Post-processing par méthodologie projet — Phase 2 (PR13).

Appelé après ``ProposalApplyService.apply()`` dans le Genesis pipeline.
Pour chaque méthodologie, ajoute des artefacts spécifiques :

  * SCRUM / KANBAN / AGILE / MILESTONE → no-op (pipeline existant suffit)
  * WATERFALL → crée des `ProjectPhase` séquentielles (4 phases standard)
  * FIELD     → crée un FieldReport vierge "Jour J" pour amorcer le suivi
  * REAL_ESTATE → crée 3 lots template (T2/T3/T4 selon le brief)
  * ADMINISTRATIVE → crée un AdminCase template basé sur le projet

Ces post-processors sont :
  * **idempotents** : un second appel ne crée pas de doublons
  * **best-effort** : log warning et continue si une erreur survient
  * **scopés workspace** : utilisent project.workspace pour les nouveaux objets
"""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from project import models as dm

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Post-processors par méthodologie
# ---------------------------------------------------------------------------
def _seed_waterfall_phases(project: dm.Project, actor=None) -> int:
    """
    Crée 4 phases séquentielles standard si aucune n'existe encore.

    Phases : Études → Conception → Réalisation → Recette
    """
    if project.phases.exists():
        return 0

    start = project.start_date or timezone.localdate()
    target = project.target_date or (start + timedelta(days=120))
    span = max((target - start).days, 30)
    chunk = span // 4

    phases_data = [
        ("Études",      "Cadrage, analyses, spécifications.",     True),
        ("Conception",  "Architecture, design, plans détaillés.", True),
        ("Réalisation", "Exécution, développement, construction.", False),
        ("Recette",     "Tests, validation, livraison finale.",    True),
    ]

    created = []
    for idx, (name, desc, gate) in enumerate(phases_data):
        phase_start = start + timedelta(days=idx * chunk)
        phase_end = start + timedelta(days=(idx + 1) * chunk - 1)
        if idx == len(phases_data) - 1:
            phase_end = target  # la dernière phase finit pile à la target_date

        created.append(dm.ProjectPhase(
            workspace=project.workspace,
            project=project,
            name=name,
            description=desc,
            position=idx,
            start_date=phase_start,
            end_date=phase_end,
            gate_required=gate,
            owner=actor,
        ))

    dm.ProjectPhase.objects.bulk_create(created)
    return len(created)


def _seed_field_report(project: dm.Project, actor=None) -> int:
    """Crée un rapport de chantier vierge pour la date de démarrage."""
    if project.field_reports.exists():
        return 0

    dm.FieldReport.objects.create(
        workspace=project.workspace,
        project=project,
        reporter=actor,
        report_date=project.start_date or timezone.localdate(),
        location_name=(project.name or "")[:200],
        weather=dm.FieldReport.Weather.OTHER,
        workforce_count=0,
        notes="Premier rapport généré automatiquement — à compléter.",
    )
    return 1


def _seed_real_estate_lots(project: dm.Project, actor=None) -> int:
    """Crée 3 lots template (T2, T3, T4) si aucun n'existe."""
    if project.real_estate_lots.exists():
        return 0

    templates = [
        ("A-101", "RDC", Decimal("45"),  2, Decimal("0")),
        ("A-102", "RDC", Decimal("65"),  3, Decimal("0")),
        ("A-201", "1",   Decimal("85"),  4, Decimal("0")),
    ]

    created = []
    for lot_number, floor, surface, bedrooms, price in templates:
        created.append(dm.RealEstateLot(
            workspace=project.workspace,
            project=project,
            lot_number=lot_number,
            floor=floor,
            surface_m2=surface,
            bedrooms=bedrooms,
            price=price,
            status=dm.RealEstateLot.LotStatus.AVAILABLE,
        ))

    dm.RealEstateLot.objects.bulk_create(created)
    return len(created)


def _seed_admin_case(project: dm.Project, actor=None) -> int:
    """Crée un dossier administratif template."""
    if project.admin_cases.exists():
        return 0

    today = timezone.localdate()
    dm.AdminCase.objects.create(
        workspace=project.workspace,
        project=project,
        reference=f"DOSS-{today.year}-{project.pk:05d}",
        title=project.name[:200] if project.name else "Dossier",
        applicant="",
        document_type="",
        status=dm.AdminCase.CaseStatus.DRAFT,
        requested_at=today,
        sla_days=30,
        assignee=actor,
    )
    return 1


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------
_DISPATCH = {
    # Modes "agiles" : pipeline IA classique (sprints, backlog, tasks)
    # est suffisant — pas de post-processing additionnel.
    dm.Project.Methodology.SCRUM:           None,
    dm.Project.Methodology.KANBAN:          None,
    dm.Project.Methodology.AGILE:           None,
    dm.Project.Methodology.MILESTONE:       None,

    # Modes "non-logiciels" : on amorce les structures métier dédiées.
    dm.Project.Methodology.WATERFALL:       _seed_waterfall_phases,
    dm.Project.Methodology.FIELD:           _seed_field_report,
    dm.Project.Methodology.REAL_ESTATE:     _seed_real_estate_lots,
    dm.Project.Methodology.ADMINISTRATIVE:  _seed_admin_case,
}


class MethodologyPostProcessor:
    """
    Façade publique. Appelée en fin de pipeline Genesis ; safe si la
    méthodologie est inconnue ou si le post-processor échoue (log + continue).
    """

    @classmethod
    def run(cls, project: dm.Project, actor=None) -> dict:
        """
        Exécute le post-processor adapté à project.methodology.

        Retourne un dict de stats {key, count} utile pour le log et le
        message de retour utilisateur. Ne lève jamais — toute exception
        est capturée et loggée.
        """
        methodology = getattr(project, "methodology", None)
        if not methodology:
            return {}

        handler = _DISPATCH.get(methodology)
        if handler is None:
            return {"methodology": methodology, "items_created": 0,
                    "note": "no post-processing for this methodology"}

        try:
            count = handler(project, actor=actor) or 0
            return {
                "methodology": methodology,
                "items_created": count,
                "handler": handler.__name__,
            }
        except Exception as exc:
            logger.warning(
                "MethodologyPostProcessor failed for project %s (%s): %s",
                project.pk, methodology, exc,
            )
            return {
                "methodology": methodology,
                "items_created": 0,
                "error": str(exc),
            }
