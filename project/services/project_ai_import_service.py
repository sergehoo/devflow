from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from project import models as dm
from project.services.budget import ProjectBudgetService

User = get_user_model()


@dataclass
class ImportContext:
    workspace: dm.Workspace
    created_by: User
    owner: User | None = None
    product_manager: User | None = None


class ProjectAIImportService:
    """
    Service principal :
    1. reçoit un payload structuré produit par l'IA
    2. crée tous les objets projet
    3. calcule les liens financiers / KPI
    """

    @staticmethod
    def _d(value, default="0") -> Decimal:
        try:
            if value in [None, ""]:
                return Decimal(default)
            return Decimal(str(value))
        except Exception:
            return Decimal(default)

    @staticmethod
    def _parse_date(value):
        if not value:
            return None
        if hasattr(value, "year"):
            return value
        try:
            return timezone.datetime.fromisoformat(str(value)).date()
        except Exception:
            return None

    @staticmethod
    def _find_user_by_email(email: str | None):
        if not email:
            return None
        return User.objects.filter(email__iexact=email.strip()).first()

    @staticmethod
    def _get_or_create_team(workspace: dm.Workspace, name: str, team_type: str = dm.Team.TeamType.OTHER):
        if not name:
            return None
        team, _ = dm.Team.objects.get_or_create(
            workspace=workspace,
            name=name.strip(),
            defaults={"team_type": team_type or dm.Team.TeamType.OTHER},
        )
        return team

    @staticmethod
    def _get_or_create_cost_category(category_type: str, fallback_name: str):
        label_map = {
            dm.CostCategory.CategoryType.HUMAN: "Ressources humaines",
            dm.CostCategory.CategoryType.SOFTWARE: "Logiciels / Licences",
            dm.CostCategory.CategoryType.INFRA: "Infrastructure / Cloud",
            dm.CostCategory.CategoryType.EQUIPMENT: "Équipements",
            dm.CostCategory.CategoryType.SUBCONTRACT: "Sous-traitance",
            dm.CostCategory.CategoryType.TRAVEL: "Déplacements",
            dm.CostCategory.CategoryType.TRAINING: "Formation",
            dm.CostCategory.CategoryType.OTHER: fallback_name or "Autre",
        }
        name = label_map.get(category_type, fallback_name or "Autre")
        category, _ = dm.CostCategory.objects.get_or_create(
            name=name,
            defaults={"category_type": category_type or dm.CostCategory.CategoryType.OTHER},
        )
        return category

    @classmethod
    @transaction.atomic
    def import_from_structured_payload(cls, payload: dict[str, Any], context: ImportContext) -> dm.Project:
        project_data = payload.get("project", {})
        roadmap_data = payload.get("roadmap", {})
        milestones_data = payload.get("milestones", [])
        sprints_data = payload.get("sprints", [])
        features_data = payload.get("features", [])
        teams_data = payload.get("teams", [])
        budget_data = payload.get("budget", {})
        revenues_data = payload.get("revenues", [])
        kpis_data = payload.get("kpis", [])

        owner = cls._find_user_by_email(project_data.get("owner_email")) or context.owner or context.created_by
        pm = cls._find_user_by_email(project_data.get("product_manager_email")) or context.product_manager

        default_team = None
        if project_data.get("team"):
            default_team = cls._get_or_create_team(context.workspace, project_data["team"])

        project = dm.Project.objects.create(
            workspace=context.workspace,
            team=default_team,
            name=project_data.get("name") or "Projet importé",
            description=project_data.get("description", ""),
            tech_stack=", ".join(project_data.get("tech_stack", [])) if isinstance(project_data.get("tech_stack"), list) else project_data.get("tech_stack", ""),
            start_date=cls._parse_date(project_data.get("start_date")),
            target_date=cls._parse_date(project_data.get("target_date")),
            status=project_data.get("status") or dm.Project.Status.PLANNED,
            priority=project_data.get("priority") or dm.Project.Priority.MEDIUM,
            owner=owner,
            product_manager=pm,
        )

        # Équipes
        created_teams = {}
        for team_data in teams_data:
            team = cls._get_or_create_team(
                context.workspace,
                team_data.get("name"),
                team_data.get("team_type") or dm.Team.TeamType.OTHER,
            )
            if team:
                created_teams[team.name.lower()] = team

        # Roadmap
        roadmap = None
        if roadmap_data:
            roadmap = dm.Roadmap.objects.create(
                workspace=context.workspace,
                name=roadmap_data.get("name") or f"Roadmap {project.name}",
                description=roadmap_data.get("description", ""),
                start_date=cls._parse_date(roadmap_data.get("start_date")) or project.start_date or timezone.localdate(),
                end_date=cls._parse_date(roadmap_data.get("end_date")) or project.target_date or timezone.localdate(),
                owner=owner,
            )

            for row_index, item in enumerate(roadmap_data.get("items", [])):
                dm.RoadmapItem.objects.create(
                    roadmap=roadmap,
                    project=project,
                    title=item.get("title") or f"Phase {row_index + 1}",
                    status=item.get("status") or dm.RoadmapItem.ItemStatus.PLANNED,
                    start_date=cls._parse_date(item.get("start_date")) or roadmap.start_date,
                    end_date=cls._parse_date(item.get("end_date")) or roadmap.end_date,
                    row=item.get("row", row_index),
                )

        # Milestones
        milestones_by_name = {}
        for milestone_data in milestones_data:
            milestone = dm.Milestone.objects.create(
                workspace=context.workspace,
                project=project,
                name=milestone_data.get("name") or "Jalon",
                description=milestone_data.get("description", ""),
                due_date=cls._parse_date(milestone_data.get("due_date")) or project.target_date or timezone.localdate(),
                status=milestone_data.get("status") or dm.Milestone.Status.PLANNED,
                owner=owner,
            )
            milestones_by_name[milestone.name.lower()] = milestone

        # Sprints
        sprints_by_number = {}
        for sprint_data in sprints_data:
            sprint_team = None
            if sprint_data.get("team"):
                sprint_team = created_teams.get(str(sprint_data["team"]).lower()) or cls._get_or_create_team(
                    context.workspace,
                    sprint_data["team"],
                )

            sprint = dm.Sprint.objects.create(
                workspace=context.workspace,
                project=project,
                team=sprint_team,
                name=sprint_data.get("name") or f"Sprint {sprint_data.get('number', 1)}",
                number=int(sprint_data.get("number") or 1),
                goal=sprint_data.get("goal", ""),
                start_date=cls._parse_date(sprint_data.get("start_date")) or timezone.localdate(),
                end_date=cls._parse_date(sprint_data.get("end_date")) or timezone.localdate(),
                velocity_target=int(sprint_data.get("velocity_target") or 0),
            )
            sprints_by_number[sprint.number] = sprint

        # Features + backlog + tasks
        labor_category = cls._get_or_create_cost_category(dm.CostCategory.CategoryType.HUMAN, "Ressources humaines")

        for feature in features_data:
            sprint = sprints_by_number.get(int(feature.get("sprint_number") or 0))
            feature_team = None
            if feature.get("team"):
                feature_team = created_teams.get(str(feature["team"]).lower()) or cls._get_or_create_team(
                    context.workspace,
                    feature["team"],
                )

            epic = dm.BacklogItem.objects.create(
                workspace=context.workspace,
                project=project,
                sprint=sprint,
                title=feature.get("title") or feature.get("epic") or "Feature",
                description=feature.get("description", ""),
                item_type=dm.BacklogItem.ItemType.STORY,
                story_points=int(feature.get("story_points") or 0),
                reporter=context.created_by,
            )

            total_feature_cost = Decimal("0")
            total_feature_sale = Decimal("0")

            for task_data in feature.get("tasks", []):
                assignee = cls._find_user_by_email(task_data.get("assignee_email"))
                task = dm.Task.objects.create(
                    workspace=context.workspace,
                    project=project,
                    sprint=sprint,
                    backlog_item=epic,
                    title=task_data.get("title") or "Tâche",
                    description=task_data.get("description", ""),
                    estimate_hours=cls._d(task_data.get("estimate_hours")),
                    priority=task_data.get("priority") or dm.Task.Priority.MEDIUM,
                    assignee=assignee,
                    reporter=context.created_by,
                )

                cost_amount, sale_amount = ProjectBudgetService.estimate_task_costs(task)
                total_feature_cost += cost_amount
                total_feature_sale += sale_amount

                if cost_amount > 0:
                    hours = cls._d(task.estimate_hours)
                    cost_unit = (cost_amount / hours) if hours > 0 else Decimal("0")
                    markup = Decimal("0")
                    if cost_amount > 0 and sale_amount > cost_amount:
                        markup = ((sale_amount - cost_amount) / cost_amount) * Decimal("100")

                    dm.ProjectEstimateLine.objects.create(
                        project=project,
                        category=labor_category,
                        source_type=dm.ProjectEstimateLine.EstimationSource.TASK,
                        budget_stage=dm.ProjectEstimateLine.BudgetStage.ESTIMATED,
                        task=task,
                        sprint=sprint,
                        label=f"Tâche · {task.title}",
                        description=task.description or "",
                        quantity=hours,
                        cost_unit_amount=cost_unit,
                        markup_percent=markup,
                        created_by=context.created_by,
                    )

            # ligne feature agrégée
            if total_feature_cost > 0:
                dm.ProjectEstimateLine.objects.create(
                    project=project,
                    category=labor_category,
                    source_type=dm.ProjectEstimateLine.EstimationSource.MANUAL,
                    budget_stage=dm.ProjectEstimateLine.BudgetStage.BASELINE,
                    sprint=sprint,
                    label=f"Feature · {feature.get('title') or epic.title}",
                    description=f"Coût agrégé de la feature {epic.title}",
                    quantity=Decimal("1"),
                    cost_unit_amount=total_feature_cost,
                    markup_percent=Decimal("0") if total_feature_cost <= 0 else ((total_feature_sale - total_feature_cost) / total_feature_cost) * Decimal("100"),
                    created_by=context.created_by,
                )

        # Budget
        budget = dm.ProjectBudget.objects.create(
            project=project,
            status=budget_data.get("status") or dm.ProjectBudget.Status.ESTIMATED,
            currency=budget_data.get("currency") or "XOF",
            estimated_labor_cost=cls._d(budget_data.get("estimated_labor_cost")),
            estimated_software_cost=cls._d(budget_data.get("estimated_software_cost")),
            estimated_infra_cost=cls._d(budget_data.get("estimated_infra_cost")),
            estimated_subcontract_cost=cls._d(budget_data.get("estimated_subcontract_cost")),
            estimated_other_cost=cls._d(budget_data.get("estimated_other_cost")),
            contingency_amount=cls._d(budget_data.get("contingency_amount")),
            management_reserve_amount=cls._d(budget_data.get("management_reserve_amount")),
            markup_percent=cls._d(budget_data.get("markup_percent")),
            planned_revenue=cls._d(budget_data.get("planned_revenue")),
            approved_budget=cls._d(budget_data.get("approved_budget")),
            overhead_cost_amount=cls._d(budget_data.get("overhead_cost_amount")),
            tax_amount=cls._d(budget_data.get("tax_amount")),
            notes=budget_data.get("notes", ""),
        )

        # Revenus
        for revenue_data in revenues_data:
            dm.ProjectRevenue.objects.create(
                project=project,
                revenue_type=revenue_data.get("revenue_type") or dm.ProjectRevenue.RevenueType.FIXED,
                title=revenue_data.get("title") or "Prévision revenu",
                amount=cls._d(revenue_data.get("amount")),
                expected_date=cls._parse_date(revenue_data.get("expected_date")),
                currency=revenue_data.get("currency") or budget.currency,
            )

        # KPI en OKR
        if kpis_data:
            objective = dm.Objective.objects.create(
                workspace=context.workspace,
                owner=pm or owner,
                title=f"KPI projet · {project.name}",
                description="Objectifs de performance importés automatiquement",
                level=dm.Objective.Level.TEAM,
                status=dm.Objective.Status.ON_TRACK,
                start_date=project.start_date or timezone.localdate(),
                end_date=project.target_date or timezone.localdate(),
            )

            for kpi in kpis_data:
                dm.KeyResult.objects.create(
                    objective=objective,
                    title=kpi.get("label") or kpi.get("name") or "KPI",
                    result_type=dm.KeyResult.ResultType.CURRENCY if kpi.get("unit") == "XOF" else dm.KeyResult.ResultType.NUMBER,
                    target_value=cls._d(kpi.get("target_value")),
                    current_value=cls._d(kpi.get("current_value")),
                    unit=kpi.get("unit", ""),
                    owner=pm or owner,
                )

        # Refresh intelligent global
        ProjectBudgetService.refresh_project_financials(project=project, user=context.created_by, rebuild_budget=True)

        return project