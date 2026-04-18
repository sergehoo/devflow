from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum, Q
from django.utils import timezone

from project import models as dm


class ProjectBudgetService:
    DEFAULT_WORKING_DAYS_PER_MONTH = Decimal("22")
    DEFAULT_HOURS_PER_DAY = Decimal("8")

    # =========================================================================
    # HELPERS
    # =========================================================================
    @staticmethod
    def _safe_decimal(value, default="0"):
        try:
            if value is None:
                return Decimal(default)
            return Decimal(str(value))
        except Exception:
            return Decimal(default)

    @classmethod
    def _get_hours_per_day(cls, user):
        profile = getattr(user, "profile", None)
        if profile and getattr(profile, "capacity_hours_per_day", None):
            hours = cls._safe_decimal(profile.capacity_hours_per_day, "8")
            return hours if hours > 0 else cls.DEFAULT_HOURS_PER_DAY
        return cls.DEFAULT_HOURS_PER_DAY

    @classmethod
    def get_member_daily_cost(cls, user):
        return dm.BillingRate.get_user_daily_cost(user)

    @classmethod
    def get_member_daily_sale_rate(cls, user):
        return dm.BillingRate.get_user_sale_daily_rate(user)

    # =========================================================================
    # ESTIMATION RH / TASKS
    # =========================================================================
    @classmethod
    def estimate_task_costs(cls, task):
        """
        Estimation coût / vente d'une tâche basée sur :
        - assignee principal
        - estimate_hours
        """
        if not task.assignee or not task.estimate_hours:
            return Decimal("0"), Decimal("0")

        hours = cls._safe_decimal(task.estimate_hours)
        if hours <= 0:
            return Decimal("0"), Decimal("0")

        hours_per_day = cls._get_hours_per_day(task.assignee)
        if hours_per_day <= 0:
            hours_per_day = cls.DEFAULT_HOURS_PER_DAY

        estimated_days = hours / hours_per_day

        daily_cost = cls.get_member_daily_cost(task.assignee)
        daily_sale = cls.get_member_daily_sale_rate(task.assignee)

        cost_amount = estimated_days * daily_cost
        sale_amount = estimated_days * daily_sale
        return cost_amount, sale_amount

    @classmethod
    def estimate_task_remaining_costs(cls, task):
        """
        Estimation du reste à faire sur une tâche.
        Avec les modèles actuels, on calcule :
        remaining_hours = estimate_hours - spent_hours
        """
        if not task.assignee:
            return Decimal("0"), Decimal("0")

        estimate_hours = cls._safe_decimal(task.estimate_hours)
        spent_hours = cls._safe_decimal(task.spent_hours)
        remaining_hours = max(estimate_hours - spent_hours, Decimal("0"))

        if remaining_hours <= 0:
            return Decimal("0"), Decimal("0")

        hours_per_day = cls._get_hours_per_day(task.assignee)
        if hours_per_day <= 0:
            hours_per_day = cls.DEFAULT_HOURS_PER_DAY

        remaining_days = remaining_hours / hours_per_day

        daily_cost = cls.get_member_daily_cost(task.assignee)
        daily_sale = cls.get_member_daily_sale_rate(task.assignee)

        return remaining_days * daily_cost, remaining_days * daily_sale

    @classmethod
    def estimate_project_members_costs(cls, project):
        """
        Estimation RH théorique basée sur les membres projet.
        Si start_date / target_date existent, allocation sur la durée.
        Sinon, base minimale = 1 jour.
        """
        total_cost = Decimal("0")
        total_sale = Decimal("0")

        members = project.members.select_related("user", "team")

        if project.start_date and project.target_date:
            total_days = (project.target_date - project.start_date).days + 1
            total_days = max(total_days, 1)
            working_days = Decimal(str(max(round(total_days * 5 / 7), 1)))
        else:
            working_days = Decimal("1")

        for member in members:
            allocation = Decimal(str(member.allocation_percent or 0)) / Decimal("100")
            allocated_days = working_days * allocation

            daily_cost = cls.get_member_daily_cost(member.user)
            daily_sale = cls.get_member_daily_sale_rate(member.user)

            total_cost += allocated_days * daily_cost
            total_sale += allocated_days * daily_sale

        return total_cost, total_sale

    # =========================================================================
    # TIMESHEETS
    # =========================================================================
    @classmethod
    def summarize_timesheets(cls, project):
        """
        Temps réel consommé via timesheets.
        Modèles actuels :
        - pas de approval_status
        - pas de computed_sale_amount dans TimesheetCostSnapshot
        """
        qs = project.timesheet_entries.all()

        total_hours = cls._safe_decimal(
            qs.aggregate(total=Sum("hours"))["total"]
        )

        approved_hours = cls._safe_decimal(
            qs.filter(approved_at__isnull=False).aggregate(total=Sum("hours"))["total"]
        )

        logged_cost = cls._safe_decimal(
            qs.aggregate(total=Sum("cost_snapshot__computed_cost"))["total"]
        )

        approved_logged_cost = cls._safe_decimal(
            qs.filter(approved_at__isnull=False).aggregate(total=Sum("cost_snapshot__computed_cost"))["total"]
        )

        return {
            "total_hours": total_hours,
            "approved_hours": approved_hours,
            "logged_cost": logged_cost,
            "approved_logged_cost": approved_logged_cost,
            "logged_sale": Decimal("0"),
            "approved_logged_sale": Decimal("0"),
        }

    # =========================================================================
    # ESTIMATE LINES
    # =========================================================================
    @classmethod
    def summarize_estimate_lines(cls, project):
        """
        Synthèse lignes d'estimation.
        Modèles actuels :
        - pas de budget_stage
        """
        qs = project.estimate_lines.select_related("category")

        total_cost = cls._safe_decimal(qs.aggregate(total=Sum("cost_amount"))["total"])
        total_sale = cls._safe_decimal(qs.aggregate(total=Sum("sale_amount"))["total"])

        labor_cost = Decimal("0")
        direct_cost = Decimal("0")
        other_cost = Decimal("0")
        raf_cost = Decimal("0")

        for line in qs:
            amount = cls._safe_decimal(line.cost_amount)
            category_type = getattr(line.category, "category_type", None)

            if line.task_id:
                task = line.task
                if task and task.status not in [dm.Task.Status.DONE, dm.Task.Status.CANCELLED]:
                    estimate_hours = cls._safe_decimal(task.estimate_hours)
                    spent_hours = cls._safe_decimal(task.spent_hours)
                    if estimate_hours > spent_hours:
                        remaining_ratio = (estimate_hours - spent_hours) / estimate_hours if estimate_hours > 0 else Decimal("0")
                        raf_cost += amount * remaining_ratio

            if category_type == dm.CostCategory.CategoryType.HUMAN:
                labor_cost += amount
            elif category_type in {
                dm.CostCategory.CategoryType.SOFTWARE,
                dm.CostCategory.CategoryType.INFRA,
                dm.CostCategory.CategoryType.EQUIPMENT,
                dm.CostCategory.CategoryType.SUBCONTRACT,
                dm.CostCategory.CategoryType.TRAVEL,
                dm.CostCategory.CategoryType.TRAINING,
            }:
                direct_cost += amount
            else:
                other_cost += amount

        return {
            "total_cost": total_cost,
            "total_sale": total_sale,
            "estimated_cost": total_cost,
            "baseline_cost": total_cost,
            "raf_cost": raf_cost,
            "labor_cost": labor_cost,
            "direct_cost": direct_cost,
            "other_cost": other_cost,
            "margin_amount": total_sale - total_cost,
        }

    # =========================================================================
    # EXPENSES
    # =========================================================================
    @classmethod
    def summarize_expenses(cls, project):
        """
        Dépenses selon états disponibles dans le modèle actuel :
        - DRAFT
        - VALIDATED
        - REJECTED

        Mapping logique :
        - estimated / forecast / committed ~= DRAFT
        - actual / paid ~= VALIDATED
        """
        qs = project.expenses.select_related("category")

        total = cls._safe_decimal(qs.aggregate(total=Sum("amount"))["total"])

        draft = cls._safe_decimal(
            qs.filter(status=dm.ProjectExpense.ExpenseStatus.DRAFT)
            .aggregate(total=Sum("amount"))["total"]
        )

        validated = cls._safe_decimal(
            qs.filter(status=dm.ProjectExpense.ExpenseStatus.VALIDATED)
            .aggregate(total=Sum("amount"))["total"]
        )

        rejected = cls._safe_decimal(
            qs.filter(status=dm.ProjectExpense.ExpenseStatus.REJECTED)
            .aggregate(total=Sum("amount"))["total"]
        )

        labor_cost = Decimal("0")
        direct_cost = Decimal("0")
        other_cost = Decimal("0")

        for expense in qs.exclude(status=dm.ProjectExpense.ExpenseStatus.REJECTED):
            amount = cls._safe_decimal(expense.amount)
            category_type = getattr(expense.category, "category_type", None)

            if category_type == dm.CostCategory.CategoryType.HUMAN:
                labor_cost += amount
            elif category_type in {
                dm.CostCategory.CategoryType.SOFTWARE,
                dm.CostCategory.CategoryType.INFRA,
                dm.CostCategory.CategoryType.EQUIPMENT,
                dm.CostCategory.CategoryType.SUBCONTRACT,
                dm.CostCategory.CategoryType.TRAVEL,
                dm.CostCategory.CategoryType.TRAINING,
            }:
                direct_cost += amount
            else:
                other_cost += amount

        return {
            "total": total,
            "estimated": draft,
            "forecast": draft,
            "committed": draft,
            "accrued": validated,
            "paid": validated,
            "rejected": rejected,
            "labor_cost": labor_cost,
            "direct_cost": direct_cost,
            "other_cost": other_cost,
        }

    # =========================================================================
    # REVENUES
    # =========================================================================
    @classmethod
    def summarize_revenues(cls, project):
        """
        Partie clientèle avec le modèle actuel :
        - amount
        - is_received
        - revenue_type

        Mapping :
        - planned = total amount
        - invoiced = total amount
        - received = sum amount where is_received=True
        """
        qs = project.revenues.all()

        planned = cls._safe_decimal(qs.aggregate(total=Sum("amount"))["total"])
        invoiced = planned
        received = cls._safe_decimal(
            qs.filter(is_received=True).aggregate(total=Sum("amount"))["total"]
        )

        planned_fixed = cls._safe_decimal(
            qs.filter(revenue_type=dm.ProjectRevenue.RevenueType.FIXED)
            .aggregate(total=Sum("amount"))["total"]
        )
        planned_tm = cls._safe_decimal(
            qs.filter(revenue_type=dm.ProjectRevenue.RevenueType.TIME_MATERIAL)
            .aggregate(total=Sum("amount"))["total"]
        )
        planned_milestone = cls._safe_decimal(
            qs.filter(revenue_type=dm.ProjectRevenue.RevenueType.MILESTONE)
            .aggregate(total=Sum("amount"))["total"]
        )

        return {
            "planned": planned,
            "invoiced": invoiced,
            "received": received,
            "remaining_to_invoice": max(planned - invoiced, Decimal("0")),
            "remaining_to_collect": max(invoiced - received, Decimal("0")),
            "planned_fixed": planned_fixed,
            "planned_time_material": planned_tm,
            "planned_milestone": planned_milestone,
        }

    # =========================================================================
    # REGENERATE ESTIMATE LINES
    # =========================================================================
    @classmethod
    @transaction.atomic
    def regenerate_estimate_lines_from_tasks(cls, project, user=None, replace_existing=False):
        """
        Génère les lignes TASK à partir des tâches estimées.
        Compatible avec le modèle actuel :
        - pas de budget_stage
        """
        if replace_existing:
            project.estimate_lines.filter(
                source_type=dm.ProjectEstimateLine.EstimationSource.TASK
            ).delete()

        lines_count = 0

        tasks = project.tasks.filter(is_archived=False).select_related("assignee", "sprint")

        labor_category = (
            dm.CostCategory.objects.filter(category_type=dm.CostCategory.CategoryType.HUMAN)
            .order_by("name")
            .first()
        )

        for task in tasks:
            if not task.estimate_hours or not task.assignee:
                continue

            cost_amount, sale_amount = cls.estimate_task_costs(task)
            hours = cls._safe_decimal(task.estimate_hours)

            if hours <= 0:
                continue

            cost_unit = (cost_amount / hours) if hours > 0 else Decimal("0")
            markup_percent = Decimal("0")
            if cost_amount > 0 and sale_amount > cost_amount:
                markup_percent = ((sale_amount - cost_amount) / cost_amount) * Decimal("100")

            line = dm.ProjectEstimateLine(
                project=project,
                category=labor_category,
                source_type=dm.ProjectEstimateLine.EstimationSource.TASK,
                task=task,
                sprint=task.sprint,
                label=f"Tâche · {task.title}",
                description=task.description or "",
                quantity=hours,
                cost_unit_amount=cost_unit,
                markup_percent=markup_percent,
                created_by=user,
            )
            line.save()
            lines_count += 1

        return lines_count

    @classmethod
    @transaction.atomic
    def regenerate_raf_lines_from_tasks(cls, project, user=None, replace_existing=False):
        """
        Avec les modèles actuels sans budget_stage, on ne crée pas de lignes RAF séparées.
        Le RAF est calculé dynamiquement depuis estimate_hours - spent_hours.
        """
        return 0

    # =========================================================================
    # BUDGET REBUILD
    # =========================================================================
    @classmethod
    @transaction.atomic
    def regenerate_budget_from_estimates(cls, project, approved_by=None):
        """
        Met à jour / crée ProjectBudget à partir des lignes d'estimation.
        """
        budget, _ = dm.ProjectBudget.objects.get_or_create(project=project)

        estimate_lines = project.estimate_lines.select_related("category")

        labor = Decimal("0")
        software = Decimal("0")
        infra = Decimal("0")
        subcontract = Decimal("0")
        other = Decimal("0")

        for line in estimate_lines:
            amount = cls._safe_decimal(line.cost_amount)
            category_type = getattr(line.category, "category_type", dm.CostCategory.CategoryType.OTHER)

            if category_type == dm.CostCategory.CategoryType.HUMAN:
                labor += amount
            elif category_type == dm.CostCategory.CategoryType.SOFTWARE:
                software += amount
            elif category_type == dm.CostCategory.CategoryType.INFRA:
                infra += amount
            elif category_type == dm.CostCategory.CategoryType.SUBCONTRACT:
                subcontract += amount
            else:
                other += amount

        budget.estimated_labor_cost = labor
        budget.estimated_software_cost = software
        budget.estimated_infra_cost = infra
        budget.estimated_subcontract_cost = subcontract
        budget.estimated_other_cost = other

        if not budget.planned_revenue or budget.planned_revenue <= 0:
            estimate_summary = cls.summarize_estimate_lines(project)
            budget.planned_revenue = estimate_summary["total_sale"]

        if approved_by:
            budget.approved_by = approved_by
            if budget.status == dm.ProjectBudget.Status.APPROVED and not budget.approved_at:
                budget.approved_at = timezone.now()

        budget.save()
        return budget

    # =========================================================================
    # OVERVIEW GLOBAL
    # =========================================================================
    @classmethod
    def build_budget_overview(cls, project):
        """
        Vue consolidée :
        - budget estimatif
        - engagé
        - réel
        - reste à faire
        - revenus
        - marges
        Compatible avec les modèles actuels.
        """
        budget = getattr(project, "budgetestimatif", None)

        estimates = cls.summarize_estimate_lines(project)
        expenses = cls.summarize_expenses(project)
        revenues = cls.summarize_revenues(project)
        timesheets = cls.summarize_timesheets(project)

        approved_budget = cls._safe_decimal(getattr(budget, "approved_budget", 0))
        planned_revenue = cls._safe_decimal(getattr(budget, "planned_revenue", 0))
        contingency_amount = cls._safe_decimal(getattr(budget, "contingency_amount", 0))

        estimated_cost = estimates["estimated_cost"] or estimates["total_cost"]
        baseline_cost = estimates["baseline_cost"] if estimates["baseline_cost"] > 0 else estimated_cost
        committed_cost = expenses["committed"]
        actual_cost = expenses["paid"]
        accrued_cost = expenses["accrued"]
        raf_cost = estimates["raf_cost"]

        forecast_final_cost = actual_cost + committed_cost + raf_cost
        total_direct_cost = expenses["direct_cost"]
        total_labor_cost = expenses["labor_cost"]
        other_cost = expenses["other_cost"]

        gross_margin = revenues["received"] - total_direct_cost
        operating_margin = gross_margin - total_labor_cost
        net_profit = operating_margin - other_cost

        profit_margin_percent = 0
        if revenues["received"] > 0:
            profit_margin_percent = int((net_profit / revenues["received"]) * Decimal("100"))

        expense_ratio_percent = 0
        if approved_budget > 0:
            expense_ratio_percent = int((actual_cost / approved_budget) * Decimal("100"))

        forecast_consumption_percent = 0
        if approved_budget > 0:
            forecast_consumption_percent = int((forecast_final_cost / approved_budget) * Decimal("100"))

        final_planned_revenue = planned_revenue if planned_revenue > 0 else revenues["planned"]

        return {
            "budget_obj": budget,

            "approved_budget": approved_budget,
            "estimated_cost": estimated_cost,
            "baseline_cost": baseline_cost,
            "committed_cost": committed_cost,
            "accrued_cost": accrued_cost,
            "actual_cost": actual_cost,
            "raf_cost": raf_cost,
            "forecast_final_cost": forecast_final_cost,

            "contingency_amount": contingency_amount,
            "management_reserve_amount": Decimal("0"),

            "planned_revenue": final_planned_revenue,
            "invoiced_revenue": revenues["invoiced"],
            "received_revenue": revenues["received"],
            "remaining_to_invoice": revenues["remaining_to_invoice"],
            "remaining_to_collect": revenues["remaining_to_collect"],

            "timesheet_total_hours": timesheets["total_hours"],
            "timesheet_approved_hours": timesheets["approved_hours"],
            "timesheet_logged_cost": timesheets["logged_cost"],
            "timesheet_approved_cost": timesheets["approved_logged_cost"],

            "direct_cost": total_direct_cost,
            "labor_cost": total_labor_cost,
            "other_cost": other_cost,

            "gross_margin": gross_margin,
            "operating_margin": operating_margin,
            "net_profit": net_profit,
            "profit_margin_percent": profit_margin_percent,

            "remaining_budget": approved_budget - actual_cost,
            "remaining_budget_forecast": approved_budget - forecast_final_cost,
            "forecast_margin": final_planned_revenue - forecast_final_cost,
            "real_margin": revenues["received"] - actual_cost,
            "expense_ratio_percent": expense_ratio_percent,
            "forecast_consumption_percent": forecast_consumption_percent,

            "estimate_summary": estimates,
            "expense_summary": expenses,
            "revenue_summary": revenues,
            "timesheet_summary": timesheets,

            "currency": getattr(budget, "currency", "XOF") if budget else "XOF",
        }

    # =========================================================================
    # SMART REFRESH
    # =========================================================================
    @classmethod
    @transaction.atomic
    def refresh_project_financials(cls, project, user=None, rebuild_budget=True):
        """
        Rafraîchissement intelligent global :
        1. régénère les lignes d'estimation à partir des tâches
        2. met à jour le budget
        3. retourne l’overview
        """
        cls.regenerate_estimate_lines_from_tasks(
            project=project,
            user=user,
            replace_existing=True,
        )

        if rebuild_budget:
            cls.regenerate_budget_from_estimates(project=project, approved_by=user)

        return cls.build_budget_overview(project)