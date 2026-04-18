from __future__ import annotations

from decimal import Decimal
from django.db import transaction
from django.utils.dateparse import parse_date

from project import models as dm


class ProjectImportMapper:
    @classmethod
    @transaction.atomic
    def import_to_workspace(cls, workspace, payload: dict, user=None) -> dm.Project:
        project_data = payload["project"]

        project = dm.Project.objects.create(
            workspace=workspace,
            name=project_data["name"],
            code=project_data.get("code") or "",
            description=project_data.get("description") or "",
            tech_stack=project_data.get("tech_stack") or "",
            status=project_data.get("status") or dm.Project.Status.PLANNED,
            priority=project_data.get("priority") or dm.Project.Priority.MEDIUM,
            start_date=parse_date(project_data["start_date"]) if project_data.get("start_date") else None,
            target_date=parse_date(project_data["target_date"]) if project_data.get("target_date") else None,
            owner=user if user and hasattr(dm.Project, "owner") else None,
            product_manager=user if user and hasattr(dm.Project, "product_manager") else None,
        )

        teams_map = {}
        for team_data in payload.get("teams", []):
            team, _ = dm.Team.objects.get_or_create(
                workspace=workspace,
                name=team_data["name"],
                defaults={
                    "description": team_data.get("mission") or "",
                    "team_type": team_data.get("team_type") or dm.Team.TeamType.OTHER,
                },
            )
            teams_map[team.name] = team

        milestones_map = {}
        for milestone_data in payload.get("milestones", []):
            milestone = dm.Milestone.objects.create(
                workspace=workspace,
                project=project,
                name=milestone_data["name"],
                description=milestone_data.get("description") or "",
                status=milestone_data.get("status") or dm.Milestone.Status.PLANNED,
                due_date=parse_date(milestone_data["due_date"]) if milestone_data.get("due_date") else project.target_date,
            )
            milestones_map[milestone.name] = milestone

        sprints_map = {}
        for i, sprint_data in enumerate(payload.get("sprints", []), start=1):
            team = teams_map.get(sprint_data.get("team_name"))
            sprint = dm.Sprint.objects.create(
                workspace=workspace,
                project=project,
                team=team,
                name=sprint_data["name"],
                number=i,
                goal=sprint_data.get("goal") or "",
                start_date=parse_date(sprint_data["start_date"]) if sprint_data.get("start_date") else project.start_date,
                end_date=parse_date(sprint_data["end_date"]) if sprint_data.get("end_date") else project.target_date,
            )
            sprints_map[sprint.name] = sprint

        features_map = {}
        for feature_data in payload.get("features", []):
            sprint = sprints_map.get(feature_data.get("sprint_name"))
            milestone = milestones_map.get(feature_data.get("milestone_name"))

            backlog = dm.BacklogItem.objects.create(
                workspace=workspace,
                project=project,
                sprint=sprint,
                title=feature_data["title"],
                description=feature_data.get("description") or "",
                item_type=dm.BacklogItem.ItemType.STORY,
            )
            features_map[backlog.title] = backlog

            if milestone:
                dm.MilestoneTask.objects.get_or_create(
                    milestone=milestone,
                    task=None,  # à gérer si tu veux lier plus tard via tâches
                )

        for task_data in payload.get("tasks", []):
            sprint = sprints_map.get(task_data.get("sprint_name"))
            backlog_item = features_map.get(task_data.get("feature_title"))
            team = teams_map.get(task_data.get("team_name"))

            task = dm.Task.objects.create(
                workspace=workspace,
                project=project,
                sprint=sprint,
                backlog_item=backlog_item,
                title=task_data["title"],
                description=task_data.get("description") or "",
                priority=task_data.get("priority") or dm.Task.Priority.MEDIUM,
                estimate_hours=task_data.get("estimate_hours"),
            )

        financials = payload.get("financials") or {}
        dm.ProjectBudget.objects.update_or_create(
            project=project,
            defaults={
                "status": dm.ProjectBudget.Status.ESTIMATED,
                "approved_budget": Decimal(str(financials.get("approved_budget") or 0)),
                "planned_revenue": Decimal(str(financials.get("planned_revenue") or 0)),
                "contingency_amount": Decimal(str(financials.get("contingency_amount") or 0)),
                "management_reserve_amount": Decimal(str(financials.get("management_reserve_amount") or 0)),
                "overhead_cost_amount": Decimal(str(financials.get("overhead_cost_amount") or 0)),
                "tax_amount": Decimal(str(financials.get("tax_amount") or 0)),
            },
        )

        return project