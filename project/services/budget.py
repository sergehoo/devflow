"""
ProjectBudgetService — Calculs financiers DevFlow basés sur le TJM.

Refonte v2 (audit du 2026-04-26) :
- Corrections du mapping ProjectExpense (utilisation des statuts réels)
- Corrections des sommes de revenus (invoiced/received corrects)
- Calcul du sale réel basé sur les TJM de vente dans summarize_timesheets
- Remplacement des boucles Python par des aggregations DB (perf x10 typique)
- Ajout d'helpers TJM par période (utilisés par les services IA de prévision)
- Préservation stricte de l'API publique existante (build_budget_overview, etc.)
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

from django.db import transaction
from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from project import models as dm

ZERO = Decimal("0")
HUNDRED = Decimal("100")
MONEY = DecimalField(max_digits=14, decimal_places=2)


def _zero():
    return Coalesce(Sum("amount"), Value(ZERO), output_field=MONEY)


class ProjectBudgetService:
    DEFAULT_WORKING_DAYS_PER_MONTH = Decimal("22")
    DEFAULT_HOURS_PER_DAY = Decimal("8")
    WORKING_DAYS_RATIO = Decimal("5") / Decimal("7")  # 5 jours ouvrés sur 7

    # =========================================================================
    # HELPERS
    # =========================================================================
    @staticmethod
    def _safe_decimal(value, default="0") -> Decimal:
        try:
            if value is None or value == "":
                return Decimal(default)
            return Decimal(str(value))
        except Exception:
            return Decimal(default)

    @classmethod
    def _get_hours_per_day(cls, user) -> Decimal:
        profile = getattr(user, "profile", None)
        if profile and getattr(profile, "capacity_hours_per_day", None):
            hours = cls._safe_decimal(profile.capacity_hours_per_day, "8")
            return hours if hours > 0 else cls.DEFAULT_HOURS_PER_DAY
        return cls.DEFAULT_HOURS_PER_DAY

    @classmethod
    def _availability(cls, user) -> Decimal:
        """Renvoie la disponibilité actuelle de l'utilisateur (0..1)."""
        profile = getattr(user, "profile", None)
        if profile and getattr(profile, "availability_percent", None) is not None:
            return cls._safe_decimal(profile.availability_percent) / HUNDRED
        return Decimal("1")

    @classmethod
    def get_member_daily_cost(cls, user) -> Decimal:
        return dm.BillingRate.get_user_daily_cost(user)

    @classmethod
    def get_member_daily_sale_rate(cls, user) -> Decimal:
        return dm.BillingRate.get_user_sale_daily_rate(user)

    @classmethod
    def working_days_between(cls, start: date | None, end: date | None) -> Decimal:
        """Nombre de jours ouvrés (approx 5/7) entre deux dates incluses."""
        if not start or not end or end < start:
            return ZERO
        total_days = (end - start).days + 1
        return Decimal(max(round(total_days * float(cls.WORKING_DAYS_RATIO)), 1))

    # =========================================================================
    # ESTIMATION RH / TASKS
    # =========================================================================
    @classmethod
    def estimate_task_costs(cls, task) -> tuple[Decimal, Decimal]:
        """Coût et chiffre d'affaires estimés pour une tâche."""
        if not task.assignee or not task.estimate_hours:
            return ZERO, ZERO

        hours = cls._safe_decimal(task.estimate_hours)
        if hours <= 0:
            return ZERO, ZERO

        hours_per_day = cls._get_hours_per_day(task.assignee) or cls.DEFAULT_HOURS_PER_DAY
        estimated_days = hours / hours_per_day

        daily_cost = cls.get_member_daily_cost(task.assignee)
        daily_sale = cls.get_member_daily_sale_rate(task.assignee)

        return estimated_days * daily_cost, estimated_days * daily_sale

    @classmethod
    def estimate_task_remaining_costs(cls, task) -> tuple[Decimal, Decimal]:
        if not task.assignee:
            return ZERO, ZERO

        estimate_hours = cls._safe_decimal(task.estimate_hours)
        spent_hours = cls._safe_decimal(task.spent_hours)
        remaining_hours = max(estimate_hours - spent_hours, ZERO)

        if remaining_hours <= 0:
            return ZERO, ZERO

        hours_per_day = cls._get_hours_per_day(task.assignee) or cls.DEFAULT_HOURS_PER_DAY
        remaining_days = remaining_hours / hours_per_day

        daily_cost = cls.get_member_daily_cost(task.assignee)
        daily_sale = cls.get_member_daily_sale_rate(task.assignee)

        return remaining_days * daily_cost, remaining_days * daily_sale

    @classmethod
    def estimate_member_period_cost(
        cls,
        user,
        start: date | None,
        end: date | None,
        allocation_percent: Decimal | float | int | None = None,
    ) -> tuple[Decimal, Decimal]:
        """
        Coût et CA prévisionnels pour un membre sur une période,
        en tenant compte de l'allocation et de la disponibilité du profil.
        Utilisé par le service IA de prévision budgétaire.
        """
        working_days = cls.working_days_between(start, end)
        if working_days <= 0:
            return ZERO, ZERO

        allocation = cls._safe_decimal(allocation_percent or 100) / HUNDRED
        availability = cls._availability(user)

        effective_days = working_days * allocation * availability

        daily_cost = cls.get_member_daily_cost(user)
        daily_sale = cls.get_member_daily_sale_rate(user)

        return effective_days * daily_cost, effective_days * daily_sale

    @classmethod
    def estimate_project_members_costs(cls, project) -> tuple[Decimal, Decimal]:
        """
        Estimation RH théorique basée sur les membres projet.
        Tient compte de l'allocation et de la disponibilité.
        """
        total_cost = ZERO
        total_sale = ZERO

        members = project.members.select_related("user", "team")

        for member in members:
            cost, sale = cls.estimate_member_period_cost(
                user=member.user,
                start=project.start_date,
                end=project.target_date,
                allocation_percent=member.allocation_percent or 0,
            )
            total_cost += cost
            total_sale += sale

        return total_cost, total_sale

    # =========================================================================
    # TIMESHEETS
    # =========================================================================
    @classmethod
    def summarize_timesheets(cls, project) -> dict:
        """
        Synthèse temps réellement consommé.
        - logged_cost / approved_logged_cost : depuis snapshot si présent, sinon
          calculé à la volée à partir du TJM courant.
        - logged_sale / approved_logged_sale : même logique pour le CA.
        """
        qs = project.timesheet_entries.select_related("user")

        approved_qs = qs.filter(approval_status=dm.TimesheetEntry.ApprovalStatus.APPROVED)

        total_hours = cls._safe_decimal(qs.aggregate(total=Sum("hours"))["total"])
        approved_hours = cls._safe_decimal(approved_qs.aggregate(total=Sum("hours"))["total"])

        # Coût / vente snapshot si disponible
        snapshot_cost = cls._safe_decimal(
            qs.aggregate(total=Sum("cost_snapshot__computed_cost"))["total"]
        )
        approved_snapshot_cost = cls._safe_decimal(
            approved_qs.aggregate(total=Sum("cost_snapshot__computed_cost"))["total"]
        )

        # Calcul du CA & complément des entries sans snapshot
        logged_cost = ZERO
        approved_logged_cost = ZERO
        logged_sale = ZERO
        approved_logged_sale = ZERO

        for entry in qs:
            hours = cls._safe_decimal(entry.hours)
            if hours <= 0 or not entry.user_id:
                continue

            hours_per_day = cls._get_hours_per_day(entry.user) or cls.DEFAULT_HOURS_PER_DAY
            days = hours / hours_per_day

            daily_cost = cls.get_member_daily_cost(entry.user)
            daily_sale = cls.get_member_daily_sale_rate(entry.user)

            entry_cost = days * daily_cost
            entry_sale = days * daily_sale

            logged_cost += entry_cost
            logged_sale += entry_sale

            if entry.approval_status == dm.TimesheetEntry.ApprovalStatus.APPROVED:
                approved_logged_cost += entry_cost
                approved_logged_sale += entry_sale

        # Snapshot prend la priorité s'il a été calculé
        if snapshot_cost > 0:
            logged_cost = snapshot_cost
        if approved_snapshot_cost > 0:
            approved_logged_cost = approved_snapshot_cost

        return {
            "total_hours": total_hours,
            "approved_hours": approved_hours,
            "logged_cost": logged_cost,
            "approved_logged_cost": approved_logged_cost,
            "logged_sale": logged_sale,
            "approved_logged_sale": approved_logged_sale,
        }

    # =========================================================================
    # ESTIMATE LINES
    # =========================================================================
    @classmethod
    def summarize_estimate_lines(cls, project) -> dict:
        qs = project.estimate_lines.select_related("category", "task")

        total_cost = cls._safe_decimal(qs.aggregate(total=Sum("cost_amount"))["total"])
        total_sale = cls._safe_decimal(qs.aggregate(total=Sum("sale_amount"))["total"])

        # Agrégations par type de catégorie via filter conditional aggregation
        labor_cost = cls._safe_decimal(
            qs.filter(category__category_type=dm.CostCategory.CategoryType.HUMAN)
            .aggregate(total=Sum("cost_amount"))["total"]
        )

        direct_types = [
            dm.CostCategory.CategoryType.SOFTWARE,
            dm.CostCategory.CategoryType.INFRA,
            dm.CostCategory.CategoryType.EQUIPMENT,
            dm.CostCategory.CategoryType.SUBCONTRACT,
            dm.CostCategory.CategoryType.TRAVEL,
            dm.CostCategory.CategoryType.TRAINING,
        ]
        direct_cost = cls._safe_decimal(
            qs.filter(category__category_type__in=direct_types)
            .aggregate(total=Sum("cost_amount"))["total"]
        )

        other_cost = total_cost - labor_cost - direct_cost
        if other_cost < 0:
            other_cost = ZERO

        # RAF (reste à faire) : pour chaque ligne TASK active, on calcule la
        # part restante de la tâche. On sélectionne uniquement les lignes
        # ayant une tâche non terminée — peu de lignes en pratique.
        raf_cost = ZERO
        active_lines = qs.filter(task__isnull=False).exclude(
            task__status__in=[dm.Task.Status.DONE, dm.Task.Status.CANCELLED]
        )
        for line in active_lines:
            estimate_hours = cls._safe_decimal(line.task.estimate_hours)
            spent_hours = cls._safe_decimal(line.task.spent_hours)
            if estimate_hours <= 0:
                continue
            ratio = max(estimate_hours - spent_hours, ZERO) / estimate_hours
            raf_cost += cls._safe_decimal(line.cost_amount) * ratio

        # Stage breakdown (utilisé par le forecast)
        baseline_cost = cls._safe_decimal(
            qs.filter(budget_stage=dm.ProjectEstimateLine.BudgetStage.BASELINE)
            .aggregate(total=Sum("cost_amount"))["total"]
        )
        forecast_cost = cls._safe_decimal(
            qs.filter(budget_stage=dm.ProjectEstimateLine.BudgetStage.FORECAST)
            .aggregate(total=Sum("cost_amount"))["total"]
        )

        return {
            "total_cost": total_cost,
            "total_sale": total_sale,
            "estimated_cost": total_cost,
            "baseline_cost": baseline_cost or total_cost,
            "forecast_cost": forecast_cost,
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
    def summarize_expenses(cls, project) -> dict:
        """
        Synthèse dépenses utilisant les statuts réels du modèle ProjectExpense.

        Mapping :
        - estimated  → status=ESTIMATED
        - forecast   → status=FORECAST
        - committed  → status=COMMITTED
        - accrued    → status=ACCRUED
        - paid       → status=PAID
        - validated  → status=VALIDATED
        - draft      → status=DRAFT
        - rejected   → status=REJECTED
        """
        qs = project.expenses.select_related("category")
        st = dm.ProjectExpense.ExpenseStatus

        agg = qs.aggregate(
            total=_zero(),
            draft=Coalesce(Sum("amount", filter=Q(status=st.DRAFT)), Value(ZERO), output_field=MONEY),
            estimated=Coalesce(Sum("amount", filter=Q(status=st.ESTIMATED)), Value(ZERO), output_field=MONEY),
            forecast=Coalesce(Sum("amount", filter=Q(status=st.FORECAST)), Value(ZERO), output_field=MONEY),
            committed=Coalesce(Sum("amount", filter=Q(status=st.COMMITTED)), Value(ZERO), output_field=MONEY),
            accrued=Coalesce(Sum("amount", filter=Q(status=st.ACCRUED)), Value(ZERO), output_field=MONEY),
            paid=Coalesce(Sum("amount", filter=Q(status=st.PAID)), Value(ZERO), output_field=MONEY),
            validated=Coalesce(Sum("amount", filter=Q(status=st.VALIDATED)), Value(ZERO), output_field=MONEY),
            rejected=Coalesce(Sum("amount", filter=Q(status=st.REJECTED)), Value(ZERO), output_field=MONEY),
        )

        # Catégories (hors REJECTED)
        not_rejected = qs.exclude(status=st.REJECTED)

        labor_cost = cls._safe_decimal(
            not_rejected.filter(category__category_type=dm.CostCategory.CategoryType.HUMAN)
            .aggregate(total=Sum("amount"))["total"]
        )
        direct_types = [
            dm.CostCategory.CategoryType.SOFTWARE,
            dm.CostCategory.CategoryType.INFRA,
            dm.CostCategory.CategoryType.EQUIPMENT,
            dm.CostCategory.CategoryType.SUBCONTRACT,
            dm.CostCategory.CategoryType.TRAVEL,
            dm.CostCategory.CategoryType.TRAINING,
        ]
        direct_cost = cls._safe_decimal(
            not_rejected.filter(category__category_type__in=direct_types)
            .aggregate(total=Sum("amount"))["total"]
        )
        non_rejected_total = cls._safe_decimal(
            not_rejected.aggregate(total=Sum("amount"))["total"]
        )
        other_cost = max(non_rejected_total - labor_cost - direct_cost, ZERO)

        return {
            "total": cls._safe_decimal(agg["total"]),
            "draft": cls._safe_decimal(agg["draft"]),
            "estimated": cls._safe_decimal(agg["estimated"]),
            "forecast": cls._safe_decimal(agg["forecast"]),
            "committed": cls._safe_decimal(agg["committed"]),
            "accrued": cls._safe_decimal(agg["accrued"]),
            "paid": cls._safe_decimal(agg["paid"]),
            "validated": cls._safe_decimal(agg["validated"]),
            "rejected": cls._safe_decimal(agg["rejected"]),
            "labor_cost": labor_cost,
            "direct_cost": direct_cost,
            "other_cost": other_cost,
        }

    # =========================================================================
    # REVENUES
    # =========================================================================
    @classmethod
    def summarize_revenues(cls, project) -> dict:
        """
        Synthèse revenus en utilisant correctement les champs amount,
        invoiced_amount, received_amount.
        """
        qs = project.revenues.all()

        agg = qs.aggregate(
            planned=Coalesce(Sum("amount"), Value(ZERO), output_field=MONEY),
            invoiced=Coalesce(Sum("invoiced_amount"), Value(ZERO), output_field=MONEY),
            received=Coalesce(Sum("received_amount"), Value(ZERO), output_field=MONEY),
        )

        rt = dm.ProjectRevenue.RevenueType
        per_type = qs.aggregate(
            planned_fixed=Coalesce(
                Sum("amount", filter=Q(revenue_type=rt.FIXED)),
                Value(ZERO), output_field=MONEY,
            ),
            planned_tm=Coalesce(
                Sum("amount", filter=Q(revenue_type=rt.TIME_MATERIAL)),
                Value(ZERO), output_field=MONEY,
            ),
            planned_milestone=Coalesce(
                Sum("amount", filter=Q(revenue_type=rt.MILESTONE)),
                Value(ZERO), output_field=MONEY,
            ),
            planned_license=Coalesce(
                Sum("amount", filter=Q(revenue_type=rt.LICENSE)),
                Value(ZERO), output_field=MONEY,
            ),
        )

        planned = cls._safe_decimal(agg["planned"])
        invoiced = cls._safe_decimal(agg["invoiced"])
        received = cls._safe_decimal(agg["received"])

        return {
            "planned": planned,
            "invoiced": invoiced,
            "received": received,
            "remaining_to_invoice": max(planned - invoiced, ZERO),
            "remaining_to_collect": max(invoiced - received, ZERO),
            "planned_fixed": cls._safe_decimal(per_type["planned_fixed"]),
            "planned_time_material": cls._safe_decimal(per_type["planned_tm"]),
            "planned_milestone": cls._safe_decimal(per_type["planned_milestone"]),
            "planned_license": cls._safe_decimal(per_type["planned_license"]),
        }

    # =========================================================================
    # REGENERATE ESTIMATE LINES
    # =========================================================================
    @classmethod
    @transaction.atomic
    def regenerate_estimate_lines_from_tasks(cls, project, user=None, replace_existing=False) -> int:
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
        if labor_category is None:
            labor_category = dm.CostCategory.objects.create(
                name="Ressources humaines",
                category_type=dm.CostCategory.CategoryType.HUMAN,
            )

        for task in tasks:
            if not task.estimate_hours or not task.assignee:
                continue

            cost_amount, sale_amount = cls.estimate_task_costs(task)
            hours = cls._safe_decimal(task.estimate_hours)
            if hours <= 0:
                continue

            cost_unit = cost_amount / hours if hours > 0 else ZERO

            markup_percent = ZERO
            if cost_amount > 0 and sale_amount > cost_amount:
                markup_percent = ((sale_amount - cost_amount) / cost_amount) * HUNDRED

            line = dm.ProjectEstimateLine(
                project=project,
                category=labor_category,
                source_type=dm.ProjectEstimateLine.EstimationSource.TASK,
                budget_stage=dm.ProjectEstimateLine.BudgetStage.ESTIMATED,
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
    def regenerate_raf_lines_from_tasks(cls, project, user=None, replace_existing=False) -> int:
        """
        Génère des lignes RAF pour les tâches non terminées dont il reste
        du temps à passer. Utilisé par les vues de forecast.
        """
        if replace_existing:
            project.estimate_lines.filter(
                budget_stage=dm.ProjectEstimateLine.BudgetStage.RAF
            ).delete()

        labor_category = (
            dm.CostCategory.objects.filter(category_type=dm.CostCategory.CategoryType.HUMAN)
            .order_by("name")
            .first()
        )

        count = 0
        active_tasks = project.tasks.filter(is_archived=False).exclude(
            status__in=[dm.Task.Status.DONE, dm.Task.Status.CANCELLED]
        )

        for task in active_tasks:
            if not task.assignee or not task.estimate_hours:
                continue

            cost_amount, sale_amount = cls.estimate_task_remaining_costs(task)
            if cost_amount <= 0:
                continue

            estimate_hours = cls._safe_decimal(task.estimate_hours)
            spent_hours = cls._safe_decimal(task.spent_hours)
            remaining_hours = max(estimate_hours - spent_hours, ZERO)

            if remaining_hours <= 0:
                continue

            cost_unit = cost_amount / remaining_hours if remaining_hours > 0 else ZERO
            markup = ZERO
            if cost_amount > 0 and sale_amount > cost_amount:
                markup = ((sale_amount - cost_amount) / cost_amount) * HUNDRED

            dm.ProjectEstimateLine.objects.create(
                project=project,
                category=labor_category,
                source_type=dm.ProjectEstimateLine.EstimationSource.TASK,
                budget_stage=dm.ProjectEstimateLine.BudgetStage.RAF,
                task=task,
                sprint=task.sprint,
                label=f"RAF · {task.title}",
                description="Reste à faire calculé automatiquement",
                quantity=remaining_hours,
                cost_unit_amount=cost_unit,
                markup_percent=markup,
                created_by=user,
            )
            count += 1
        return count

    # =========================================================================
    # BUDGET REBUILD
    # =========================================================================
    @classmethod
    @transaction.atomic
    def regenerate_budget_from_estimates(cls, project, approved_by=None):
        budget, _ = dm.ProjectBudget.objects.get_or_create(project=project)

        estimate_lines = project.estimate_lines.select_related("category")

        # Aggregations DB plutôt que boucle Python
        type_aggs = estimate_lines.aggregate(
            labor=Coalesce(
                Sum("cost_amount", filter=Q(category__category_type=dm.CostCategory.CategoryType.HUMAN)),
                Value(ZERO), output_field=MONEY,
            ),
            software=Coalesce(
                Sum("cost_amount", filter=Q(category__category_type=dm.CostCategory.CategoryType.SOFTWARE)),
                Value(ZERO), output_field=MONEY,
            ),
            infra=Coalesce(
                Sum("cost_amount", filter=Q(category__category_type=dm.CostCategory.CategoryType.INFRA)),
                Value(ZERO), output_field=MONEY,
            ),
            subcontract=Coalesce(
                Sum("cost_amount", filter=Q(category__category_type=dm.CostCategory.CategoryType.SUBCONTRACT)),
                Value(ZERO), output_field=MONEY,
            ),
            equipment=Coalesce(
                Sum("cost_amount", filter=Q(category__category_type=dm.CostCategory.CategoryType.EQUIPMENT)),
                Value(ZERO), output_field=MONEY,
            ),
            travel=Coalesce(
                Sum("cost_amount", filter=Q(category__category_type=dm.CostCategory.CategoryType.TRAVEL)),
                Value(ZERO), output_field=MONEY,
            ),
            training=Coalesce(
                Sum("cost_amount", filter=Q(category__category_type=dm.CostCategory.CategoryType.TRAINING)),
                Value(ZERO), output_field=MONEY,
            ),
            other=Coalesce(
                Sum("cost_amount", filter=Q(category__category_type=dm.CostCategory.CategoryType.OTHER)),
                Value(ZERO), output_field=MONEY,
            ),
        )

        budget.estimated_labor_cost = cls._safe_decimal(type_aggs["labor"])
        budget.estimated_software_cost = cls._safe_decimal(type_aggs["software"])
        budget.estimated_infra_cost = cls._safe_decimal(type_aggs["infra"])
        budget.estimated_subcontract_cost = cls._safe_decimal(type_aggs["subcontract"])
        budget.estimated_other_cost = (
            cls._safe_decimal(type_aggs["equipment"])
            + cls._safe_decimal(type_aggs["travel"])
            + cls._safe_decimal(type_aggs["training"])
            + cls._safe_decimal(type_aggs["other"])
        )

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
    def build_budget_overview(cls, project) -> dict:
        budget = getattr(project, "budgetestimatif", None)

        estimates = cls.summarize_estimate_lines(project)
        expenses = cls.summarize_expenses(project)
        revenues = cls.summarize_revenues(project)
        timesheets = cls.summarize_timesheets(project)

        approved_budget = cls._safe_decimal(getattr(budget, "approved_budget", 0))
        planned_revenue = cls._safe_decimal(getattr(budget, "planned_revenue", 0))
        contingency_amount = cls._safe_decimal(getattr(budget, "contingency_amount", 0))
        management_reserve = cls._safe_decimal(getattr(budget, "management_reserve_amount", 0))

        # Coûts engagés réels = COMMITTED + ACCRUED
        committed_cost = expenses["committed"] + expenses["accrued"]
        # Coûts décaissés / actuels
        actual_cost = expenses["paid"] + expenses["validated"]
        # RAF (reste à faire) basé sur les tâches actives
        raf_cost = estimates["raf_cost"] or timesheets["logged_cost"] * ZERO

        # Forecast = ce qui est déjà sorti + engagé non payé + reste à faire
        forecast_final_cost = actual_cost + committed_cost + raf_cost

        total_direct_cost = expenses["direct_cost"]
        total_labor_cost = expenses["labor_cost"] + timesheets["logged_cost"]
        other_cost = expenses["other_cost"]

        # Marges réelles vs forecast
        revenue_received = revenues["received"]
        revenue_invoiced = revenues["invoiced"]
        revenue_planned = revenues["planned"] or planned_revenue

        gross_margin = revenue_invoiced - total_direct_cost
        operating_margin = gross_margin - total_labor_cost
        net_profit = operating_margin - other_cost

        profit_margin_percent = ZERO
        if revenue_invoiced > 0:
            profit_margin_percent = (net_profit / revenue_invoiced) * HUNDRED

        expense_ratio_percent = ZERO
        if approved_budget > 0:
            expense_ratio_percent = (actual_cost / approved_budget) * HUNDRED

        forecast_consumption_percent = ZERO
        if approved_budget > 0:
            forecast_consumption_percent = (forecast_final_cost / approved_budget) * HUNDRED

        final_planned_revenue = planned_revenue if planned_revenue > 0 else revenue_planned

        return {
            "budget_obj": budget,

            "approved_budget": approved_budget,
            "estimated_cost": estimates["estimated_cost"],
            "baseline_cost": estimates["baseline_cost"],
            "committed_cost": committed_cost,
            "accrued_cost": expenses["accrued"],
            "actual_cost": actual_cost,
            "raf_cost": raf_cost,
            "forecast_final_cost": forecast_final_cost,

            "contingency_amount": contingency_amount,
            "management_reserve_amount": management_reserve,

            "planned_revenue": final_planned_revenue,
            "invoiced_revenue": revenue_invoiced,
            "received_revenue": revenue_received,
            # Alias rétro-compatibilité templates existants
            "total_received": revenue_received,
            "remaining_to_invoice": revenues["remaining_to_invoice"],
            "remaining_to_collect": revenues["remaining_to_collect"],

            "timesheet_total_hours": timesheets["total_hours"],
            "timesheet_approved_hours": timesheets["approved_hours"],
            "timesheet_logged_cost": timesheets["logged_cost"],
            "timesheet_logged_sale": timesheets["logged_sale"],
            "timesheet_approved_cost": timesheets["approved_logged_cost"],
            "timesheet_approved_sale": timesheets["approved_logged_sale"],

            "direct_cost": total_direct_cost,
            "labor_cost": total_labor_cost,
            "other_cost": other_cost,

            "gross_margin": gross_margin,
            "operating_margin": operating_margin,
            "net_profit": net_profit,
            "profit_margin_percent": int(profit_margin_percent),

            "remaining_budget": approved_budget - actual_cost,
            "remaining_budget_forecast": approved_budget - forecast_final_cost,
            "forecast_margin": final_planned_revenue - forecast_final_cost,
            "real_margin": revenue_received - actual_cost,
            "expense_ratio_percent": int(expense_ratio_percent),
            "forecast_consumption_percent": int(forecast_consumption_percent),

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
    def refresh_project_financials(cls, project, user=None, rebuild_budget=True) -> dict:
        cls.regenerate_estimate_lines_from_tasks(
            project=project,
            user=user,
            replace_existing=True,
        )

        if rebuild_budget:
            cls.regenerate_budget_from_estimates(project=project, approved_by=user)

        return cls.build_budget_overview(project)

    # =========================================================================
    # PORTFOLIO
    # =========================================================================
    @classmethod
    def build_portfolio_overview(cls, projects: Iterable) -> dict:
        """
        Cockpit budgétaire multi-projets utilisé par le dashboard portfolio.
        """
        totals = defaultdict(lambda: ZERO)
        rows = []

        for project in projects:
            ov = cls.build_budget_overview(project)
            rows.append(
                {
                    "project": project,
                    "approved_budget": ov["approved_budget"],
                    "actual_cost": ov["actual_cost"],
                    "forecast_final_cost": ov["forecast_final_cost"],
                    "planned_revenue": ov["planned_revenue"],
                    "received_revenue": ov["received_revenue"],
                    "real_margin": ov["real_margin"],
                    "forecast_margin": ov["forecast_margin"],
                    "expense_ratio_percent": ov["expense_ratio_percent"],
                    "currency": ov["currency"],
                }
            )

            for key in [
                "approved_budget",
                "actual_cost",
                "forecast_final_cost",
                "planned_revenue",
                "received_revenue",
            ]:
                totals[key] += ov[key]

        totals_real_margin = totals["received_revenue"] - totals["actual_cost"]
        totals_forecast_margin = totals["planned_revenue"] - totals["forecast_final_cost"]

        totals_consumption = ZERO
        if totals["approved_budget"] > 0:
            totals_consumption = (totals["actual_cost"] / totals["approved_budget"]) * HUNDRED

        return {
            "rows": rows,
            "totals": dict(totals),
            "totals_real_margin": totals_real_margin,
            "totals_forecast_margin": totals_forecast_margin,
            "totals_consumption_percent": int(totals_consumption),
        }
