from django import forms

from project import models as dm


BASE_INPUT_CLASS = (
    "w-full rounded-[14px] border border-devborder bg-devbg3 "
    "px-4 py-3 text-sm text-devtext1 placeholder:text-devtext3 "
    "focus:outline-none focus:ring-0 focus:border-devaccent"
)

BASE_SELECT_CLASS = (
    "w-full rounded-[14px] border border-devborder bg-devbg3 "
    "px-4 py-3 text-sm text-devtext1 js-select2 "
    "focus:outline-none focus:ring-0 focus:border-devaccent"
)

BASE_TEXTAREA_CLASS = (
    "w-full rounded-[14px] border border-devborder bg-devbg3 "
    "px-4 py-3 text-sm text-devtext1 placeholder:text-devtext3 "
    "focus:outline-none focus:ring-0 focus:border-devaccent min-h-[140px]"
)

BASE_EDITOR_CLASS = (
    "w-full rounded-[14px] border border-devborder bg-devbg3 "
    "px-4 py-3 text-sm text-devtext1 js-tinymce"
)

BASE_CHECKBOX_CLASS = (
    "h-4 w-4 rounded border-devborder text-devaccent "
    "focus:ring-devaccent"
)

BASE_DATE_CLASS = (
    "w-full rounded-[14px] border border-devborder bg-devbg3 "
    "px-4 py-3 text-sm text-devtext1 "
    "focus:outline-none focus:ring-0 focus:border-devaccent"
)


class StyledModelForm(forms.ModelForm):
    """
    Base form DevFlow:
    - select => select2
    - textarea description/notes => tinymce
    - autres champs => classes Tailwind homogènes
    """

    tinymce_field_names = {"description", "notes", "summary", "comment", "body"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for name, field in self.fields.items():
            widget = field.widget

            if isinstance(widget, forms.CheckboxInput):
                css = BASE_CHECKBOX_CLASS

            elif isinstance(widget, forms.Select):
                css = BASE_SELECT_CLASS
                widget.attrs.setdefault("data-control", "select2")
                widget.attrs.setdefault("data-placeholder", f"Sélectionner {field.label.lower()}")

            elif isinstance(widget, forms.SelectMultiple):
                css = BASE_SELECT_CLASS
                widget.attrs.setdefault("data-control", "select2")
                widget.attrs.setdefault("data-placeholder", f"Sélectionner {field.label.lower()}")

            elif isinstance(widget, forms.Textarea):
                if name in self.tinymce_field_names:
                    css = BASE_EDITOR_CLASS
                    widget.attrs.setdefault("data-tinymce", "1")
                    widget.attrs.setdefault("data-editor-height", "320")
                else:
                    css = BASE_TEXTAREA_CLASS

            elif isinstance(widget, (forms.DateInput, forms.DateTimeInput)):
                css = BASE_DATE_CLASS

            else:
                css = BASE_INPUT_CLASS

            existing = widget.attrs.get("class", "")
            widget.attrs["class"] = f"{existing} {css}".strip()

            if isinstance(
                widget,
                (
                    forms.TextInput,
                    forms.NumberInput,
                    forms.EmailInput,
                    forms.URLInput,
                    forms.PasswordInput,
                ),
            ):
                widget.attrs.setdefault("placeholder", field.label)

            widget.attrs.setdefault("autocomplete", "off")


class ProjectBudgetForm(StyledModelForm):
    class Meta:
        model = dm.ProjectBudget
        fields = [
            "status",
            "currency",
            "estimated_labor_cost",
            "estimated_software_cost",
            "estimated_infra_cost",
            "estimated_subcontract_cost",
            "estimated_other_cost",
            "contingency_amount",
            "version_number",
            "target_margin_percent",
            "markup_percent",
            "planned_revenue",
            "approved_budget",
            "alert_threshold_percent",
            "notes",
        ]
        widgets = {
            "status": forms.Select(),
            "currency": forms.TextInput(),
            "estimated_labor_cost": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "estimated_software_cost": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "estimated_infra_cost": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "estimated_subcontract_cost": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "estimated_other_cost": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "contingency_amount": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "version_number": forms.NumberInput(attrs={"min": "1"}),
            "target_margin_percent": forms.NumberInput(attrs={"min": "0", "max": "100"}),
            "markup_percent": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "planned_revenue": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "approved_budget": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "alert_threshold_percent": forms.NumberInput(attrs={"min": "0", "max": "100"}),
            "notes": forms.Textarea(),
        }


class ProjectEstimateLineForm(StyledModelForm):
    class Meta:
        model = dm.ProjectEstimateLine
        fields = [
            "category",
            "source_type",
            "task",
            "sprint",
            "milestone",
            "label",
            "description",
            "quantity",
            "cost_unit_amount",
            "markup_percent",
        ]
        widgets = {
            "category": forms.Select(),
            "source_type": forms.Select(),
            "task": forms.Select(),
            "sprint": forms.Select(),
            "milestone": forms.Select(),
            "label": forms.TextInput(),
            "description": forms.Textarea(),
            "quantity": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "cost_unit_amount": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "markup_percent": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
        }


class ProjectRevenueForm(StyledModelForm):
    class Meta:
        model = dm.ProjectRevenue
        fields = [
            "revenue_type",
            "title",
            "amount",
            "currency",
            "expected_date",
            "received_date",
            "notes",
        ]
        widgets = {
            "revenue_type": forms.Select(),
            "title": forms.TextInput(),
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "currency": forms.TextInput(),
            "expected_date": forms.DateInput(attrs={"type": "date"}),
            "received_date": forms.DateInput(attrs={"type": "date"}),
            "is_received": forms.CheckboxInput(),
            "notes": forms.Textarea(),
        }


class ProjectExpenseForm(StyledModelForm):
    class Meta:
        model = dm.ProjectExpense
        fields = [
            "category",
            "task",
            "sprint",
            "milestone",
            "title",
            "description",
            "status",
            "expense_date",
            "committed_date",
            "paid_date",
            "amount",
            "currency",
            "vendor",
            "reference",
            "is_direct_cost",
            "is_labor_cost",
        ]
        widgets = {
            "category": forms.Select(),
            "task": forms.Select(),
            "sprint": forms.Select(),
            "milestone": forms.Select(),
            "title": forms.TextInput(),
            "description": forms.Textarea(attrs={"data-tinymce": "1"}),
            "status": forms.Select(),
            "expense_date": forms.DateInput(attrs={"type": "date"}),
            "committed_date": forms.DateInput(attrs={"type": "date"}),
            "paid_date": forms.DateInput(attrs={"type": "date"}),
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "currency": forms.TextInput(),
            "vendor": forms.TextInput(),
            "reference": forms.TextInput(),
            "is_direct_cost": forms.CheckboxInput(),
            "is_labor_cost": forms.CheckboxInput(),
        }

    def clean(self):
        cleaned = super().clean()
        is_direct_cost = cleaned.get("is_direct_cost")
        is_labor_cost = cleaned.get("is_labor_cost")

        if is_direct_cost and is_labor_cost:
            self.add_error("is_labor_cost", "Une dépense ne peut pas être à la fois directe et main-d'œuvre.")

        return cleaned