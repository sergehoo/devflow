"""
Service IA "Genesis" : crée un projet **complet et persisté en base** à
partir d'une simple paire (nom, description).

Différence avec ProjectAIStructureService (qui produit une *proposition* à
valider) :
- Genesis crée directement le Project + Roadmap + Sprints + Milestones +
  BacklogItems + Tasks + Dependencies, dans une transaction.
- Une ProjectAIProposal est aussi créée et marquée APPLIED, pour audit.
- Si l'IA est indisponible ou répond mal → fallback heuristique (13 phases
  standard), pour ne jamais bloquer l'utilisateur.

Workflow :
1. Demande à l'IA un payload structuré (roadmap, sprints, milestones,
   backlog, tasks).
2. Persiste un Project minimal.
3. Délègue la persistance des items à `ProposalApplyService.apply()`
   (déjà testé, idempotent, gère les contraintes uniques sprint number,
   les dépendances, etc.).
4. Déclenche un rafraîchissement budgétaire (TJM) via
   ProjectBudgetService.refresh_project_financials.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from project import models as dm
from project.services.ai.services.project_structure import (
    ProjectAIStructureService,
)
from project.services.ai.services.proposal_apply import ProposalApplyService
from project.services.budget import ProjectBudgetService

logger = logging.getLogger(__name__)
User = get_user_model()


@dataclass
class GenesisResult:
    project: dm.Project
    proposal: dm.ProjectAIProposal
    counts: dict
    used_provider: str


class ProjectGenesisService:
    """
    Crée un projet complet + sa structure à partir d'un nom et d'une
    description, en utilisant l'IA pour la planification.
    """

    @classmethod
    @transaction.atomic
    def create_project_from_brief(
        cls,
        *,
        workspace: dm.Workspace,
        name: str,
        description: str,
        owner: User,
        product_manager: User | None = None,
        priority: str = dm.Project.Priority.MEDIUM,
        team: dm.Team | None = None,
        start_date=None,
        target_date=None,
        budget=None,
        use_ai: bool = True,
        auto_apply: bool = True,
    ) -> GenesisResult:
        """
        Point d'entrée principal.

        - workspace : workspace cible (obligatoire)
        - name      : nom du projet (obligatoire)
        - description : brief libre fourni par l'utilisateur (obligatoire)
        - auto_apply: si True, applique directement la proposition au projet.
                      Si False, on s'arrête à la proposition (mode "preview").
        """
        name = (name or "").strip()
        description = (description or "").strip()
        if not name:
            raise ValueError("Le nom du projet est obligatoire.")
        if not description:
            raise ValueError("La description du projet est obligatoire (au moins 1 phrase).")

        start_date = start_date or timezone.localdate()
        target_date = target_date or (start_date + timedelta(days=120))

        # 1. Création du Project minimal
        project = dm.Project.objects.create(
            workspace=workspace,
            team=team,
            name=name,
            description=description,
            owner=owner,
            product_manager=product_manager or owner,
            priority=priority,
            status=dm.Project.Status.PLANNED,
            start_date=start_date,
            target_date=target_date,
            budget=budget,
        )

        # Le signal post_save Project peut auto-déclencher une proposition
        # via Celery — on vérifie qu'il n'y en a pas déjà une en cours
        # (idempotence).
        existing = dm.ProjectAIProposal.objects.filter(
            project=project,
            status__in=[
                dm.ProjectAIProposal.Status.PENDING,
                dm.ProjectAIProposal.Status.GENERATING,
                dm.ProjectAIProposal.Status.READY,
            ],
        ).first()

        if existing and existing.items.exists():
            proposal = existing
            used_provider = existing.used_provider or "heuristic"
        else:
            # 2. Génération synchrone (on veut un retour immédiat à l'utilisateur)
            result = ProjectAIStructureService.generate_for_project(
                project=project,
                triggered_by=owner,
                use_ai=use_ai,
            )
            proposal = result.proposal
            used_provider = result.used_provider

        # 3. Application immédiate si demandée
        counts = {}
        if auto_apply:
            # Marquer tous les items comme VALIDATED (création par IA = confiance)
            proposal.items.update(
                item_status=dm.ProjectAIProposalItem.ItemStatus.VALIDATED,
                edited_by=owner,
                edited_at=timezone.now(),
            )
            proposal.status = dm.ProjectAIProposal.Status.VALIDATED
            proposal.validated_by = owner
            proposal.validated_at = timezone.now()
            proposal.save(update_fields=[
                "status", "validated_by", "validated_at", "updated_at",
            ])

            try:
                counts = ProposalApplyService.apply(proposal, actor=owner)
            except Exception as exc:
                logger.exception("Genesis apply failed for project %s: %s", project.pk, exc)
                # On ne supprime PAS le projet : l'utilisateur peut quand même
                # éditer manuellement la proposition via le cockpit.
                counts = {"error": str(exc)}

            # 4. Refresh budgétaire (TJM members → estimated_labor_cost)
            try:
                ProjectBudgetService.refresh_project_financials(
                    project=project, user=owner, rebuild_budget=True
                )
            except Exception as exc:
                logger.warning("Genesis budget refresh failed: %s", exc)

            # 5. Log de l'action
            try:
                dm.ProjectAIProposalLog.objects.create(
                    proposal=proposal,
                    action=dm.ProjectAIProposalLog.Action.APPLIED,
                    actor=owner,
                    message="Projet créé en un clic via DevFlow Genesis (IA).",
                    payload=counts,
                )
            except Exception:
                pass

        return GenesisResult(
            project=project,
            proposal=proposal,
            counts=counts,
            used_provider=used_provider,
        )
