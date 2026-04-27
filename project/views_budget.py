from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Sum, Value, Q, DecimalField
from django.db.models.functions import Coalesce
# from django.forms import DecimalField
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import DetailView

from project import models as dm
from project.forms_budget import (
    ProjectBudgetForm,
    ProjectEstimateLineForm,
    ProjectRevenueForm,
    ProjectExpenseForm,
)
from project.services.budget import ProjectBudgetService
from project.views import DevflowCreateView, DevflowUpdateView, DevflowListView, DevflowDetailView


class ProjectFinancialPermissionMixin:
    def get_project_from_request(self):
        project_id = self.request.GET.get("project") or self.kwargs.get("project_id")
        if project_id:
            return (
                dm.Project.objects
                .select_related("workspace", "owner", "product_manager")
                .filter(pk=project_id)
                .first()
            )

        obj = getattr(self, "object", None)
        if obj and hasattr(obj, "project"):
            return obj.project

        return None

    def get_workspace_membership(self, workspace):
        if not workspace or not self.request.user.is_authenticated:
            return None
        return workspace.memberships.filter(user=self.request.user).select_related("team").first()

    def can_view_financials(self, project):
        user = self.request.user

        if not user.is_authenticated:
            return False

        if user.is_superuser:
            return True

        if user.has_perm("project.view_financial_data") or user.has_perm("project.view_projectexpense_financial"):
            return True

        membership = self.get_workspace_membership(project.workspace)
        if not membership:
            return False

        return membership.role in [
            dm.TeamMembership.Role.ADMIN,
            dm.TeamMembership.Role.CTO,
            dm.TeamMembership.Role.PM,
            dm.TeamMembership.Role.PRODUCT_OWNER,
            dm.TeamMembership.Role.TECH_LEAD,
        ]

    def can_approve_level1(self, expense):
        user = self.request.user

        if not user.is_authenticated:
            return False

        if user.is_superuser or user.has_perm("project.approve_projectexpense_level1"):
            return True

        membership = self.get_workspace_membership(expense.project.workspace)
        if not membership:
            return False

        return (
            expense.project.product_manager_id == user.id
            or expense.project.owner_id == user.id
            or membership.role in [
                dm.TeamMembership.Role.PM,
                dm.TeamMembership.Role.PRODUCT_OWNER,
            ]
        )

    def can_approve_level2(self, expense):
        user = self.request.user

        if not user.is_authenticated:
            return False

        if user.is_superuser or user.has_perm("project.approve_projectexpense_level2"):
            return True

        membership = self.get_workspace_membership(expense.project.workspace)
        if not membership:
            return False

        return membership.role in [
            dm.TeamMembership.Role.ADMIN,
            dm.TeamMembership.Role.CTO,
            dm.TeamMembership.Role.TECH_LEAD,
        ]

    def ensure_financial_permission(self):
        project = None

        obj = getattr(self, "object", None)
        if obj and hasattr(obj, "project"):
            project = obj.project
        else:
            project = self.get_project_from_request()

        if project and not self.can_view_financials(project):
            raise PermissionDenied("Vous n'avez pas accès aux données financières de ce projet.")

    def dispatch(self, request, *args, **kwargs):
        self.object = getattr(self, "object", None)
        self.ensure_financial_permission()
        return super().dispatch(request, *args, **kwargs)

class ProjectBudgetDetailView(ProjectFinancialPermissionMixin, DevflowDetailView):
    model = dm.ProjectBudget
    template_name = "project/budget/detail.html"
    section = "project"
    page_title = "Budget projet"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        budget = self.object
        ctx["overview"] = ProjectBudgetService.build_budget_overview(budget.project)
        return ctx


class ProjectBudgetCreateView(ProjectFinancialPermissionMixin, DevflowCreateView):
    model = dm.ProjectBudget
    form_class = ProjectBudgetForm
    template_name = "project/budget/form.html"
    section = "project"
    page_title = "Créer budget projet"

    def get_success_url(self):
        return reverse_lazy("project_detail", kwargs={"pk": self.object.project_id})

    def form_valid(self, form):
        project_id = self.request.GET.get("project")
        if project_id:
            form.instance.project = get_object_or_404(dm.Project, pk=project_id)
        messages.success(self.request, "Budget projet enregistré avec succès.")
        return super().form_valid(form)


class ProjectBudgetUpdateView(ProjectFinancialPermissionMixin, DevflowUpdateView):
    model = dm.ProjectBudget
    form_class = ProjectBudgetForm
    template_name = "project/budget/form.html"
    section = "project"
    page_title = "Modifier budget projet"

    def get_success_url(self):
        return reverse_lazy("project_detail", kwargs={"pk": self.object.project_id})


class ProjectEstimateLineCreateView(ProjectFinancialPermissionMixin, DevflowCreateView):
    model = dm.ProjectEstimateLine
    form_class = ProjectEstimateLineForm
    template_name = "project/estimate_line/form.html"
    section = "project"
    page_title = "Ajouter ligne d'estimation"

    def get_success_url(self):
        return reverse_lazy("project_detail", kwargs={"pk": self.object.project_id})

    def form_valid(self, form):
        project_id = self.request.GET.get("project")
        if project_id:
            form.instance.project = get_object_or_404(dm.Project, pk=project_id)
        form.instance.created_by = self.request.user
        messages.success(self.request, "Ligne d'estimation ajoutée.")
        return super().form_valid(form)


class ProjectRevenueCreateView(ProjectFinancialPermissionMixin, DevflowCreateView):
    model = dm.ProjectRevenue
    form_class = ProjectRevenueForm
    template_name = "project/revenue/form.html"
    section = "project"
    page_title = "Ajouter revenu projet"

    def get_success_url(self):
        return reverse_lazy("project_detail", kwargs={"pk": self.object.project_id})

    def form_valid(self, form):
        project_id = self.request.GET.get("project")
        if project_id:
            form.instance.project = get_object_or_404(dm.Project, pk=project_id)
        messages.success(self.request, "Prévision de revenu enregistrée.")
        return super().form_valid(form)


class ProjectExpenseUpdateView(ProjectFinancialPermissionMixin, DevflowUpdateView):
    model = dm.ProjectExpense
    form_class = ProjectExpenseForm
    template_name = "project/expense/form.html"
    section = "project"
    page_title = "Modifier dépense projet"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("project", "category", "task", "sprint", "milestone")
        )

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        expense = self.object
        project = expense.project
        form.fields["task"].queryset = project.tasks.filter(is_archived=False).order_by("title")
        form.fields["sprint"].queryset = project.sprints.filter(is_archived=False).order_by("-start_date")
        form.fields["milestone"].queryset = project.milestones.filter(is_archived=False).order_by("due_date")

        if expense.approval_state == dm.ProjectExpense.ApprovalState.LEVEL2_APPROVED:
            for field_name in form.fields:
                form.fields[field_name].disabled = True

        return form

    def get_success_url(self):
        return reverse_lazy("project_expense_detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        if self.object.approval_state == dm.ProjectExpense.ApprovalState.LEVEL2_APPROVED:
            messages.error(self.request, "Une dépense validée niveau 2 ne peut plus être modifiée.")
            return redirect(self.get_success_url())

        messages.success(self.request, "Dépense mise à jour.")
        return super().form_valid(form)


class ProjectExpenseApproveLevel1View(ProjectFinancialPermissionMixin, LoginRequiredMixin, View):
    def post(self, request, pk, *args, **kwargs):
        expense = get_object_or_404(
            dm.ProjectExpense.objects.select_related("project", "project__workspace"),
            pk=pk,
        )

        if not self.can_approve_level1(expense):
            raise PermissionDenied("Vous n'avez pas le droit de valider cette dépense au niveau 1.")

        try:
            expense.approve_level1(request.user)
            messages.success(request, "Dépense validée au niveau 1.")
        except ValidationError as exc:
            messages.error(request, exc.message)

        return redirect("project_expense_detail", pk=expense.pk)


class ProjectExpenseApproveLevel2View(ProjectFinancialPermissionMixin, LoginRequiredMixin, View):
    def post(self, request, pk, *args, **kwargs):
        expense = get_object_or_404(
            dm.ProjectExpense.objects.select_related("project", "project__workspace"),
            pk=pk,
        )

        if not self.can_approve_level2(expense):
            raise PermissionDenied("Vous n'avez pas le droit de valider cette dépense au niveau 2.")

        try:
            expense.approve_level2(request.user)
            messages.success(request, "Dépense validée au niveau 2.")
        except ValidationError as exc:
            messages.error(request, exc.message)

        return redirect("project_expense_detail", pk=expense.pk)


from django.db.models import DecimalField as ModelDecimalField


class ProjectExpenseRejectView(ProjectFinancialPermissionMixin, LoginRequiredMixin, View):
    def post(self, request, pk, *args, **kwargs):
        expense = get_object_or_404(
            dm.ProjectExpense.objects.select_related("project", "project__workspace"),
            pk=pk,
        )

        if not (self.can_approve_level1(expense) or self.can_approve_level2(expense)):
            raise PermissionDenied("Vous n'avez pas le droit de rejeter cette dépense.")

        reason = request.POST.get("reason", "").strip()

        try:
            expense.reject(request.user, reason=reason)
            messages.warning(request, "Dépense rejetée.")
        except ValidationError as exc:
            messages.error(request, exc.message)

        return redirect("project_expense_detail", pk=expense.pk)


class ProjectExpenseListView(ProjectFinancialPermissionMixin, DevflowListView):
    model = dm.ProjectExpense
    template_name = "project/expense/list.html"
    context_object_name = "items"
    section = "project"
    page_title = "Dépenses projet"
    paginate_by = 20
    search_fields = ("title", "description", "vendor", "reference")

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .select_related(
                "project",
                "project__workspace",
                "project__owner",
                "project__product_manager",
                "category",
                "task",
                "sprint",
                "milestone",
                "created_by",
                "level1_approved_by",
                "level2_approved_by",
                "validated_by",
            )
        )

        project_id = self.request.GET.get("project")
        status = self.request.GET.get("status")
        approval_state = self.request.GET.get("approval_state")
        category_id = self.request.GET.get("category")

        if project_id:
            queryset = queryset.filter(project_id=project_id)

        if status:
            queryset = queryset.filter(status=status)

        if approval_state:
            queryset = queryset.filter(approval_state=approval_state)

        if category_id:
            queryset = queryset.filter(category_id=category_id)

        return queryset.order_by("-expense_date", "-created_at")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        project_id = self.request.GET.get("project")
        project = get_object_or_404(dm.Project, pk=project_id) if project_id else None

        money_field = DecimalField(max_digits=14, decimal_places=2)
        base_qs = self.get_queryset()

        stats = base_qs.aggregate(
            total_count=Count("id"),
            total_amount=Coalesce(Sum("amount"), Value(Decimal("0.00")), output_field=money_field),
            draft_amount=Coalesce(
                Sum("amount", filter=Q(status=dm.ProjectExpense.ExpenseStatus.DRAFT)),
                Value(Decimal("0.00")),
                output_field=money_field,
            ),
            estimated_amount=Coalesce(
                Sum("amount", filter=Q(status=dm.ProjectExpense.ExpenseStatus.ESTIMATED)),
                Value(Decimal("0.00")),
                output_field=money_field,
            ),
            forecast_amount=Coalesce(
                Sum("amount", filter=Q(status=dm.ProjectExpense.ExpenseStatus.FORECAST)),
                Value(Decimal("0.00")),
                output_field=money_field,
            ),
            committed_amount=Coalesce(
                Sum("amount", filter=Q(status=dm.ProjectExpense.ExpenseStatus.COMMITTED)),
                Value(Decimal("0.00")),
                output_field=money_field,
            ),
            accrued_amount=Coalesce(
                Sum("amount", filter=Q(status=dm.ProjectExpense.ExpenseStatus.ACCRUED)),
                Value(Decimal("0.00")),
                output_field=money_field,
            ),
            paid_amount=Coalesce(
                Sum("amount", filter=Q(status=dm.ProjectExpense.ExpenseStatus.PAID)),
                Value(Decimal("0.00")),
                output_field=money_field,
            ),
            validated_amount=Coalesce(
                Sum("amount", filter=Q(status=dm.ProjectExpense.ExpenseStatus.VALIDATED)),
                Value(Decimal("0.00")),
                output_field=money_field,
            ),
            rejected_amount=Coalesce(
                Sum("amount", filter=Q(status=dm.ProjectExpense.ExpenseStatus.REJECTED)),
                Value(Decimal("0.00")),
                output_field=money_field,
            ),
        )

        # On enrichit les objets paginés pour le template
        items_page = ctx.get("items")
        if items_page:
            for expense in items_page:
                expense.user_can_approve_level1 = self.can_approve_level1(expense)
                expense.user_can_approve_level2 = self.can_approve_level2(expense)

                expense.user_can_validate_l1 = (
                    expense.user_can_approve_level1
                    and expense.approval_state == dm.ProjectExpense.ApprovalState.PENDING
                )
                expense.user_can_validate_l2 = (
                    expense.user_can_approve_level2
                    and expense.approval_state == dm.ProjectExpense.ApprovalState.LEVEL1_APPROVED
                )
                expense.user_can_reject = (
                    expense.user_can_approve_level1 or expense.user_can_approve_level2
                )

        ctx.update({
            "project_obj": project,
            "status_choices": dm.ProjectExpense.ExpenseStatus.choices,
            "approval_state_choices": dm.ProjectExpense.ApprovalState.choices,
            "current_status": self.request.GET.get("status", ""),
            "current_approval_state": self.request.GET.get("approval_state", ""),
            "current_category": self.request.GET.get("category", ""),
            "stats": stats,
            "categories": dm.CostCategory.objects.order_by("name"),
        })
        return ctx

class ProjectExpenseDetailView(ProjectFinancialPermissionMixin, DevflowDetailView):
    model = dm.ProjectExpense
    template_name = "project/expense/detail.html"
    context_object_name = "item"
    section = "project"
    page_title = "Détail dépense"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related(
                "project",
                "project__workspace",
                "project__owner",
                "project__product_manager",
                "category",
                "task",
                "sprint",
                "milestone",
                "created_by",
                "level1_approved_by",
                "level2_approved_by",
                "validated_by",
                "rejected_by",
            )
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        expense = self.object

        expense.user_can_approve_level1 = self.can_approve_level1(expense)
        expense.user_can_approve_level2 = self.can_approve_level2(expense)
        expense.user_can_reject = expense.user_can_approve_level1 or expense.user_can_approve_level2

        expense.user_can_validate_l1 = (
            expense.user_can_approve_level1
            and expense.approval_state == dm.ProjectExpense.ApprovalState.PENDING
        )
        expense.user_can_validate_l2 = (
            expense.user_can_approve_level2
            and expense.approval_state == dm.ProjectExpense.ApprovalState.LEVEL1_APPROVED
        )

        ctx["can_approve_level1"] = expense.user_can_approve_level1
        ctx["can_approve_level2"] = expense.user_can_approve_level2
        ctx["user_can_reject"] = expense.user_can_reject
        return ctx

class ProjectExpenseCreateView(ProjectFinancialPermissionMixin, DevflowCreateView):
    model = dm.ProjectExpense
    form_class = ProjectExpenseForm
    template_name = "project/expense/form.html"
    section = "project"
    page_title = "Ajouter dépense projet"

    def get_success_url(self):
        return reverse_lazy("project_detail", kwargs={"pk": self.object.project_id})

    def form_valid(self, form):
        project_id = self.request.GET.get("project")
        if project_id:
            form.instance.project = get_object_or_404(dm.Project, pk=project_id)
        form.instance.created_by = self.request.user
        messages.success(self.request, "Dépense ajoutée.")
        return super().form_valid(form)


class GenerateEstimateLinesFromTasksView(ProjectFinancialPermissionMixin, LoginRequiredMixin, View):
    def post(self, request, project_id):
        project = get_object_or_404(dm.Project, pk=project_id)
        if not self.can_view_financials(project):
            messages.error(request, "Accès non autorisé.")
            return redirect("project_detail", pk=project.pk)

        created_count = ProjectBudgetService.regenerate_estimate_lines_from_tasks(
            project=project,
            user=request.user,
            replace_existing=request.POST.get("replace") == "1",
        )

        messages.success(
            request,
            f"{created_count} ligne(s) d'estimation générée(s) depuis les tâches."
        )
        return redirect("project_detail", pk=project.pk)


class RecalculateProjectBudgetView(ProjectFinancialPermissionMixin, LoginRequiredMixin, View):
    def post(self, request, project_id):
        project = get_object_or_404(dm.Project, pk=project_id)
        if not self.can_view_financials(project):
            messages.error(request, "Accès non autorisé.")
            return redirect("project_detail", pk=project.pk)

        ProjectBudgetService.regenerate_budget_from_estimates(
            project=project,
            approved_by=request.user,
        )

        messages.success(request, "Budget recalculé à partir des lignes d'estimation.")
        return redirect("project_detail", pk=project.pk)


class RefreshProjectFinancialsView(ProjectFinancialPermissionMixin, LoginRequiredMixin, View):
    """Recalcul intelligent global : RAF + budget + overview."""

    def post(self, request, project_id):
        project = get_object_or_404(dm.Project, pk=project_id)
        if not self.can_view_financials(project):
            messages.error(request, "Accès non autorisé.")
            return redirect("project_detail", pk=project.pk)

        ProjectBudgetService.refresh_project_financials(
            project=project,
            user=request.user,
            rebuild_budget=True,
        )
        ProjectBudgetService.regenerate_raf_lines_from_tasks(
            project=project,
            user=request.user,
            replace_existing=True,
        )

        messages.success(request, "Données financières du projet rafraîchies.")
        return redirect("project_detail", pk=project.pk)
