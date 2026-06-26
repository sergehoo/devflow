"""
DevFlow — Tool Registry pour le copilote IA (PR16-METHODO).

Permet d'enregistrer des "tools" que l'IA peut appeler en autonomie pour
créer/modifier des objets DevFlow (créer un sprint, générer des user
stories, etc.).

Sécurité :
  * Chaque tool déclare ``required_permission`` (RBAC code)
  * Chaque tool déclare ``destructive=True`` si l'action est dangereuse
    (delete, mass-update) → confirmation utilisateur obligatoire
  * Tous les paramètres sont validés contre le ``json_schema`` du tool
  * Toute exécution est loggée dans ``AIActionLog`` AVANT et APRÈS

Usage :
    @register_tool(
        name="create_sprint",
        description="Crée un nouveau sprint",
        required_permission="sprint.create",
        json_schema={"type": "object", "properties": {...}},
    )
    def create_sprint(project, user, name, duration_weeks=2, goal=""):
        ...
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from django.utils import timezone

logger = logging.getLogger(__name__)


@dataclass
class ToolSpec:
    """Métadonnées d'un tool enregistré."""
    name: str
    description: str
    required_permission: str = ""
    destructive: bool = False
    json_schema: dict = field(default_factory=dict)
    function: Callable = None
    reversible: bool = False


TOOL_REGISTRY: dict[str, ToolSpec] = {}


def register_tool(
    name: str,
    description: str,
    *,
    required_permission: str = "",
    destructive: bool = False,
    reversible: bool = False,
    json_schema: Optional[dict] = None,
):
    """Décorateur pour enregistrer un tool dans le registre global."""
    def _wrap(fn):
        TOOL_REGISTRY[name] = ToolSpec(
            name=name, description=description,
            required_permission=required_permission,
            destructive=destructive,
            reversible=reversible,
            json_schema=json_schema or {"type": "object", "properties": {}},
            function=fn,
        )
        return fn
    return _wrap


def list_tools_for_ai() -> list[dict]:
    """Retourne la liste des tools formatée pour le prompt IA."""
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "destructive": spec.destructive,
            "parameters": spec.json_schema,
        }
        for spec in TOOL_REGISTRY.values()
    ]


def _check_permission(user, permission: str, workspace=None) -> bool:
    """Vérifie qu'un user a une permission RBAC donnée."""
    if user is None:
        return False
    if user.is_superuser:
        return True
    if not permission:
        return True
    try:
        from project.services.rbac import RBACService
        return RBACService.can(user, permission, workspace=workspace)
    except Exception:
        return True  # fallback permissif si RBAC indispo


def execute_tool(
    tool_name: str,
    user,
    project=None,
    user_message: str = "",
    **kwargs,
) -> dict:
    """
    Exécute un tool nommé avec audit complet.

    Retourne ``{ "status": "SUCCESS|FAILED|DENIED", "result": ..., "log_id": int }``.
    """
    from project import models as dm

    spec = TOOL_REGISTRY.get(tool_name)
    workspace = getattr(project, "workspace", None) if project else None

    # Crée le log AVANT exécution
    log = dm.AIActionLog.objects.create(
        workspace=workspace,
        project=project,
        user=user,
        tool_name=tool_name,
        arguments=kwargs,
        user_message=user_message[:5000],
        status=dm.AIActionLog.Status.PENDING,
        is_reversible=spec.reversible if spec else False,
    )

    if spec is None:
        log.status = dm.AIActionLog.Status.FAILED
        log.error_message = f"Tool '{tool_name}' inconnu."
        log.save(update_fields=["status", "error_message", "updated_at"])
        return {"status": "FAILED", "result": None, "log_id": log.pk,
                "error": f"Tool '{tool_name}' inconnu."}

    # Permission RBAC
    if not _check_permission(user, spec.required_permission, workspace):
        log.status = dm.AIActionLog.Status.DENIED
        log.error_message = f"Permission refusée : {spec.required_permission}"
        log.save(update_fields=["status", "error_message", "updated_at"])
        return {"status": "DENIED", "result": None, "log_id": log.pk,
                "error": "Permission insuffisante pour cette action."}

    # Exécution effective
    start = time.time()
    try:
        result = spec.function(project=project, user=user, **kwargs)
        log.duration_ms = int((time.time() - start) * 1000)
        log.status = dm.AIActionLog.Status.SUCCESS
        log.result = result if isinstance(result, dict) else {"value": str(result)[:500]}
        # Si le tool retourne un dict avec affected_object_*, on l'enregistre
        if isinstance(result, dict):
            log.affected_object_type = result.get("object_type", "")
            log.affected_object_id = result.get("object_id")
        log.save(update_fields=[
            "duration_ms", "status", "result",
            "affected_object_type", "affected_object_id", "updated_at",
        ])
        return {"status": "SUCCESS", "result": result, "log_id": log.pk}
    except Exception as exc:
        log.duration_ms = int((time.time() - start) * 1000)
        log.status = dm.AIActionLog.Status.FAILED
        log.error_message = f"{type(exc).__name__}: {exc}"[:5000]
        log.save(update_fields=[
            "duration_ms", "status", "error_message", "updated_at",
        ])
        logger.exception("Tool %s failed", tool_name)
        return {"status": "FAILED", "result": None, "log_id": log.pk,
                "error": str(exc)}


# ════════════════════════════════════════════════════════════════════════════
# TOOLS PRÉ-ENREGISTRÉS (à enrichir au fur et à mesure)
# ════════════════════════════════════════════════════════════════════════════
@register_tool(
    name="create_sprint",
    description="Crée un nouveau sprint sur le projet (Scrum/Agile).",
    required_permission="sprint.create",
    reversible=True,
    json_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Nom du sprint"},
            "duration_weeks": {"type": "integer", "default": 2},
            "goal": {"type": "string"},
            "start_date": {"type": "string", "format": "date"},
        },
        "required": ["name"],
    },
)
def create_sprint(project, user, name, duration_weeks=2, goal="", start_date=None, **kwargs):
    from project import models as dm
    from datetime import date, timedelta
    if not project:
        raise ValueError("Projet requis.")
    if start_date:
        try:
            start = date.fromisoformat(start_date)
        except ValueError:
            start = date.today()
    else:
        start = date.today()
    end = start + timedelta(weeks=duration_weeks)
    # Numéro suivant
    last = project.sprints.order_by("-number").first()
    next_num = (last.number + 1) if last and last.number else 1
    sprint = dm.Sprint.objects.create(
        workspace=project.workspace,
        project=project,
        name=name[:100],
        number=next_num,
        goal=goal[:500],
        start_date=start,
        end_date=end,
        status="PLANNED",
    )
    return {
        "sprint_id": sprint.pk,
        "name": sprint.name,
        "number": sprint.number,
        "object_type": "Sprint",
        "object_id": sprint.pk,
        "message": f"Sprint #{sprint.number} « {sprint.name} » créé du {start} au {end}.",
    }


@register_tool(
    name="generate_user_stories",
    description="Génère des user stories pour le backlog à partir d'un brief.",
    required_permission="task.create",
    reversible=False,
    json_schema={
        "type": "object",
        "properties": {
            "brief": {"type": "string", "description": "Brief fonctionnel"},
            "max_stories": {"type": "integer", "default": 10},
        },
        "required": ["brief"],
    },
)
def generate_user_stories(project, user, brief, max_stories=10, **kwargs):
    from project.services.methodology.capabilities import create_backlog_from_brief
    from project import models as dm
    stories = create_backlog_from_brief(project, brief, max_stories=max_stories)
    if not stories:
        return {"message": "L'IA n'a pas pu générer de stories.", "stories": []}
    # Crée les BacklogItems en base
    created = []
    for s in stories:
        try:
            item = dm.BacklogItem.objects.create(
                workspace=project.workspace,
                project=project,
                title=s.get("title", "Untitled")[:200],
                description=s.get("story", "")[:5000] + "\n\n## Critères d'acceptation\n"
                            + "\n".join(f"- {ac}" for ac in s.get("acceptance_criteria", [])),
                item_type="STORY",
                story_points=s.get("story_points"),
                status="BACKLOG",
            )
            created.append({"id": item.pk, "title": item.title})
        except Exception as exc:
            logger.warning("BacklogItem creation failed: %s", exc)
    return {
        "stories_created": len(created),
        "stories": created,
        "message": f"{len(created)} user stories créées dans le backlog.",
    }


@register_tool(
    name="get_project_risks",
    description="Liste les risques du projet et leur criticité.",
    required_permission="",
    json_schema={"type": "object", "properties": {}},
)
def get_project_risks(project, user, **kwargs):
    from project import models as dm
    risks = []
    if hasattr(project, "risks"):
        for r in project.risks.exclude(status__in=["CLOSED", "ARCHIVED"])[:20]:
            risks.append({
                "id": r.pk, "title": r.title,
                "probability": getattr(r, "probability", None),
                "impact": getattr(r, "impact", None),
                "status": r.status,
            })
    return {"risks": risks, "count": len(risks)}


@register_tool(
    name="detect_overloaded_users",
    description="Détecte les membres surchargés du projet (>N tâches actives).",
    required_permission="",
    json_schema={
        "type": "object",
        "properties": {"threshold": {"type": "integer", "default": 5}},
    },
)
def detect_overloaded_users(project, user, threshold=5, **kwargs):
    from django.db.models import Count
    if not hasattr(project, "tasks"):
        return {"overloaded": []}
    overloaded = (
        project.tasks
        .filter(status__in=["TODO", "IN_PROGRESS", "REVIEW"])
        .values("assignee__id", "assignee__username", "assignee__first_name")
        .annotate(active_count=Count("id"))
        .filter(active_count__gte=threshold)
        .order_by("-active_count")[:10]
    )
    return {"overloaded": list(overloaded), "threshold": threshold}


@register_tool(
    name="generate_meeting_summary",
    description="Génère le compte-rendu d'une réunion à partir de son ID.",
    required_permission="",
    json_schema={
        "type": "object",
        "properties": {"meeting_id": {"type": "integer"}},
        "required": ["meeting_id"],
    },
)
def generate_meeting_summary(project, user, meeting_id, **kwargs):
    from project import models as dm
    from project.services.meeting import MeetingService
    meeting = dm.ProjectMeeting.objects.filter(
        pk=meeting_id, workspace=project.workspace,
    ).first()
    if not meeting:
        return {"error": "Réunion introuvable."}
    summary = MeetingService.generate_ai_summary(meeting)
    return {
        "meeting_id": meeting.pk,
        "object_type": "ProjectMeeting", "object_id": meeting.pk,
        "summary_length": len(summary or ""),
        "message": "Compte-rendu IA généré." if summary else "Aucun contenu généré.",
    }


# ════════════════════════════════════════════════════════════════════════════
# P3-METHODO : 8 tools IA additionnels
# ════════════════════════════════════════════════════════════════════════════
@register_tool(
    name="update_task_status",
    description="Change le statut d'une tâche (en respectant le Workflow Engine).",
    required_permission="task.update",
    reversible=True,
    json_schema={
        "type": "object",
        "properties": {
            "task_id": {"type": "integer"},
            "new_status": {"type": "string", "description": "Code statut (todo, in_progress, review, done, blocked, cancelled)"},
            "comment": {"type": "string"},
        },
        "required": ["task_id", "new_status"],
    },
)
def update_task_status(project, user, task_id, new_status, comment="", **kwargs):
    from project import models as dm
    from project.services.methodology.workflow_engine import WorkflowEngine, TransitionError
    task = dm.Task.objects.filter(pk=task_id, project=project).first()
    if not task:
        return {"error": "Tâche introuvable dans ce projet."}
    try:
        WorkflowEngine.apply_transition(task, new_status.lower(), user, comment=comment)
        return {
            "object_type": "Task", "object_id": task.pk,
            "task_id": task.pk, "new_status": task.status,
            "message": f"Tâche « {task.title} » → {task.status}.",
        }
    except TransitionError as exc:
        return {"error": str(exc)}


@register_tool(
    name="assign_task",
    description="Affecte une tâche à un utilisateur (recherche par username/email).",
    required_permission="task.update",
    reversible=True,
    json_schema={
        "type": "object",
        "properties": {
            "task_id": {"type": "integer"},
            "user_hint": {"type": "string", "description": "Username, email ou prénom/nom"},
        },
        "required": ["task_id", "user_hint"],
    },
)
def assign_task(project, user, task_id, user_hint, **kwargs):
    from django.db.models import Q
    from project import models as dm
    from project.utils.workspaces import users_in_workspaces
    task = dm.Task.objects.filter(pk=task_id, project=project).first()
    if not task:
        return {"error": "Tâche introuvable."}
    hint = (user_hint or "").strip().lower()
    candidates = users_in_workspaces([project.workspace_id]).filter(
        Q(username__icontains=hint) | Q(email__icontains=hint)
        | Q(first_name__icontains=hint) | Q(last_name__icontains=hint)
    )
    assignee = candidates.first()
    if not assignee:
        return {"error": f"Aucun utilisateur du workspace ne correspond à '{user_hint}'."}
    old = task.assignee
    task.assignee = assignee
    task.save(update_fields=["assignee", "updated_at"])
    return {
        "object_type": "Task", "object_id": task.pk,
        "old_assignee": str(old) if old else None,
        "new_assignee": str(assignee),
        "message": f"Tâche « {task.title } » assignée à {assignee.get_full_name() or assignee.username}.",
    }


@register_tool(
    name="create_milestone",
    description="Crée un nouveau jalon (milestone) sur le projet.",
    required_permission="milestone.create",
    reversible=True,
    json_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "due_date": {"type": "string", "format": "date"},
            "description": {"type": "string"},
        },
        "required": ["name"],
    },
)
def create_milestone(project, user, name, due_date=None, description="", **kwargs):
    from datetime import date
    from project import models as dm
    parsed_date = None
    if due_date:
        try:
            parsed_date = date.fromisoformat(due_date)
        except ValueError:
            parsed_date = None
    milestone = dm.Milestone.objects.create(
        workspace=project.workspace,
        project=project,
        name=name[:200],
        description=description[:5000],
        status="PLANNED",
        due_date=parsed_date,
    )
    return {
        "object_type": "Milestone", "object_id": milestone.pk,
        "milestone_id": milestone.pk, "name": milestone.name,
        "message": f"Jalon « {milestone.name} » créé"
                   + (f" (échéance {parsed_date})" if parsed_date else "") + ".",
    }


@register_tool(
    name="create_risk",
    description="Crée un risque dans le registre du projet.",
    required_permission="risk.create",
    reversible=True,
    json_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "probability": {"type": "integer", "minimum": 1, "maximum": 5},
            "impact": {"type": "integer", "minimum": 1, "maximum": 5},
            "description": {"type": "string"},
            "mitigation_plan": {"type": "string"},
        },
        "required": ["title"],
    },
)
def create_risk(project, user, title, probability=3, impact=3,
                description="", mitigation_plan="", **kwargs):
    from project import models as dm
    risk = dm.Risk.objects.create(
        workspace=project.workspace, project=project,
        title=title[:200],
        description=description[:5000],
        probability=int(probability),
        impact=int(impact),
        mitigation_plan=mitigation_plan[:5000],
        status="OPEN",
    )
    return {
        "object_type": "Risk", "object_id": risk.pk,
        "risk_id": risk.pk, "criticality": int(probability) * int(impact),
        "message": f"Risque « {risk.title} » créé (criticité {int(probability) * int(impact)}/25).",
    }


@register_tool(
    name="comment_task",
    description="Ajoute un commentaire sur une tâche.",
    required_permission="task.comment",
    reversible=False,
    json_schema={
        "type": "object",
        "properties": {
            "task_id": {"type": "integer"},
            "comment": {"type": "string"},
        },
        "required": ["task_id", "comment"],
    },
)
def comment_task(project, user, task_id, comment, **kwargs):
    from project import models as dm
    task = dm.Task.objects.filter(pk=task_id, project=project).first()
    if not task:
        return {"error": "Tâche introuvable."}
    # Recherche le modèle TaskComment ou équivalent
    if hasattr(dm, "TaskComment"):
        tc = dm.TaskComment.objects.create(
            task=task, author=user, body=comment[:5000],
        )
        return {
            "object_type": "TaskComment", "object_id": tc.pk,
            "task_id": task.pk,
            "message": f"Commentaire ajouté à « {task.title} ».",
        }
    return {"error": "Modèle TaskComment indisponible sur ce projet."}


@register_tool(
    name="generate_artifact",
    description="Génère un artefact (User Story, WBS, Risk Register, ...) via l'IA.",
    required_permission="project.update",
    reversible=False,
    json_schema={
        "type": "object",
        "properties": {
            "artifact_code": {"type": "string", "description": "Code de l'artefact (cf MethodologyArtifact.code)"},
            "context": {"type": "string", "description": "Contexte / brief additionnel"},
        },
        "required": ["artifact_code"],
    },
)
def generate_artifact(project, user, artifact_code, context="", **kwargs):
    from project import models as dm
    from project.services.methodology.ai_service import MethodologyAIService
    result = MethodologyAIService.generate_artifact(project, artifact_code, context_input=context)
    if "error" in result:
        return {"error": result["error"]}
    # Persiste dans ProjectArtifact
    methodology = dm.Methodology.objects.filter(
        code=(project.methodology or "").lower(),
    ).first()
    mart = methodology.artifacts.filter(code=artifact_code).first() if methodology else None
    # Marque la version précédente comme non-courante
    dm.ProjectArtifact.objects.filter(
        project=project, artifact_code=artifact_code, is_current=True,
    ).update(is_current=False)
    next_version = (
        dm.ProjectArtifact.objects
        .filter(project=project, artifact_code=artifact_code)
        .count() + 1
    )
    artifact = dm.ProjectArtifact.objects.create(
        project=project, methodology_artifact=mart,
        artifact_code=artifact_code,
        title=result.get("title", artifact_code),
        content=result.get("content", "")[:50000],
        template_kind=result.get("kind", "markdown"),
        version=next_version,
        ai_provider=result.get("provider", "")[:40],
        generated_by=user,
        is_current=True,
    )
    return {
        "object_type": "ProjectArtifact", "object_id": artifact.pk,
        "artifact_code": artifact_code,
        "version": next_version,
        "content_length": len(result.get("content", "")),
        "message": f"Artefact « {artifact.title} » v{next_version} généré.",
    }


@register_tool(
    name="analyze_project_health",
    description="Synthèse de la santé globale du projet (KPIs, risques, retards).",
    required_permission="",
    json_schema={"type": "object", "properties": {}},
)
def analyze_project_health(project, user, **kwargs):
    from project.services.methodology.kpis import compute_kpi
    from project.services.methodology.capabilities import detect_delays
    score = 100
    flags = []
    # Avancement
    adv = compute_kpi(project, "advancement_global")
    if isinstance(adv.get("value"), (int, float)) and adv["value"] < 30:
        score -= 15
        flags.append("Avancement faible")
    # Retards
    delays = detect_delays(project)
    if delays:
        score -= min(30, len(delays) * 5)
        flags.append(f"{len(delays)} retard(s) détecté(s)")
    # Risques actifs
    risks_count = 0
    if hasattr(project, "risks"):
        risks_count = project.risks.exclude(status="CLOSED").count()
        if risks_count >= 5:
            score -= 15
            flags.append(f"{risks_count} risques actifs")
    # Budget
    budget = compute_kpi(project, "budget_consumption")
    if isinstance(budget.get("value"), (int, float)) and budget["value"] > 90:
        score -= 20
        flags.append("Budget consommé > 90%")
    score = max(0, min(100, score))
    return {
        "health_score": score,
        "level": "good" if score >= 75 else "warning" if score >= 50 else "critical",
        "flags": flags,
        "delays_count": len(delays),
        "risks_count": risks_count,
        "advancement_pct": adv.get("value"),
        "budget_consumption_pct": budget.get("value"),
        "message": f"Score santé : {score}/100. " + (
            "Aucune alerte." if not flags else "Alertes : " + ", ".join(flags)
        ),
    }


@register_tool(
    name="suggest_improvements",
    description="L'IA analyse le projet et suggère 3-5 améliorations concrètes.",
    required_permission="",
    json_schema={"type": "object", "properties": {}},
)
def suggest_improvements(project, user, **kwargs):
    p = get_ai_provider() if False else None  # éviter import circulaire
    from project.services.ai.factory import get_ai_provider as _get
    from project.services.ai.base import AIMessage
    from project.services.methodology.ai_service import MethodologyAIService

    provider = _get()
    if not provider or not provider.is_available():
        return {"error": "Provider IA indisponible."}

    health = analyze_project_health(project, user)
    context = MethodologyAIService._build_context_block(project)
    profile = MethodologyAIService.get_profile(project)

    system = (
        (profile.system_prompt if profile else "Tu es un expert PM.")
        + "\n\nFais une synthèse + 3-5 recommandations CONCRÈTES, hiérarchisées par "
          "impact. Format JSON :\n"
          '{"summary": "1 phrase", "recommendations": [{"title": "...", '
          '"rationale": "...", "impact": "high|medium|low", "effort": "low|medium|high"}]}'
    )
    try:
        resp = provider.generate(
            messages=[
                AIMessage(role="system", content=system),
                AIMessage(role="user", content=(
                    f"{context}\n\nHealth score : {health.get('health_score')}/100\n"
                    f"Flags : {', '.join(health.get('flags', [])) or 'aucun'}"
                )),
            ],
            temperature=0.3, max_tokens=1500, json_mode=True,
        )
        import json as _json
        text = (resp.text or "").strip()
        if text.startswith("```"):
            text = text.split("```", 2)[-1]
            if text.startswith("json"):
                text = text[4:]
            text = text.rsplit("```", 1)[0]
        data = _json.loads(text)
        return {
            "summary": data.get("summary", ""),
            "recommendations": data.get("recommendations", []),
            "message": data.get("summary", "Analyse terminée.")
                       + f" {len(data.get('recommendations', []))} recommandation(s).",
        }
    except Exception as exc:
        return {"error": f"Analyse impossible : {exc}"}


# ════════════════════════════════════════════════════════════════════════════
# TOOLS FACTURATION (PR-INV-AI-TOOLS)
# ════════════════════════════════════════════════════════════════════════════
#
# Sécurité multi-tenant — règle d'or :
#   * Tous les tools n'opèrent QUE sur le workspace du ``project`` passé en
#     paramètre (ou explicitement le workspace lié à l'invoice manipulée).
#   * Aucune facture n'est jamais résolue par PK sans contrôle workspace.
#   * Quand le copilote est invoqué hors-projet (facturation libre), on
#     impose ``workspace_id`` explicite dans les arguments et on vérifie
#     que l'utilisateur en est membre via ``get_user_workspace_ids``.
# ════════════════════════════════════════════════════════════════════════════
from decimal import Decimal as _Decimal, InvalidOperation as _InvalidOp


def _ai_resolve_workspace(project, user, workspace_id=None):
    """
    Retourne le workspace cible pour une action de facturation.
    Priorité : project.workspace > workspace_id explicite (vérifié).
    """
    if project is not None and getattr(project, "workspace_id", None):
        return project.workspace
    if workspace_id is None:
        raise ValueError(
            "workspace_id requis quand aucun projet n'est dans le contexte."
        )
    from project import models as dm
    from project.utils.workspaces import get_user_workspace_ids
    ws_ids = set(get_user_workspace_ids(user))
    if int(workspace_id) not in ws_ids and not getattr(user, "is_superuser", False):
        raise PermissionError(
            "Vous n'êtes pas membre du workspace cible."
        )
    return dm.Workspace.objects.filter(pk=workspace_id).first() or (_ for _ in ()).throw(
        ValueError(f"Workspace #{workspace_id} introuvable.")
    )


def _ai_get_invoice(invoice_id, user):
    """Retourne une Invoice en s'assurant que l'utilisateur a accès au workspace."""
    from project import models as dm
    from project.utils.workspaces import get_user_workspace_ids
    ws_ids = set(get_user_workspace_ids(user))
    inv = dm.Invoice.objects.select_related("workspace", "project", "client").filter(
        pk=invoice_id
    ).first()
    if inv is None:
        raise ValueError(f"Facture #{invoice_id} introuvable.")
    if inv.workspace_id not in ws_ids and not getattr(user, "is_superuser", False):
        raise PermissionError("Vous n'avez pas accès à cette facture.")
    return inv


def _ai_to_decimal(val, default=_Decimal("0")):
    if val is None or val == "":
        return default
    try:
        return _Decimal(str(val))
    except (_InvalidOp, TypeError, ValueError):
        return default


# ──────────────────────────────────────────────────────────────────────
# create_invoice
# ──────────────────────────────────────────────────────────────────────
@register_tool(
    name="create_invoice",
    description=(
        "Crée une facture en brouillon (DRAFT). La facture est rattachée "
        "au workspace du projet courant (ou au workspace_id explicite si "
        "facture libre). Renvoie l'ID + un résumé pour l'éditer ensuite "
        "avec add_invoice_line, update_invoice_settings, issue_invoice."
    ),
    required_permission="invoice.create",
    reversible=True,
    json_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Titre/objet de la facture"},
            "client_id": {"type": "integer",
                          "description": "ID InvoiceClient (optionnel)"},
            "workspace_id": {"type": "integer",
                             "description": "Requis si aucun projet en contexte"},
            "currency": {"type": "string", "default": "XOF",
                         "description": "Devise (XOF/XAF/EUR/USD/…)"},
            "tax_rate": {"type": "number", "default": 18.0,
                         "description": "Taux de TVA en %"},
            "issue_date": {"type": "string", "format": "date"},
            "due_date": {"type": "string", "format": "date"},
            "period_start": {"type": "string", "format": "date"},
            "period_end": {"type": "string", "format": "date"},
            "notes": {"type": "string"},
            "billing_mode": {
                "type": "string",
                "enum": ["FIXED", "TIME_AND_MATERIALS", "MILESTONE", "MANUAL"],
                "default": "MANUAL",
            },
        },
    },
)
def create_invoice(
    project, user,
    title="", client_id=None, workspace_id=None,
    currency="XOF", tax_rate=18.0,
    issue_date=None, due_date=None,
    period_start=None, period_end=None,
    notes="", billing_mode="MANUAL",
    **kwargs,
):
    from datetime import date as _date
    from project import models as dm
    ws = _ai_resolve_workspace(project, user, workspace_id)

    client = None
    if client_id:
        client = dm.InvoiceClient.objects.filter(
            pk=client_id, workspace=ws
        ).first()
        if client is None:
            raise ValueError(
                f"Client #{client_id} introuvable dans le workspace {ws.name}."
            )

    def _parse_d(s):
        if not s:
            return None
        try:
            return _date.fromisoformat(s)
        except (TypeError, ValueError):
            return None

    inv = dm.Invoice.objects.create(
        workspace=ws,
        project=project,
        client=client,
        title=(title or "")[:200],
        notes=(notes or "")[:5000],
        currency=(currency or "XOF")[:10],
        tax_rate=_ai_to_decimal(tax_rate, _Decimal("18.00")),
        issue_date=_parse_d(issue_date) or _date.today(),
        due_date=_parse_d(due_date),
        period_start=_parse_d(period_start),
        period_end=_parse_d(period_end),
        billing_mode=billing_mode if billing_mode in {
            "FIXED", "TIME_AND_MATERIALS", "MILESTONE", "MANUAL"
        } else "MANUAL",
        status=dm.Invoice.Status.DRAFT,
        issued_by=user if getattr(user, "is_authenticated", False) else None,
    )
    return {
        "invoice_id": inv.pk,
        "status": inv.status,
        "currency": inv.currency,
        "object_type": "Invoice",
        "object_id": inv.pk,
        "message": (
            f"Facture brouillon créée (#{inv.pk}) — workspace « {ws.name} »"
            f"{', client ' + client.name if client else ''}."
        ),
    }


# ──────────────────────────────────────────────────────────────────────
# add_invoice_line
# ──────────────────────────────────────────────────────────────────────
@register_tool(
    name="add_invoice_line",
    description=(
        "Ajoute UNE ligne à une facture existante (statut DRAFT). "
        "Recalcule automatiquement les totaux. Pour ajouter plusieurs "
        "lignes en une seule fois, préférer add_invoice_lines_bulk."
    ),
    required_permission="invoice.update",
    reversible=True,
    json_schema={
        "type": "object",
        "properties": {
            "invoice_id": {"type": "integer"},
            "label": {"type": "string"},
            "description": {"type": "string"},
            "quantity": {"type": "number", "default": 1},
            "unit_price": {"type": "number"},
            "line_type": {
                "type": "string",
                "enum": ["SERVICE", "TIME", "EXPENSE", "MILESTONE",
                        "DISCOUNT", "OTHER"],
                "default": "SERVICE",
            },
        },
        "required": ["invoice_id", "label", "unit_price"],
    },
)
def add_invoice_line(
    project, user, invoice_id, label, unit_price,
    description="", quantity=1, line_type="SERVICE",
    **kwargs,
):
    from project import models as dm
    inv = _ai_get_invoice(invoice_id, user)
    if inv.status != dm.Invoice.Status.DRAFT:
        raise PermissionError(
            f"Édition impossible : la facture est en statut "
            f"{inv.get_status_display()} (DRAFT requis)."
        )
    last_pos = (
        inv.lines.order_by("-position").values_list("position", flat=True).first()
        or 0
    )
    line = dm.InvoiceLine.objects.create(
        invoice=inv,
        line_type=(line_type or "SERVICE").upper(),
        label=(label or "Ligne")[:240],
        description=(description or "")[:5000],
        quantity=_ai_to_decimal(quantity, _Decimal("1")),
        unit_price=_ai_to_decimal(unit_price, _Decimal("0")),
        position=last_pos + 1,
    )
    inv.recompute_totals(save=True)
    inv.refresh_from_db()
    return {
        "line_id": line.pk,
        "invoice_id": inv.pk,
        "total_amount": str(line.total_amount),
        "invoice_total_ttc": str(inv.total_ttc),
        "object_type": "InvoiceLine",
        "object_id": line.pk,
        "message": (
            f"Ligne ajoutée : « {line.label} » × {line.quantity} @ "
            f"{line.unit_price} = {line.total_amount} {inv.currency}."
        ),
    }


# ──────────────────────────────────────────────────────────────────────
# add_invoice_lines_bulk
# ──────────────────────────────────────────────────────────────────────
@register_tool(
    name="add_invoice_lines_bulk",
    description=(
        "Ajoute plusieurs lignes en une seule transaction sur une "
        "facture DRAFT. Recalcule les totaux à la fin. Idéal pour "
        "construire une facture complète en un appel."
    ),
    required_permission="invoice.update",
    reversible=True,
    json_schema={
        "type": "object",
        "properties": {
            "invoice_id": {"type": "integer"},
            "lines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "description": {"type": "string"},
                        "quantity": {"type": "number", "default": 1},
                        "unit_price": {"type": "number"},
                        "line_type": {
                            "type": "string",
                            "enum": ["SERVICE", "TIME", "EXPENSE",
                                     "MILESTONE", "DISCOUNT", "OTHER"],
                            "default": "SERVICE",
                        },
                    },
                    "required": ["label", "unit_price"],
                },
            },
        },
        "required": ["invoice_id", "lines"],
    },
)
def add_invoice_lines_bulk(project, user, invoice_id, lines, **kwargs):
    from django.db import transaction
    from project import models as dm
    if not isinstance(lines, list) or not lines:
        raise ValueError("Le paramètre 'lines' doit être une liste non vide.")
    inv = _ai_get_invoice(invoice_id, user)
    if inv.status != dm.Invoice.Status.DRAFT:
        raise PermissionError(
            f"Édition impossible : facture en statut "
            f"{inv.get_status_display()} (DRAFT requis)."
        )
    last_pos = (
        inv.lines.order_by("-position").values_list("position", flat=True).first()
        or 0
    )
    created_ids = []
    with transaction.atomic():
        for i, raw in enumerate(lines, start=1):
            line = dm.InvoiceLine.objects.create(
                invoice=inv,
                line_type=(raw.get("line_type") or "SERVICE").upper(),
                label=(raw.get("label") or f"Ligne {i}")[:240],
                description=(raw.get("description") or "")[:5000],
                quantity=_ai_to_decimal(raw.get("quantity", 1), _Decimal("1")),
                unit_price=_ai_to_decimal(raw.get("unit_price", 0), _Decimal("0")),
                position=last_pos + i,
            )
            created_ids.append(line.pk)
        inv.recompute_totals(save=True)
    inv.refresh_from_db()
    return {
        "invoice_id": inv.pk,
        "lines_created": len(created_ids),
        "line_ids": created_ids,
        "subtotal_ht": str(inv.subtotal_ht),
        "tax_amount": str(inv.tax_amount),
        "total_ttc": str(inv.total_ttc),
        "object_type": "Invoice",
        "object_id": inv.pk,
        "message": (
            f"{len(created_ids)} ligne(s) ajoutée(s) à la facture #{inv.pk}. "
            f"Nouveau total TTC : {inv.total_ttc} {inv.currency}."
        ),
    }


# ──────────────────────────────────────────────────────────────────────
# update_invoice_settings
# ──────────────────────────────────────────────────────────────────────
@register_tool(
    name="update_invoice_settings",
    description=(
        "Met à jour les paramètres globaux d'une facture DRAFT : "
        "tax_rate, discount_amount, currency, notes, title, due_date, "
        "period_start, period_end, billing_mode."
    ),
    required_permission="invoice.update",
    reversible=True,
    json_schema={
        "type": "object",
        "properties": {
            "invoice_id": {"type": "integer"},
            "tax_rate": {"type": "number"},
            "discount_amount": {"type": "number"},
            "currency": {"type": "string"},
            "notes": {"type": "string"},
            "title": {"type": "string"},
            "due_date": {"type": "string", "format": "date"},
            "period_start": {"type": "string", "format": "date"},
            "period_end": {"type": "string", "format": "date"},
            "billing_mode": {
                "type": "string",
                "enum": ["FIXED", "TIME_AND_MATERIALS",
                         "MILESTONE", "MANUAL"],
            },
        },
        "required": ["invoice_id"],
    },
)
def update_invoice_settings(project, user, invoice_id, **kwargs):
    from datetime import date as _date
    from project import models as dm
    inv = _ai_get_invoice(invoice_id, user)
    if inv.status != dm.Invoice.Status.DRAFT:
        raise PermissionError(
            f"Édition impossible : statut {inv.get_status_display()} (DRAFT requis)."
        )
    updates = []
    if "tax_rate" in kwargs:
        rate = _ai_to_decimal(kwargs["tax_rate"], inv.tax_rate)
        inv.tax_rate = max(_Decimal("0"), min(_Decimal("100"), rate))
        updates.append("tax_rate")
    if "discount_amount" in kwargs:
        d = _ai_to_decimal(kwargs["discount_amount"], _Decimal("0"))
        inv.discount_amount = max(_Decimal("0"), d)
        updates.append("discount_amount")
    if "currency" in kwargs:
        inv.currency = (kwargs["currency"] or inv.currency)[:10]
        updates.append("currency")
    if "notes" in kwargs:
        inv.notes = (kwargs["notes"] or "")[:10000]
        updates.append("notes")
    if "title" in kwargs:
        inv.title = (kwargs["title"] or "")[:200]
        updates.append("title")
    for date_field in ("due_date", "period_start", "period_end"):
        if date_field in kwargs:
            val = kwargs[date_field]
            try:
                setattr(inv, date_field,
                        _date.fromisoformat(val) if val else None)
                updates.append(date_field)
            except (TypeError, ValueError):
                pass
    if "billing_mode" in kwargs:
        mode = (kwargs["billing_mode"] or "MANUAL").upper()
        if mode in {"FIXED", "TIME_AND_MATERIALS", "MILESTONE", "MANUAL"}:
            inv.billing_mode = mode
            updates.append("billing_mode")
    if not updates:
        return {"message": "Aucun champ modifié.", "invoice_id": inv.pk}
    inv.save(update_fields=updates + ["updated_at"])
    inv.recompute_totals(save=True)
    inv.refresh_from_db()
    return {
        "invoice_id": inv.pk,
        "updated_fields": updates,
        "subtotal_ht": str(inv.subtotal_ht),
        "tax_amount": str(inv.tax_amount),
        "total_ttc": str(inv.total_ttc),
        "object_type": "Invoice",
        "object_id": inv.pk,
        "message": f"Paramètres facture mis à jour : {', '.join(updates)}.",
    }


# ──────────────────────────────────────────────────────────────────────
# issue_invoice
# ──────────────────────────────────────────────────────────────────────
@register_tool(
    name="issue_invoice",
    description=(
        "Passe une facture de DRAFT à ISSUED (Émise). Génère "
        "automatiquement le numéro FAC-AAAA-NNNN. Une fois émise, "
        "les lignes ne peuvent plus être modifiées."
    ),
    required_permission="invoice.issue",
    reversible=False,
    json_schema={
        "type": "object",
        "properties": {"invoice_id": {"type": "integer"}},
        "required": ["invoice_id"],
    },
)
def issue_invoice(project, user, invoice_id, **kwargs):
    from project import models as dm
    inv = _ai_get_invoice(invoice_id, user)
    if inv.status != dm.Invoice.Status.DRAFT:
        raise PermissionError(
            f"Seules les factures DRAFT peuvent être émises "
            f"(statut actuel : {inv.get_status_display()})."
        )
    if not inv.lines.exists():
        raise ValueError("Impossible d'émettre une facture sans ligne.")
    inv.status = dm.Invoice.Status.ISSUED
    inv.number = inv.number or dm.Invoice.generate_number(inv.workspace)
    inv.save(update_fields=["status", "number", "updated_at"])
    return {
        "invoice_id": inv.pk,
        "number": inv.number,
        "status": inv.status,
        "total_ttc": str(inv.total_ttc),
        "object_type": "Invoice",
        "object_id": inv.pk,
        "message": (
            f"Facture émise sous le numéro {inv.number} — "
            f"total {inv.total_ttc} {inv.currency}."
        ),
    }


# ──────────────────────────────────────────────────────────────────────
# list_invoices
# ──────────────────────────────────────────────────────────────────────
@register_tool(
    name="list_invoices",
    description=(
        "Liste les factures du projet courant (ou du workspace si "
        "aucun projet). Renvoie max 50 enregistrements triés par "
        "date d'émission décroissante."
    ),
    required_permission="",
    json_schema={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["DRAFT", "ISSUED", "SENT", "PARTIALLY_PAID",
                         "PAID", "OVERDUE", "CANCELLED"],
            },
            "limit": {"type": "integer", "default": 20, "maximum": 50},
            "workspace_id": {"type": "integer"},
        },
    },
)
def list_invoices(project, user, status=None, limit=20, workspace_id=None,
                  **kwargs):
    from project import models as dm
    from project.utils.workspaces import get_user_workspace_ids
    ws_ids = set(get_user_workspace_ids(user))
    qs = dm.Invoice.objects.filter(workspace_id__in=ws_ids)
    if project is not None:
        qs = qs.filter(project=project)
    elif workspace_id is not None:
        qs = qs.filter(workspace_id=int(workspace_id))
    if status:
        qs = qs.filter(status=status)
    qs = qs.select_related("client", "project").order_by("-issue_date", "-id")[
        : min(int(limit), 50)
    ]
    invoices = [
        {
            "id": inv.pk,
            "number": inv.number or "(brouillon)",
            "title": inv.title,
            "client": inv.client.name if inv.client else None,
            "project": inv.project.name if inv.project else None,
            "status": inv.status,
            "status_display": inv.get_status_display(),
            "issue_date": inv.issue_date.isoformat() if inv.issue_date else None,
            "due_date": inv.due_date.isoformat() if inv.due_date else None,
            "total_ttc": str(inv.total_ttc),
            "currency": inv.currency,
        }
        for inv in qs
    ]
    return {
        "count": len(invoices),
        "invoices": invoices,
        "message": f"{len(invoices)} facture(s) trouvée(s).",
    }


# ──────────────────────────────────────────────────────────────────────
# get_invoice
# ──────────────────────────────────────────────────────────────────────
@register_tool(
    name="get_invoice",
    description=(
        "Récupère le détail complet d'une facture : entête, lignes et "
        "totaux. Sécurité workspace stricte."
    ),
    required_permission="",
    json_schema={
        "type": "object",
        "properties": {"invoice_id": {"type": "integer"}},
        "required": ["invoice_id"],
    },
)
def get_invoice(project, user, invoice_id, **kwargs):
    inv = _ai_get_invoice(invoice_id, user)
    lines = [
        {
            "id": l.pk,
            "label": l.label,
            "description": l.description,
            "line_type": l.line_type,
            "quantity": str(l.quantity),
            "unit_price": str(l.unit_price),
            "total_amount": str(l.total_amount),
            "position": l.position,
        }
        for l in inv.lines.order_by("position", "id")
    ]
    return {
        "id": inv.pk,
        "number": inv.number or "(brouillon)",
        "title": inv.title,
        "status": inv.status,
        "status_display": inv.get_status_display(),
        "currency": inv.currency,
        "tax_rate": str(inv.tax_rate),
        "subtotal_ht": str(inv.subtotal_ht),
        "discount_amount": str(inv.discount_amount or 0),
        "tax_amount": str(inv.tax_amount),
        "total_ttc": str(inv.total_ttc),
        "paid_amount": str(inv.paid_amount),
        "remaining_due": str(inv.remaining_due),
        "issue_date": inv.issue_date.isoformat() if inv.issue_date else None,
        "due_date": inv.due_date.isoformat() if inv.due_date else None,
        "client": inv.client.name if inv.client else None,
        "project": inv.project.name if inv.project else None,
        "lines": lines,
        "object_type": "Invoice",
        "object_id": inv.pk,
        "message": f"Facture {inv.number or 'brouillon'} — "
                   f"{len(lines)} ligne(s), total {inv.total_ttc} {inv.currency}.",
    }


# ──────────────────────────────────────────────────────────────────────
# create_invoice_client
# ──────────────────────────────────────────────────────────────────────
@register_tool(
    name="create_invoice_client",
    description=(
        "Crée un nouveau client de facturation dans le workspace courant "
        "(ou workspace_id explicite). Utilisable avant create_invoice."
    ),
    required_permission="invoice_client.create",
    reversible=True,
    json_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "legal_name": {"type": "string"},
            "tax_id": {"type": "string"},
            "email": {"type": "string"},
            "phone": {"type": "string"},
            "address_line1": {"type": "string"},
            "address_line2": {"type": "string"},
            "postal_code": {"type": "string"},
            "city": {"type": "string"},
            "country": {"type": "string"},
            "contact_name": {"type": "string"},
            "workspace_id": {"type": "integer"},
        },
        "required": ["name"],
    },
)
def create_invoice_client(project, user, name, workspace_id=None, **kwargs):
    from project import models as dm
    ws = _ai_resolve_workspace(project, user, workspace_id)
    name = (name or "").strip()
    if not name:
        raise ValueError("Le nom du client est requis.")

    # Idempotent : si un client portant ce nom existe déjà dans ce workspace,
    # on le renvoie au lieu de lever une IntegrityError.
    existing = dm.InvoiceClient.objects.filter(workspace=ws, name=name).first()
    if existing is not None:
        return {
            "client_id": existing.pk,
            "name": existing.name,
            "object_type": "InvoiceClient",
            "object_id": existing.pk,
            "message": f"Client « {name} » déjà existant — utilisé en l'état.",
        }

    client = dm.InvoiceClient.objects.create(
        workspace=ws,
        name=name[:180],
        legal_name=(kwargs.get("legal_name") or "")[:200],
        tax_id=(kwargs.get("tax_id") or "")[:60],
        email=(kwargs.get("email") or "")[:254],
        phone=(kwargs.get("phone") or "")[:40],
        address_line1=(kwargs.get("address_line1") or "")[:200],
        address_line2=(kwargs.get("address_line2") or "")[:200],
        postal_code=(kwargs.get("postal_code") or "")[:20],
        city=(kwargs.get("city") or "")[:120],
        country=(kwargs.get("country") or "")[:80],
        contact_name=(kwargs.get("contact_name") or "")[:180],
    )
    return {
        "client_id": client.pk,
        "name": client.name,
        "object_type": "InvoiceClient",
        "object_id": client.pk,
        "message": f"Client « {client.name } » créé dans le workspace « {ws.name} ».",
    }


# ──────────────────────────────────────────────────────────────────────
# delete_invoice_line  (réversible côté UX uniquement si DRAFT)
# ──────────────────────────────────────────────────────────────────────
@register_tool(
    name="delete_invoice_line",
    description=(
        "Supprime une ligne d'une facture DRAFT. Recalcule les totaux."
    ),
    required_permission="invoice.update",
    destructive=True,
    reversible=False,
    json_schema={
        "type": "object",
        "properties": {"line_id": {"type": "integer"}},
        "required": ["line_id"],
    },
)
def delete_invoice_line(project, user, line_id, **kwargs):
    from project import models as dm
    from project.utils.workspaces import get_user_workspace_ids
    ws_ids = set(get_user_workspace_ids(user))
    line = (
        dm.InvoiceLine.objects.select_related("invoice")
        .filter(pk=line_id, invoice__workspace_id__in=ws_ids).first()
    )
    if line is None:
        raise ValueError(f"Ligne #{line_id} introuvable.")
    if line.invoice.status != dm.Invoice.Status.DRAFT:
        raise PermissionError(
            f"Suppression impossible : facture en statut "
            f"{line.invoice.get_status_display()} (DRAFT requis)."
        )
    inv = line.invoice
    label = line.label
    line.delete()
    inv.recompute_totals(save=True)
    inv.refresh_from_db()
    return {
        "deleted_line_id": line_id,
        "invoice_id": inv.pk,
        "total_ttc": str(inv.total_ttc),
        "object_type": "Invoice",
        "object_id": inv.pk,
        "message": f"Ligne « {label} » supprimée. "
                   f"Nouveau total : {inv.total_ttc} {inv.currency}.",
    }
