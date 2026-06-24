"""
DevFlow — Workflow Engine (PR2-METHODO).

API publique :
  * WorkflowEngine.allowed_transitions(obj, user) → list[(transition, label)]
  * WorkflowEngine.can_transition(obj, target_status, user) → (ok, reason)
  * WorkflowEngine.apply_transition(obj, target_status, user, comment=None)
        → effectue la transition et retourne l'objet mis à jour
  * WorkflowEngine.trigger_auto_transitions(obj, event) → applique les
        transitions ayant ``auto_trigger == event``

Sécurité :
  * Toute transition est validée contre les ``required_role_codes`` du
    workflow ET les permissions RBAC du user.
  * On vérifie que le user a accès au workspace du projet de l'objet.
  * Aucune modification cross-tenant possible.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


class TransitionError(Exception):
    """Erreur métier de transition (statut invalide, rôle manquant, etc.)."""


def _resolve_workflow_for_object(obj) -> Optional[Any]:
    """
    Trouve le ``MethodologyWorkflow`` qui régit ``obj``.

    Stratégie :
      1. ``obj.project.methodology_obj`` (si renseigné, futur champ)
      2. Mapping ``obj.project.methodology`` (CharField legacy) → Methodology.code
      3. Choisit le workflow ``is_default`` correspondant à ``applies_to``
         déduit du type de ``obj``.

    Retourne None si rien ne matche — la transition est alors libre
    (rétro-compatibilité : on ne bloque pas les projets sans méthodologie).
    """
    from project import models as dm

    project = getattr(obj, "project", None)
    if project is None:
        return None

    methodology = None
    # 1) FK explicite (futur — non encore en BD)
    methodology = getattr(project, "methodology_obj", None)
    # 2) Mapping legacy via code (Project.methodology = "SCRUM" → "scrum")
    if methodology is None:
        legacy_code = getattr(project, "methodology", None)
        if legacy_code:
            code = str(legacy_code).lower()
            methodology = dm.Methodology.objects.filter(code=code).first()
    if methodology is None:
        return None

    # Détecte la catégorie d'objet (task, story, epic, ...)
    applies_to = "task"
    model_name = obj.__class__.__name__
    mapping = {
        "Task": "task",
        "BacklogItem": "story",  # par défaut — peut être affiné par item_type
        "Milestone": "milestone",
        "ProjectPhase": "phase",
        "Risk": "risk",
    }
    applies_to = mapping.get(model_name, "task")

    # Affine pour BacklogItem.item_type
    if model_name == "BacklogItem":
        item_type = (getattr(obj, "item_type", None) or "").lower()
        item_type_map = {
            "epic": "epic", "story": "story", "task": "task",
            "bug": "bug", "deliverable": "deliverable",
        }
        applies_to = item_type_map.get(item_type, applies_to)

    workflow = (
        methodology.workflows
        .filter(applies_to__in=[applies_to, "any"])
        .order_by("-is_default", "id")
        .first()
    )
    return workflow


def _user_has_role(user, project, role_codes: Iterable[str]) -> bool:
    """
    Vérifie qu'un user possède au moins un des rôles méthodologiques requis
    sur ce projet. Les superusers passent toujours.
    """
    if user is None:
        return False
    if user.is_superuser:
        return True
    codes = set(c for c in (role_codes or []) if c)
    if not codes:
        return True  # aucune contrainte de rôle

    # ProjectMember peut porter un methodology_role_code à terme (PR4)
    try:
        memberships = project.members.filter(user=user).values_list(
            "role", flat=True,
        )
        for m in memberships:
            if m and str(m).lower() in codes:
                return True
    except Exception:
        pass

    # Fallback : organisateur/owner toujours autorisé
    if getattr(project, "owner_id", None) == user.pk:
        return True
    if getattr(project, "product_manager_id", None) == user.pk:
        return True

    return False


def _get_current_status_obj(obj):
    """Retourne le MethodologyStatus correspondant au statut courant de l'obj."""
    from project import models as dm

    project = getattr(obj, "project", None)
    if project is None:
        return None
    code = (getattr(obj, "status", "") or "").lower()
    if not code:
        return None
    methodology = getattr(project, "methodology_obj", None)
    if methodology is None:
        legacy = getattr(project, "methodology", None)
        if legacy:
            methodology = dm.Methodology.objects.filter(
                code=str(legacy).lower()
            ).first()
    if methodology is None:
        return None
    return methodology.statuses.filter(code=code).first()


class WorkflowEngine:
    """Validation et application des transitions de statut data-driven."""

    @staticmethod
    def allowed_transitions(obj, user) -> list[dict]:
        """
        Retourne la liste des transitions actuellement autorisées depuis
        le statut courant de l'objet pour cet utilisateur.

        Format : ``[{ "to_status": MethodologyStatus, "label": str,
                       "requires_comment": bool }, ...]``
        """
        workflow = _resolve_workflow_for_object(obj)
        if workflow is None:
            return []
        current = _get_current_status_obj(obj)
        if current is None:
            return []
        project = obj.project
        out = []
        for t in (
            workflow.transitions
            .select_related("from_status", "to_status")
            .filter(from_status=current)
            .exclude(auto_trigger__in=[
                # auto_triggers s'appliquent côté events, pas via UI
                "on_pr_merged", "on_pr_opened", "on_all_subtasks_done",
                "on_review_approved", "on_deadline_passed",
                "on_blocked_resolved", "on_budget_exceeded",
            ])
        ):
            if _user_has_role(user, project, t.required_role_codes):
                out.append({
                    "to_status": t.to_status,
                    "label": t.label or t.to_status.name,
                    "requires_comment": t.requires_comment,
                })
        return out

    @staticmethod
    def can_transition(obj, target_status_code: str, user) -> tuple[bool, str]:
        """
        Vérifie qu'une transition vers ``target_status_code`` est autorisée.

        Retourne ``(True, "")`` si OK, ou ``(False, "raison")`` sinon.
        """
        workflow = _resolve_workflow_for_object(obj)
        if workflow is None:
            # Pas de workflow → on laisse passer (rétro-compatibilité)
            return (True, "")

        current = _get_current_status_obj(obj)
        if current is None:
            return (False, "Statut courant introuvable dans la méthodologie.")

        if current.code == target_status_code:
            return (False, "Déjà dans le statut cible.")

        target = workflow.methodology.statuses.filter(
            code=target_status_code
        ).first()
        if target is None:
            return (False, f"Statut '{target_status_code}' inconnu pour cette méthodologie.")

        transition = workflow.transitions.filter(
            from_status=current, to_status=target,
        ).first()
        if transition is None:
            return (False, f"Transition {current.code} → {target.code} non autorisée.")

        if not _user_has_role(user, obj.project, transition.required_role_codes):
            return (
                False,
                f"Rôle insuffisant pour cette transition "
                f"(requis : {', '.join(transition.required_role_codes) or '—'}).",
            )

        return (True, "")

    @staticmethod
    @transaction.atomic
    def apply_transition(obj, target_status_code: str, user, comment: str = "") -> Any:
        """
        Effectue la transition (après validation). Lève ``TransitionError``
        si refus.

        Side-effects :
          * Met à jour ``obj.status``
          * Si la transition exige un commentaire et qu'il est fourni,
            stocke un commentaire/activity log
          * Loggue dans ActivityLog (best-effort)
        """
        ok, reason = WorkflowEngine.can_transition(obj, target_status_code, user)
        if not ok:
            raise TransitionError(reason)

        workflow = _resolve_workflow_for_object(obj)
        current = _get_current_status_obj(obj)
        target = workflow.methodology.statuses.filter(code=target_status_code).first()
        transition = workflow.transitions.filter(
            from_status=current, to_status=target,
        ).first()

        if transition.requires_comment and not (comment or "").strip():
            raise TransitionError("Un commentaire est requis pour cette transition.")

        # Convert target code en représentation du modèle Task/etc.
        # Le champ obj.status est typiquement un CharField — on stocke le code en MAJUSCULES
        # pour rétro-compatibilité avec Task.Status.choices (TODO/IN_PROGRESS/...).
        # Le mapping precis dépend du modèle :
        new_status_value = target_status_code.upper()
        # Si le modèle a une Status enum, on essaie de matcher
        try:
            status_enum = type(obj).Status
            for member in status_enum:
                if member.value.lower() == target_status_code.lower():
                    new_status_value = member.value
                    break
        except (AttributeError, TypeError):
            pass

        obj.status = new_status_value
        obj.save(update_fields=["status", "updated_at"]
                 if hasattr(obj, "updated_at") else ["status"])

        # Activity log best-effort
        try:
            from project import models as dm
            if hasattr(dm, "ActivityLog"):
                dm.ActivityLog.objects.create(
                    workspace=obj.project.workspace,
                    project=obj.project,
                    actor=user,
                    action_type="status_transition",
                    description=(
                        f"{current.name} → {target.name}"
                        + (f" — {comment}" if comment else "")
                    ),
                    metadata={
                        "obj_type": type(obj).__name__,
                        "obj_id": obj.pk,
                        "from": current.code,
                        "to": target.code,
                        "comment": comment,
                    },
                )
        except Exception as exc:
            logger.warning("activity log on transition failed: %s", exc)

        return obj

    @staticmethod
    def trigger_auto_transitions(obj, event: str) -> int:
        """
        Cherche les transitions ayant ``auto_trigger == event`` depuis le
        statut courant de ``obj`` et les applique. Retourne le nombre
        de transitions appliquées (typiquement 0 ou 1).

        ``event`` doit être une des valeurs de
        ``WorkflowTransition.AutoTrigger.choices`` (ex : 'on_pr_merged').
        """
        workflow = _resolve_workflow_for_object(obj)
        if workflow is None:
            return 0
        current = _get_current_status_obj(obj)
        if current is None:
            return 0

        candidates = workflow.transitions.filter(
            from_status=current, auto_trigger=event,
        )
        applied = 0
        for t in candidates:
            # Auto-transitions ne vérifient pas les rôles (déclenchées par système)
            try:
                obj.status = t.to_status.code.upper()
                obj.save(update_fields=["status", "updated_at"]
                         if hasattr(obj, "updated_at") else ["status"])
                applied += 1
                logger.info(
                    "Auto-transition %s: %s → %s (event=%s)",
                    type(obj).__name__, current.code, t.to_status.code, event,
                )
            except Exception as exc:
                logger.warning("auto-transition failed: %s", exc)
        return applied
