"""
Application d'une ProjectAIProposal validée → création des objets DevFlow
réels (Roadmap, Milestone, Sprint, BacklogItem, Task, TaskDependency,
TaskAssignment).

Idempotence : un item appliqué (status=APPLIED) n'est plus traité, et
porte l'id de l'objet métier créé (applied_object_id, applied_object_model).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from project import models as dm

logger = logging.getLogger(__name__)


class ProposalApplyService:

    @classmethod
    @transaction.atomic
    def apply(cls, proposal: dm.ProjectAIProposal, actor=None) -> dict:
        """
        Applique tous les items VALIDATED ou EDITED de la proposition.
        Items REJECTED ou PROPOSED ne sont pas appliqués.
        """
        if not proposal.is_editable and proposal.status != dm.ProjectAIProposal.Status.VALIDATED:
            raise ValueError(
                f"La proposition #{proposal.pk} n'est pas dans un état applicable."
            )

        Item = dm.ProjectAIProposalItem
        applicable_statuses = [Item.ItemStatus.VALIDATED, Item.ItemStatus.EDITED]
        items = proposal.items.filter(item_status__in=applicable_statuses)

        ref_index: dict[str, dict[str, Any]] = {}
        counts = {"roadmap": 0, "milestones": 0, "sprints": 0, "backlog": 0, "tasks": 0,
                  "dependencies": 0, "assignments": 0}

        # 1. Roadmap (un seul Roadmap pour tout le projet, items à l'intérieur)
        roadmap_items = items.filter(kind=Item.Kind.ROADMAP_ITEM)
        roadmap = None
        if roadmap_items.exists():
            roadmap = dm.Roadmap.objects.create(
                workspace=proposal.workspace,
                name=f"Roadmap · {proposal.project.name}",
                description=proposal.summary[:500],
                start_date=proposal.project.start_date or timezone.localdate(),
                end_date=proposal.project.target_date or (timezone.localdate() + timedelta(days=180)),
                owner=proposal.project.owner,
            )
            for ri in roadmap_items:
                obj = dm.RoadmapItem.objects.create(
                    roadmap=roadmap,
                    project=proposal.project,
                    title=ri.title or "Phase",
                    status=dm.RoadmapItem.ItemStatus.PLANNED,
                    start_date=ri.start_date or roadmap.start_date,
                    end_date=ri.end_date or roadmap.end_date,
                    row=ri.order_index,
                )
                ref_index[ri.local_ref] = {"model": "RoadmapItem", "id": obj.pk, "obj": obj}
                cls._mark_applied(ri, obj, actor)
                counts["roadmap"] += 1

        # 2. Milestones
        for mi in items.filter(kind=Item.Kind.MILESTONE):
            obj = dm.Milestone.objects.create(
                workspace=proposal.workspace,
                project=proposal.project,
                name=mi.title or "Jalon",
                description=mi.description,
                due_date=mi.end_date or (proposal.project.target_date or timezone.localdate()),
                status=dm.Milestone.Status.PLANNED,
                owner=proposal.project.owner,
            )
            ref_index[mi.local_ref] = {"model": "Milestone", "id": obj.pk, "obj": obj}
            cls._mark_applied(mi, obj, actor)
            counts["milestones"] += 1

        # 3. Sprints — on numérote séquentiellement en évitant les collisions
        existing_max = (
            dm.Sprint.objects.filter(project=proposal.project)
            .order_by("-number")
            .values_list("number", flat=True)
            .first()
            or 0
        )
        next_number = existing_max + 1
        for si in items.filter(kind=Item.Kind.SPRINT):
            obj = dm.Sprint.objects.create(
                workspace=proposal.workspace,
                project=proposal.project,
                name=si.title or f"Sprint {next_number}",
                number=next_number,
                start_date=si.start_date or (proposal.project.start_date or timezone.localdate()),
                end_date=si.end_date or (proposal.project.target_date or timezone.localdate()),
                velocity_target=si.velocity_target or 0,
                status=dm.Sprint.Status.PLANNED,
            )
            ref_index[si.local_ref] = {"model": "Sprint", "id": obj.pk, "obj": obj}
            cls._mark_applied(si, obj, actor)
            counts["sprints"] += 1
            next_number += 1

        # 4. Backlog items
        for bi in items.filter(kind=Item.Kind.BACKLOG):
            obj = dm.BacklogItem.objects.create(
                workspace=proposal.workspace,
                project=proposal.project,
                title=bi.title or "Backlog item",
                description=bi.description,
                item_type=dm.BacklogItem.ItemType.STORY,
                story_points=int(bi.extra_payload.get("story_points") or 0),
                reporter=actor or proposal.project.owner,
            )
            ref_index[bi.local_ref] = {"model": "BacklogItem", "id": obj.pk, "obj": obj}
            cls._mark_applied(bi, obj, actor)
            counts["backlog"] += 1

        # 5. Tasks
        for ti in items.filter(kind=Item.Kind.TASK):
            sprint = None
            milestone = None
            if ti.sprint_ref and ti.sprint_ref in ref_index:
                sprint = ref_index[ti.sprint_ref]["obj"] if ref_index[ti.sprint_ref]["model"] == "Sprint" else None
            if ti.milestone_ref and ti.milestone_ref in ref_index:
                milestone = ref_index[ti.milestone_ref]["obj"] if ref_index[ti.milestone_ref]["model"] == "Milestone" else None

            assignee = ti.recommended_assignee
            obj = dm.Task.objects.create(
                workspace=proposal.workspace,
                project=proposal.project,
                sprint=sprint,
                title=ti.title or "Tâche",
                description=ti.description,
                priority=ti.priority or dm.Task.Priority.MEDIUM,
                estimate_hours=ti.estimate_hours or Decimal("0"),
                assignee=assignee,
                reporter=actor or proposal.project.owner,
            )
            if milestone:
                # Lien M2M via MilestoneTask si le modèle l'expose
                try:
                    dm.MilestoneTask.objects.create(milestone=milestone, task=obj)
                except Exception:
                    pass

            ref_index[ti.local_ref] = {"model": "Task", "id": obj.pk, "obj": obj}
            cls._mark_applied(ti, obj, actor)
            counts["tasks"] += 1

        # 6. Dependencies (entre tâches déjà créées)
        for di in items.filter(kind=Item.Kind.DEPENDENCY):
            payload = di.extra_payload or {}
            from_ref = payload.get("from_ref")
            to_ref = payload.get("to_ref")
            from_obj = ref_index.get(from_ref, {}).get("obj") if from_ref else None
            to_obj = ref_index.get(to_ref, {}).get("obj") if to_ref else None
            if from_obj and to_obj and isinstance(from_obj, dm.Task) and isinstance(to_obj, dm.Task):
                try:
                    dep = dm.TaskDependency.objects.create(
                        from_task=from_obj,
                        to_task=to_obj,
                        dependency_type=payload.get("type", "BLOCKS"),
                    )
                    cls._mark_applied(di, dep, actor)
                    counts["dependencies"] += 1
                except Exception as exc:
                    logger.warning("Skip dependency %s → %s: %s", from_ref, to_ref, exc)

        # 7. Assignments (compléments)
        for ai in items.filter(kind=Item.Kind.ASSIGNMENT):
            payload = ai.extra_payload or {}
            task_ref = payload.get("task_ref")
            task_obj = ref_index.get(task_ref, {}).get("obj") if task_ref else None
            user = ai.recommended_assignee
            if task_obj and isinstance(task_obj, dm.Task) and user:
                try:
                    assignment = dm.TaskAssignment.objects.create(
                        task=task_obj,
                        user=user,
                        assigned_by=actor,
                        allocation_percent=100,
                    )
                    cls._mark_applied(ai, assignment, actor)
                    counts["assignments"] += 1
                except Exception as exc:
                    logger.warning("Skip assignment for task %s: %s", task_ref, exc)

        # Marque la proposition comme appliquée
        proposal.status = dm.ProjectAIProposal.Status.APPLIED
        proposal.applied_at = timezone.now()
        proposal.save(update_fields=["status", "applied_at", "updated_at"])

        dm.ProjectAIProposalLog.objects.create(
            proposal=proposal,
            action=dm.ProjectAIProposalLog.Action.APPLIED,
            actor=actor,
            message=f"Proposition appliquée : {counts}",
            payload=counts,
        )
        return counts

    @staticmethod
    def _mark_applied(item: dm.ProjectAIProposalItem, obj, actor) -> None:
        item.item_status = dm.ProjectAIProposalItem.ItemStatus.APPLIED
        item.applied_object_id = getattr(obj, "pk", None)
        item.applied_object_model = obj.__class__.__name__
        item.edited_by = item.edited_by or actor
        item.edited_at = item.edited_at or timezone.now()
        item.save(update_fields=[
            "item_status", "applied_object_id", "applied_object_model",
            "edited_by", "edited_at", "updated_at",
        ])
