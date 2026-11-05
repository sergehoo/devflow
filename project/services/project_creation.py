"""
Création d'un projet — logique extraite telle quelle de ``ProjectCreateView``
pour être partagée avec l'API (frontend React). Aucune règle modifiée.
"""

from __future__ import annotations

import logging

from project import models as dm

logger = logging.getLogger(__name__)


def create_project_from_form(form, *, workspace, user):
    """Enregistre un ``ProjectForm`` valide. À appeler dans ``transaction.atomic``.

    Retourne ``(projet, messages_info)``.
    """
    infos: list[str] = []
    obj = form.save(commit=False)

    obj.workspace = workspace

    if not getattr(obj, "owner_id", None) and user is not None and user.is_authenticated:
        obj.owner = user

    if obj.progress_percent is None:
        obj.progress_percent = 0

    if hasattr(obj, "risk_score") and obj.risk_score is None:
        obj.risk_score = 0

    obj.save()
    form.save_m2m()

    # ── Multi-équipes : si pas d'équipe principale mais des
    # équipes contributrices, on prend la première comme principale.
    contributing_teams = list(obj.teams.all())
    if not obj.team_id and contributing_teams:
        obj.team = contributing_teams[0]
        obj.save(update_fields=["team", "updated_at"])

    # ── Auto-création des ProjectMember pour tous les membres
    # actifs des équipes contributrices. Le rôle est repris du
    # TeamMembership.role pour faciliter ensuite les affectations
    # IA selon profil.
    team_ids = {t.id for t in contributing_teams}
    if obj.team_id:
        team_ids.add(obj.team_id)
    if team_ids:
        memberships = dm.TeamMembership.objects.filter(
            workspace=obj.workspace,
            team_id__in=team_ids,
            status=dm.TeamMembership.Status.ACTIVE,
        ).select_related("user", "team")
        created_count = 0
        for m in memberships:
            _, created = dm.ProjectMember.objects.get_or_create(
                project=obj,
                user=m.user,
                defaults={
                    "team": m.team,
                    "role": m.get_role_display(),
                    "allocation_percent": 50,
                },
            )
            if created:
                created_count += 1
        if created_count:
            infos.append(f"{created_count} membre(s) d'équipe ajouté(s) automatiquement au projet.",
            )

    if hasattr(dm, "ProjectBudget"):
        dm.ProjectBudget.objects.get_or_create(
            project=obj,
            defaults={
                "status": dm.ProjectBudget.Status.DRAFT,
                "currency": "XOF",
            },
        )

    # PR4-METHODO : applique automatiquement la configuration
    # de la méthodologie choisie (statuts, rôles, cérémonies,
    # KPIs, artefacts, phases si Waterfall, etc.).
    # Best-effort : un échec ne doit pas bloquer la création.
    try:
        from project.services.ai.services.methodology_postprocess import (
            MethodologyPostProcessor,
        )
        result = MethodologyPostProcessor.run(obj, actor=user)
        if result.get("items_created"):
            infos.append(f"Configuration {obj.get_methodology_display()} appliquée : "
                f"{result['items_created']} élément(s) initialisé(s).",
            )
    except Exception as exc:
        logger.warning(
            "MethodologyPostProcessor failed for project %s: %s",
            obj.pk, exc,
        )

    return obj, infos
