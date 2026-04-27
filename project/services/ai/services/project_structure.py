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

        members_summary = []
        for m in project.members.select_related("user"):
            profile = getattr(m.user, "profile", None)
            members_summary.append(
                {
                    "user_email": m.user.email if m.user else "",
                    "user_label": str(m.user) if m.user else "",
                    "role": m.role,
                    "seniority": getattr(profile, "seniority", "") if profile else "",
                    "allocation_percent": m.allocation_percent,
                }
            )

        objectives = list(
            dm.Objective.objects.filter(workspace=project.workspace)
            .values_list("title", flat=True)[:5]
        )

        prompt_payload = {
            "project": {
                "name": project.name,
                "description": project.description,
                "tech_stack": project.tech_stack,
                "priority": project.priority,
                "status": project.status,
                "start_date": project.start_date.isoformat() if project.start_date else None,
                "target_date": project.target_date.isoformat() if project.target_date else None,
                "budget": str(project.budget) if project.budget else None,
            },
            "team": members_summary,
            "objectives_workspace": objectives,
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
        "Tu es un PMO senior + Tech Lead. À partir des informations projet, "
        "tu produis UNE structure exploitable dans DevFlow. Réponds STRICTEMENT en JSON valide, "
        "sans aucun texte hors JSON, avec la forme suivante :\n"
        "{\n"
        '  "summary": "string (synthèse 2-3 phrases)",\n'
        '  "risks": "string (risques principaux)",\n'
        '  "recommendations": ["string", ...],\n'
        '  "roadmap": [{"local_ref":"R1","title":"...","description":"...","start_date":"YYYY-MM-DD","end_date":"YYYY-MM-DD"}],\n'
        '  "milestones": [{"local_ref":"M1","title":"...","description":"...","due_date":"YYYY-MM-DD"}],\n'
        '  "sprints": [{"local_ref":"S1","title":"Sprint 1","start_date":"YYYY-MM-DD","end_date":"YYYY-MM-DD","velocity_target":20}],\n'
        '  "backlog": [{"local_ref":"B1","title":"...","description":"...","story_points":5}],\n'
        '  "tasks": [{\n'
        '     "local_ref":"T1","title":"...","description":"...","priority":"LOW|MEDIUM|HIGH|CRITICAL",\n'
        '     "complexity":"LOW|MEDIUM|HIGH","estimate_hours":8,"recommended_profile":"DEVELOPER|TECH_LEAD|...",\n'
        '     "recommended_assignee_email":"jane@x.com","sprint_ref":"S1","milestone_ref":"M1",\n'
        '     "depends_on_refs":["T0"], "acceptance_criteria":["..."]\n'
        "  }],\n"
        '  "dependencies": [{"from_ref":"T2","to_ref":"T1","type":"BLOCKS"}],\n'
        '  "assignments": [{"task_ref":"T1","user_email":"jane@x.com","reason":"..."}]\n'
        "}\n"
        "Couvre IMPÉRATIVEMENT toutes les phases : cadrage, conception fonctionnelle, "
        "architecture technique, design UI/UX, développement backend, développement frontend, "
        "intégrations, tests, sécurité, déploiement, documentation, recette utilisateur, "
        "maintenance initiale. Utilise les emails fournis pour les recommended_assignee_email."
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
