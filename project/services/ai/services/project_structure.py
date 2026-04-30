"""
Service IA : structuration automatique d'un projet.

Génère, à partir d'un Project fraîchement créé, une proposition complète
contenant :
- roadmap items (phases)
- milestones
- sprints
- backlog items
- tâches couvrant cadrage → conception → design → backend → frontend →
  intégrations → tests → sécurité → déploiement → documentation →
  recette → maintenance initiale
- dépendances entre tâches
- affectations recommandées en fonction des profils membres

La proposition est stockée dans ProjectAIProposal + ProjectAIProposalItem.
L'utilisateur valide ensuite manuellement avant application définitive.

Stratégie :
1. On essaie d'appeler le provider IA configuré (OpenAI/local).
2. Si l'IA répond, on parse le JSON et on instancie les items.
3. Si l'IA est indisponible OU répond mal, on retombe sur un squelette
   heuristique standard (12 phases × 3 tâches type), pour ne jamais bloquer
   l'utilisateur.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from project import models as dm
from project.services.ai.base import AIMessage
from project.services.ai.factory import get_ai_provider
from project.services.ai.openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)
User = get_user_model()


# =========================================================================
# Squelette heuristique : 13 phases standard d'un projet logiciel
# =========================================================================
DEFAULT_PHASES: list[dict[str, Any]] = [
    {
        "code": "CADRAGE",
        "name": "Cadrage projet",
        "duration_days": 5,
        "tasks": [
            ("Atelier de cadrage", "PM", 8, "MEDIUM"),
            ("Définition du périmètre fonctionnel", "PM", 8, "HIGH"),
            ("Identification des parties prenantes", "PM", 4, "MEDIUM"),
        ],
    },
    {
        "code": "CONCEPTION_FONC",
        "name": "Conception fonctionnelle",
        "duration_days": 8,
        "tasks": [
            ("Rédaction des user stories", "PRODUCT_OWNER", 16, "HIGH"),
            ("Définition des critères d'acceptation", "PRODUCT_OWNER", 8, "HIGH"),
            ("Validation fonctionnelle avec le métier", "PM", 4, "MEDIUM"),
        ],
    },
    {
        "code": "ARCHITECTURE",
        "name": "Architecture technique",
        "duration_days": 6,
        "tasks": [
            ("Définition de l'architecture cible", "TECH_LEAD", 16, "HIGH"),
            ("Choix de la stack technique", "TECH_LEAD", 8, "HIGH"),
            ("Schéma de base de données", "TECH_LEAD", 8, "HIGH"),
        ],
    },
    {
        "code": "DESIGN",
        "name": "Design UI/UX",
        "duration_days": 10,
        "tasks": [
            ("Wireframes des écrans clés", "DESIGNER", 16, "HIGH"),
            ("Maquettes haute fidélité", "DESIGNER", 24, "HIGH"),
            ("Design system & composants", "DESIGNER", 16, "MEDIUM"),
        ],
    },
    {
        "code": "BACKEND",
        "name": "Développement backend",
        "duration_days": 25,
        "tasks": [
            ("Mise en place du squelette backend", "DEVELOPER", 16, "HIGH"),
            ("Modèles de données et migrations", "DEVELOPER", 24, "HIGH"),
            ("API REST des entités principales", "DEVELOPER", 40, "HIGH"),
            ("Authentification et permissions", "DEVELOPER", 16, "HIGH"),
            ("Logique métier centrale", "DEVELOPER", 32, "HIGH"),
        ],
    },
    {
        "code": "FRONTEND",
        "name": "Développement frontend",
        "duration_days": 25,
        "tasks": [
            ("Setup frontend & routing", "DEVELOPER", 16, "MEDIUM"),
            ("Écrans d'authentification", "DEVELOPER", 16, "MEDIUM"),
            ("Écrans liste / détail principaux", "DEVELOPER", 32, "HIGH"),
            ("Formulaires de saisie", "DEVELOPER", 24, "HIGH"),
            ("Intégration des maquettes", "DEVELOPER", 24, "MEDIUM"),
        ],
    },
    {
        "code": "INTEGRATIONS",
        "name": "Intégrations tierces",
        "duration_days": 8,
        "tasks": [
            ("Intégration paiement / facturation", "DEVELOPER", 16, "HIGH"),
            ("Intégration emailing / notifications", "DEVELOPER", 8, "MEDIUM"),
            ("Webhooks et services externes", "DEVELOPER", 8, "MEDIUM"),
        ],
    },
    {
        "code": "TESTS",
        "name": "Tests automatisés",
        "duration_days": 8,
        "tasks": [
            ("Tests unitaires backend", "DEVELOPER", 16, "HIGH"),
            ("Tests d'intégration API", "DEVELOPER", 16, "HIGH"),
            ("Tests end-to-end frontend", "QA", 16, "HIGH"),
        ],
    },
    {
        "code": "SECURITE",
        "name": "Sécurité",
        "duration_days": 5,
        "tasks": [
            ("Audit de sécurité OWASP Top 10", "DEVOPS", 16, "HIGH"),
            ("Chiffrement et gestion des secrets", "DEVOPS", 8, "HIGH"),
            ("Revue des permissions et RBAC", "TECH_LEAD", 8, "HIGH"),
        ],
    },
    {
        "code": "DEPLOIEMENT",
        "name": "Déploiement",
        "duration_days": 5,
        "tasks": [
            ("Pipeline CI/CD", "DEVOPS", 16, "HIGH"),
            ("Configuration des environnements", "DEVOPS", 8, "HIGH"),
            ("Mise en production initiale", "DEVOPS", 8, "HIGH"),
        ],
    },
    {
        "code": "DOCUMENTATION",
        "name": "Documentation",
        "duration_days": 4,
        "tasks": [
            ("Documentation technique", "TECH_LEAD", 8, "MEDIUM"),
            ("Documentation utilisateur", "PRODUCT_OWNER", 8, "MEDIUM"),
            ("Manuel d'exploitation", "DEVOPS", 8, "MEDIUM"),
        ],
    },
    {
        "code": "RECETTE",
        "name": "Recette utilisateur",
        "duration_days": 6,
        "tasks": [
            ("Préparation des scénarios de recette", "QA", 8, "HIGH"),
            ("Recette avec le client / métier", "QA", 16, "HIGH"),
            ("Correction des anomalies recette", "DEVELOPER", 16, "HIGH"),
        ],
    },
    {
        "code": "MAINTENANCE",
        "name": "Maintenance initiale",
        "duration_days": 10,
        "tasks": [
            ("Support post-mise en production", "DEVELOPER", 16, "MEDIUM"),
            ("Monitoring et alerting", "DEVOPS", 8, "MEDIUM"),
            ("Itérations correctives", "DEVELOPER", 16, "MEDIUM"),
        ],
    },
]


@dataclass
class StructureGenerationResult:
    proposal: dm.ProjectAIProposal
    used_provider: str
    items_created: int


class ProjectAIStructureService:
    """Génération automatique d'une structure de projet."""

    @classmethod
    @transaction.atomic
    def generate_for_project(
        cls,
        project: dm.Project,
        triggered_by: User | None = None,
        use_ai: bool = True,
    ) -> StructureGenerationResult:
        """
        Point d'entrée principal. Crée (ou met à jour) une proposition IA
        pour ce projet.
        """
        proposal = dm.ProjectAIProposal.objects.create(
            project=project,
            workspace=project.workspace,
            status=dm.ProjectAIProposal.Status.GENERATING,
            triggered_by=triggered_by,
        )
        dm.ProjectAIProposalLog.objects.create(
            proposal=proposal,
            action=dm.ProjectAIProposalLog.Action.TRIGGERED,
            actor=triggered_by,
            message=f"Génération déclenchée pour le projet « {project.name} ».",
        )

        payload: dict[str, Any] | None = None
        used_provider = "heuristic"

        if use_ai:
            try:
                payload, used_provider = cls._call_ai(project, proposal)
            except Exception as exc:
                logger.exception("AI structuring failed: %s", exc)
                payload = None
                proposal.error_message = str(exc)[:1000]

        if not payload:
            payload = cls._heuristic_payload(project)
            used_provider = used_provider or "heuristic"

        proposal.raw_payload = payload
        proposal.used_provider = used_provider
        proposal.summary = (payload.get("summary") or "")[:5000]
        proposal.risks_summary = (payload.get("risks") or "")[:5000]
        proposal.recommendations = payload.get("recommendations") or []

        items_created = cls._instantiate_items(proposal, payload, project)

        proposal.status = dm.ProjectAIProposal.Status.READY
        proposal.save()

        dm.ProjectAIProposalLog.objects.create(
            proposal=proposal,
            action=dm.ProjectAIProposalLog.Action.GENERATED,
            actor=triggered_by,
            message=f"Proposition générée par {used_provider} ({items_created} items).",
        )

        return StructureGenerationResult(
            proposal=proposal,
            used_provider=used_provider,
            items_created=items_created,
        )

    # ---------------------------------------------------------------------
    # AI call
    # ---------------------------------------------------------------------
    @classmethod
    def _call_ai(cls, project: dm.Project, proposal: dm.ProjectAIProposal) -> tuple[dict, str]:
        provider = get_ai_provider()
        if not provider.is_available():
            return {}, "heuristic"

        # ── Pool de membres : ProjectMember + équipes contributrices ─────
        members_summary = []
        seen_user_ids = set()

        # 1) ProjectMembers explicites
        for m in project.members.select_related("user", "team"):
            if not m.user_id or m.user_id in seen_user_ids:
                continue
            seen_user_ids.add(m.user_id)
            profile = getattr(m.user, "profile", None)
            members_summary.append({
                "user_email": m.user.email,
                "user_label": (m.user.get_full_name() or m.user.username),
                "role": m.role or "",
                "seniority": getattr(profile, "seniority", "") if profile else "",
                "allocation_percent": m.allocation_percent or 0,
                "team": m.team.name if m.team_id else (project.team.name if project.team_id else ""),
                "capacity_hours_per_week": float(getattr(profile, "capacity_hours_per_week", 40) or 40) if profile else 40,
                "billable_rate_per_day": float(getattr(profile, "billable_rate_per_day", 0) or 0) if profile else 0,
            })

        # 2) Membres des équipes contributrices (Project.teams M2M)
        try:
            for tm in project.get_assignable_memberships():
                if tm.user_id in seen_user_ids:
                    continue
                seen_user_ids.add(tm.user_id)
                profile = getattr(tm.user, "profile", None)
                members_summary.append({
                    "user_email": tm.user.email,
                    "user_label": (tm.user.get_full_name() or tm.user.username),
                    "role": tm.role,
                    "seniority": getattr(profile, "seniority", "") if profile else "",
                    "allocation_percent": tm.current_load_percent or 0,
                    "team": tm.team.name if tm.team_id else "",
                    "capacity_hours_per_week": float(getattr(profile, "capacity_hours_per_week", 40) or 40) if profile else 40,
                    "billable_rate_per_day": float(getattr(profile, "billable_rate_per_day", 0) or 0) if profile else 0,
                })
        except Exception:
            pass

        # ── Contexte enrichi : équipes, objectifs, KPIs, budget existant
        teams_meta = []
        try:
            for t in project.teams.all():
                teams_meta.append({
                    "name": t.name,
                    "type": t.team_type,
                    "lead": (t.lead.get_full_name() or t.lead.username) if t.lead_id else "",
                    "velocity_target": t.velocity_target,
                    "color": t.color,
                })
        except Exception:
            pass

        objectives = list(
            dm.Objective.objects.filter(workspace=project.workspace)
            .values("title", "level", "status")[:8]
        )

        existing_milestones = list(
            project.milestones.filter(is_archived=False).values("name", "due_date")[:10]
        )
        existing_releases = list(
            project.releases.filter(is_archived=False).values("name", "released_at")[:10]
        )

        budget_obj = getattr(project, "budgetestimatif", None)
        budget_meta = None
        if budget_obj:
            budget_meta = {
                "currency": getattr(budget_obj, "currency", "XOF"),
                "amount": str(getattr(budget_obj, "amount", "") or ""),
                "markup_percent": str(getattr(budget_obj, "markup_percent", "") or ""),
            }

        # ── Workspace info pour ton PMO
        workspace = project.workspace

        prompt_payload = {
            "project": {
                "name": project.name,
                "code": project.code,
                "description": project.description or "",
                "tech_stack": project.tech_stack or "",
                "priority": project.priority,
                "status": project.status,
                "category": project.category.name if project.category_id else "",
                "start_date": project.start_date.isoformat() if project.start_date else None,
                "target_date": project.target_date.isoformat() if project.target_date else None,
                "budget": str(project.budget) if project.budget else None,
                "main_team": project.team.name if project.team_id else "",
                "owner": (project.owner.get_full_name() or project.owner.username) if project.owner_id else "",
                "product_manager": (project.product_manager.get_full_name() or project.product_manager.username) if project.product_manager_id else "",
            },
            "workspace": {
                "name": workspace.name,
                "currency": "XOF",
                "timezone": workspace.timezone,
                "quarter_label": workspace.quarter_label,
            },
            "contributing_teams": teams_meta,
            "team_pool": members_summary,
            "team_pool_size": len(members_summary),
            "objectives_workspace": objectives,
            "existing_milestones": [{"name": m["name"], "due_date": m["due_date"].isoformat() if m["due_date"] else None} for m in existing_milestones],
            "existing_releases": [{"name": r["name"], "released_at": r["released_at"].isoformat() if r["released_at"] else None} for r in existing_releases],
            "budget_meta": budget_meta,
        }

        proposal.prompt_snapshot = json.dumps(prompt_payload, ensure_ascii=False)[:8000]

        messages = [
            AIMessage(role="system", content=cls._SYSTEM_PROMPT),
            AIMessage(role="user", content=json.dumps(prompt_payload, ensure_ascii=False)),
        ]

        response = provider.generate(
            messages=messages,
            temperature=0.3,
            json_mode=provider.supports_json_mode(),
        )
        proposal.tokens_used = response.tokens_used or 0
        proposal.used_model = response.model or ""

        if isinstance(provider, OpenAIProvider):
            data = OpenAIProvider.parse_json(response)
        else:
            try:
                data = json.loads(response.text)
            except Exception:
                data = {}

        if not data or not isinstance(data, dict):
            return {}, provider.name

        return data, provider.name

    _SYSTEM_PROMPT = (
        "Tu es un Directeur PMO senior, certifié PMP + Scrum Master + SAFe Agilist, "
        "doublé d'un Tech Lead avec 15 ans d'expérience en delivery logiciel. "
        "Tu produis pour DevFlow une structure de projet PROFESSIONNELLE, exhaustive, "
        "calibrée comme un kick-off PMO réel — pas un brouillon générique.\n\n"

        "═══ EXIGENCES DE PROFONDEUR ═══\n"
        "Tu DOIS produire AU MINIMUM :\n"
        "  • 1 roadmap découpée en 3-6 phases stratégiques (Discovery, Design, "
        "    Build, Stabilisation, Go-Live, Hyper-care).\n"
        "  • 6 à 10 milestones avec des dates réalistes alignées sur start_date / target_date.\n"
        "  • 4 à 12 sprints de 2 semaines couvrant toute la période.\n"
        "  • 8 à 20 backlog items (epics / user stories) avec story_points, "
        "    description claire et critères d'acceptation Given/When/Then.\n"
        "  • 25 à 80 tâches granulaires (4-16h chacune) couvrant TOUTES les phases :\n"
        "    cadrage, ateliers fonctionnels, spécifications, architecture, modèle de "
        "    données, design UI/UX, prototypage, dev backend, dev frontend, "
        "    intégrations tierces, sécurité (OWASP), tests unitaires, tests "
        "    d'intégration, tests E2E, recette utilisateur, performance, "
        "    accessibilité, documentation technique, doc utilisateur, formation, "
        "    déploiement, monitoring, maintenance corrective initiale.\n"
        "  • Au moins 6 dépendances entre tâches (BLOCKS, RELATES_TO).\n"
        "  • Affectations ciblées : utilise EXCLUSIVEMENT les emails du `team_pool` "
        "    fourni en entrée. Choisis le membre dont le `role` ET la `seniority` "
        "    correspondent à la nature de la tâche : tâches lead/architecture → "
        "    SENIOR/LEAD/EXPERT, tâches QA → role=QA, etc. Équilibre la charge "
        "    (round-robin pondéré par allocation_percent).\n"
        "  • Au moins 5 risques projet typés avec sévérité (technique, planning, "
        "    sécurité, dépendance externe, ressources).\n"
        "  • 4 à 8 KPI projet mesurables (velocity, burn-down, lead time, "
        "    defect rate, customer satisfaction…).\n"
        "  • 2 à 4 OKR alignés sur les objectifs du workspace (si fournis).\n\n"

        "═══ FORMAT DE SORTIE — JSON STRICT ═══\n"
        "Réponds UNIQUEMENT en JSON valide, sans texte hors JSON, avec :\n"
        "{\n"
        '  "summary": "synthèse exécutive 4-6 phrases (objectif business, parties prenantes, livrables clés, risques majeurs, jalons critiques)",\n'
        '  "risks": "string descriptif",\n'
        '  "recommendations": ["actions PMO concrètes (gouvernance, comitologie, RAID log, communication, etc.)"],\n'
        '  "roadmap": [{"local_ref":"R1","title":"Phase Discovery","description":"...","start_date":"YYYY-MM-DD","end_date":"YYYY-MM-DD"}],\n'
        '  "milestones": [{"local_ref":"M1","title":"Cadrage validé","description":"livrables : note de cadrage, RACI, registre des risques v0","due_date":"YYYY-MM-DD"}],\n'
        '  "releases": [{"local_ref":"REL1","title":"v1.0 MVP","description":"...","released_at":"YYYY-MM-DD"}],\n'
        '  "sprints": [{"local_ref":"S1","title":"Sprint 1 — Cadrage","goal":"objectif sprint","start_date":"YYYY-MM-DD","end_date":"YYYY-MM-DD","velocity_target":20}],\n'
        '  "backlog": [{"local_ref":"B1","title":"Authentification SSO","description":"...","story_points":8,"acceptance_criteria":["Given un utilisateur ... When ... Then ..."],"item_type":"STORY"}],\n'
        '  "tasks": [{\n'
        '     "local_ref":"T1","title":"...","description":"contexte + livrable + done-when",\n'
        '     "priority":"LOW|MEDIUM|HIGH|CRITICAL",\n'
        '     "complexity":"LOW|MEDIUM|HIGH",\n'
        '     "estimate_hours":8,\n'
        '     "recommended_profile":"PM|TECH_LEAD|DEVELOPER|QA|DEVOPS|DESIGNER|ANALYST",\n'
        '     "recommended_assignee_email":"prenom@workspace.com",\n'
        '     "sprint_ref":"S1","milestone_ref":"M1","backlog_ref":"B1",\n'
        '     "depends_on_refs":["T0"],\n'
        '     "acceptance_criteria":["critère 1","critère 2"],\n'
        '     "tags":["backend","sécurité"]\n'
        "  }],\n"
        '  "dependencies": [{"from_ref":"T2","to_ref":"T1","type":"BLOCKS|RELATES_TO|DUPLICATES"}],\n'
        '  "assignments": [{"task_ref":"T1","user_email":"jane@x.com","reason":"justification courte (rôle + séniorité + charge)"}],\n'
        '  "risks": [{"title":"...","severity":"LOW|MEDIUM|HIGH|CRITICAL","probability":"LOW|MEDIUM|HIGH","mitigation":"...","owner_role":"PM|TECH_LEAD|..."}],\n'
        '  "kpis": [{"name":"Velocity","unit":"points/sprint","target":20,"frequency":"sprint"}],\n'
        '  "okrs": [{"objective":"Lancer le MVP en Q3","key_results":["KR1 : ...","KR2 : ..."]}],\n'
        '  "communication_plan": [{"audience":"COPIL","frequency":"bi-mensuelle","format":"comité de pilotage 1h"}]\n'
        "}\n\n"

        "═══ CONTRAINTES STRICTES ═══\n"
        "• Toutes les dates respectent project.start_date ≤ X ≤ project.target_date.\n"
        "• Toutes les tâches sont rattachées à un sprint ET un milestone (pas d'orphelin).\n"
        "• Une tâche estime_hours > 16h doit être un membre SENIOR/LEAD/EXPERT.\n"
        "• Chaque user_email DOIT exister dans `team_pool` — n'invente pas d'email.\n"
        "• Les acceptance_criteria utilisent le format Given/When/Then.\n"
        "• Le total des estimate_hours doit refléter la complexité du projet et "
        "  rester cohérent avec le budget si fourni (taux moyen ~ 1500 XOF/h).\n"
        "• Pas de doublon de local_ref. Pas d'auto-référence dans les dépendances.\n"
    )

    # ---------------------------------------------------------------------
    # Heuristique
    # ---------------------------------------------------------------------
    @classmethod
    def _heuristic_payload(cls, project: dm.Project) -> dict[str, Any]:
        start = project.start_date or timezone.localdate()
        target = project.target_date or (start + timedelta(days=120))

        members = list(project.members.select_related("user").all())
        # Map seniority/role → user (round-robin par profil)
        role_map: dict[str, list[User]] = {}
        for m in members:
            if not m.user:
                continue
            role = m.role.upper() if m.role else "DEVELOPER"
            role_map.setdefault(role, []).append(m.user)

        def pick_user(profile_hint: str) -> User | None:
            for key in [profile_hint, "DEVELOPER", "ANY"]:
                if key in role_map and role_map[key]:
                    return role_map[key][0]
            # fallback : premier membre dispo
            for users in role_map.values():
                if users:
                    return users[0]
            return None

        roadmap = []
        milestones = []
        sprints = []
        backlog = []
        tasks = []
        dependencies = []
        assignments = []

        cursor = start
        sprint_index = 1
        previous_task_ref: str | None = None

        for phase_index, phase in enumerate(DEFAULT_PHASES, start=1):
            phase_start = cursor
            phase_end = phase_start + timedelta(days=phase["duration_days"])

            roadmap_ref = f"R{phase_index}"
            roadmap.append(
                {
                    "local_ref": roadmap_ref,
                    "title": phase["name"],
                    "description": f"Phase {phase['code']} du projet {project.name}.",
                    "start_date": phase_start.isoformat(),
                    "end_date": phase_end.isoformat(),
                }
            )

            milestone_ref = f"M{phase_index}"
            milestones.append(
                {
                    "local_ref": milestone_ref,
                    "title": f"Fin de {phase['name']}",
                    "description": f"Livrables de la phase {phase['name']} validés.",
                    "due_date": phase_end.isoformat(),
                }
            )

            sprint_ref = f"S{sprint_index}"
            sprints.append(
                {
                    "local_ref": sprint_ref,
                    "title": f"Sprint {sprint_index} — {phase['name']}",
                    "start_date": phase_start.isoformat(),
                    "end_date": phase_end.isoformat(),
                    "velocity_target": 20,
                }
            )

            backlog_ref = f"B{phase_index}"
            backlog.append(
                {
                    "local_ref": backlog_ref,
                    "title": f"Epic · {phase['name']}",
                    "description": f"Ensemble des tâches de la phase {phase['name']}.",
                    "story_points": 13,
                }
            )

            for task_index, (title, profile, hours, priority) in enumerate(phase["tasks"], start=1):
                task_ref = f"T{phase_index}-{task_index}"
                user = pick_user(profile)
                assignee_email = user.email if user else ""

                tasks.append(
                    {
                        "local_ref": task_ref,
                        "title": title,
                        "description": f"{title} pour la phase « {phase['name']} ».",
                        "priority": priority,
                        "complexity": "MEDIUM",
                        "estimate_hours": hours,
                        "recommended_profile": profile,
                        "recommended_assignee_email": assignee_email,
                        "sprint_ref": sprint_ref,
                        "milestone_ref": milestone_ref,
                        "depends_on_refs": [previous_task_ref] if previous_task_ref else [],
                        "acceptance_criteria": [
                            "Livrable conforme à la définition de fait",
                            "Revue technique passée",
                        ],
                    }
                )
                if assignee_email:
                    assignments.append(
                        {
                            "task_ref": task_ref,
                            "user_email": assignee_email,
                            "reason": f"Profil {profile} disponible dans l'équipe.",
                        }
                    )
                if previous_task_ref:
                    dependencies.append(
                        {
                            "from_ref": task_ref,
                            "to_ref": previous_task_ref,
                            "type": "BLOCKS",
                        }
                    )
                previous_task_ref = task_ref

            cursor = phase_end
            sprint_index += 1

        return {
            "summary": (
                f"Structure heuristique générée pour « {project.name} » : "
                f"{len(roadmap)} phases, {len(sprints)} sprints, {len(tasks)} tâches."
            ),
            "risks": (
                "Heuristique générique : à raffiner par l'équipe selon le périmètre réel. "
                "Pensez à valider les dépendances avant application."
            ),
            "recommendations": [
                "Adapter les estimations selon la séniorité réelle de l'équipe",
                "Préciser les critères d'acceptation des tâches métier",
                "Ajouter les jalons contractuels client si pertinent",
            ],
            "roadmap": roadmap,
            "milestones": milestones,
            "sprints": sprints,
            "backlog": backlog,
            "tasks": tasks,
            "dependencies": dependencies,
            "assignments": assignments,
        }

    # ---------------------------------------------------------------------
    # Persist payload → items
    # ---------------------------------------------------------------------
    @classmethod
    def _instantiate_items(
        cls,
        proposal: dm.ProjectAIProposal,
        payload: dict[str, Any],
        project: dm.Project,
    ) -> int:
        ItemCls = dm.ProjectAIProposalItem
        Kind = ItemCls.Kind

        members = list(project.members.select_related("user"))
        email_to_user = {m.user.email.lower(): m.user for m in members if m.user and m.user.email}

        def parse_date(value):
            if not value:
                return None
            try:
                return timezone.datetime.fromisoformat(str(value)).date()
            except Exception:
                return None

        items: list[ItemCls] = []
        order = 0

        # Roadmap
        for ri in payload.get("roadmap", []) or []:
            order += 1
            items.append(
                ItemCls(
                    proposal=proposal,
                    kind=Kind.ROADMAP_ITEM,
                    local_ref=ri.get("local_ref", ""),
                    title=ri.get("title", "")[:200],
                    description=ri.get("description", ""),
                    start_date=parse_date(ri.get("start_date")),
                    end_date=parse_date(ri.get("end_date")),
                    order_index=order,
                    extra_payload=ri,
                )
            )

        # Milestones
        for mi in payload.get("milestones", []) or []:
            order += 1
            items.append(
                ItemCls(
                    proposal=proposal,
                    kind=Kind.MILESTONE,
                    local_ref=mi.get("local_ref", ""),
                    title=mi.get("title", "")[:200],
                    description=mi.get("description", ""),
                    end_date=parse_date(mi.get("due_date")),
                    order_index=order,
                    extra_payload=mi,
                )
            )

        # Sprints
        for si in payload.get("sprints", []) or []:
            order += 1
            items.append(
                ItemCls(
                    proposal=proposal,
                    kind=Kind.SPRINT,
                    local_ref=si.get("local_ref", ""),
                    title=si.get("title", "")[:200],
                    start_date=parse_date(si.get("start_date")),
                    end_date=parse_date(si.get("end_date")),
                    velocity_target=int(si.get("velocity_target") or 0),
                    order_index=order,
                    extra_payload=si,
                )
            )

        # Backlog
        for bi in payload.get("backlog", []) or []:
            order += 1
            items.append(
                ItemCls(
                    proposal=proposal,
                    kind=Kind.BACKLOG,
                    local_ref=bi.get("local_ref", ""),
                    title=bi.get("title", "")[:200],
                    description=bi.get("description", ""),
                    extra_payload=bi,
                    order_index=order,
                )
            )

        # Tasks
        for ti in payload.get("tasks", []) or []:
            order += 1
            assignee_email = (ti.get("recommended_assignee_email") or "").strip().lower()
            user = email_to_user.get(assignee_email) if assignee_email else None
            items.append(
                ItemCls(
                    proposal=proposal,
                    kind=Kind.TASK,
                    local_ref=ti.get("local_ref", ""),
                    title=ti.get("title", "")[:200],
                    description=ti.get("description", ""),
                    priority=str(ti.get("priority", "")).upper()[:20],
                    complexity=str(ti.get("complexity", "")).upper()[:20],
                    estimate_hours=Decimal(str(ti.get("estimate_hours") or 0)),
                    recommended_profile=str(ti.get("recommended_profile", ""))[:120],
                    recommended_assignee=user,
                    sprint_ref=str(ti.get("sprint_ref", ""))[:80],
                    milestone_ref=str(ti.get("milestone_ref", ""))[:80],
                    depends_on_refs=ti.get("depends_on_refs") or [],
                    acceptance_criteria=ti.get("acceptance_criteria") or [],
                    extra_payload=ti,
                    order_index=order,
                )
            )

        # Dependencies
        for di in payload.get("dependencies", []) or []:
            order += 1
            items.append(
                ItemCls(
                    proposal=proposal,
                    kind=Kind.DEPENDENCY,
                    local_ref=f"{di.get('from_ref','')}→{di.get('to_ref','')}",
                    title=f"Dépendance {di.get('from_ref','')} → {di.get('to_ref','')}",
                    extra_payload=di,
                    order_index=order,
                )
            )

        # Assignments
        for ai in payload.get("assignments", []) or []:
            order += 1
            email = (ai.get("user_email") or "").strip().lower()
            user = email_to_user.get(email)
            items.append(
                ItemCls(
                    proposal=proposal,
                    kind=Kind.ASSIGNMENT,
                    local_ref=ai.get("task_ref", ""),
                    title=f"Affectation {ai.get('task_ref','')} → {ai.get('user_email','')}",
                    description=ai.get("reason", ""),
                    recommended_assignee=user,
                    extra_payload=ai,
                    order_index=order,
                )
            )

        ItemCls.objects.bulk_create(items)
        return len(items)
