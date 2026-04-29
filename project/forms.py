from __future__ import annotations

from decimal import Decimal

from allauth.account.forms import SignupForm
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordChangeForm
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import (
    APIKey,
    AInsight,
    ActivityLog,
    BacklogItem,
    BoardColumn,
    ChannelMembership,
    ChecklistItem,
    DashboardSnapshot,
    DirectChannel,
    Integration,
    KeyResult,
    Label,
    Message,
    MessageAttachment,
    Milestone,
    MilestoneTask,
    Notification,
    Objective,
    Project,
    ProjectLabel,
    ProjectMember,
    PullRequest,
    Reaction,
    Release,
    Risk,
    Roadmap,
    RoadmapItem,
    Sprint,
    SprintMetric,
    SprintReview,
    SprintRetrospective,
    Task,
    TaskAssignment,
    TaskAttachment,
    TaskChecklist,
    TaskComment,
    TaskDependency,
    TaskLabel,
    Team,
    TeamMembership,
    TimesheetEntry,
    UserPreference,
    Webhook,
    Workspace,
    WorkspaceInvitation,
    WorkspaceSettings,
    UserProfile, ProjectDocumentImport,
)
from .models import Invoice, InvoiceLine, InvoicePayment, InvoiceClient

User = get_user_model()


def _user_choice_label(user) -> str:
    """
    Affichage standardisé d'un utilisateur dans les <select> de formulaire :
    « Prénom Nom » si renseigné, sinon « Prénom » ou « Nom » seul,
    sinon username, sinon email. On suffixe par l'email entre parenthèses
    quand un nom complet existe, pour différencier les homonymes.
    """
    if user is None:
        return ""
    first = (getattr(user, "first_name", "") or "").strip()
    last = (getattr(user, "last_name", "") or "").strip()
    full = (first + " " + last).strip()
    email = (getattr(user, "email", "") or "").strip()
    username = (getattr(user, "username", "") or "").strip()

    if full and email:
        return f"{full} ({email})"
    if full:
        return full
    if username:
        return username
    return email or f"User #{user.pk}"

class CustomSignupForm(SignupForm):

    first_name = forms.CharField(
        label="Prénom",
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={"placeholder": "Votre prénom"}),
    )
    last_name = forms.CharField(
        label="Nom",
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={"placeholder": "Votre nom"}),
    )
    def save(self, request):
        user = super().save(request)
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.save(update_fields=["first_name", "last_name"])
        return user
# =============================================================================
# STYLE CONSTANTS
# =============================================================================
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

BASE_FILE_CLASS = (
    "w-full rounded-[14px] border border-devborder bg-devbg3 "
    "px-4 py-3 text-sm text-devtext1"
)

TINYMCE_FIELDS = {
    "description",
    "notes",
    "body",
    "summary",
    "recommendation",
    "demo_notes",
    "stakeholder_feedback",
    "went_well",
    "to_improve",
    "action_items",
    "acceptance_criteria",
    "mitigation_plan",
    "changelog",
    "error_message",
}


# =============================================================================
# BASE FORM
# =============================================================================
class BaseStyledModelForm(forms.ModelForm):
    """
    Formulaire de base DevFlow :
    - select => select2
    - textarea métier => TinyMCE
    - styles homogènes
    """

    def __init__(self, *args, **kwargs):
        self.current_workspace = kwargs.pop("current_workspace", None)
        self.allowed_workspaces = kwargs.pop("allowed_workspaces", None)
        self.request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)

        # Affichage prénom + nom (fallback username) pour TOUS les selects User
        _user_label = _user_choice_label
        for field in self.fields.values():
            if isinstance(field, (forms.ModelChoiceField, forms.ModelMultipleChoiceField)):
                qs = getattr(field, "queryset", None)
                model = getattr(qs, "model", None) if qs is not None else None
                if model is User:
                    field.label_from_instance = _user_label

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
                if name in TINYMCE_FIELDS:
                    css = BASE_EDITOR_CLASS
                    widget.attrs.setdefault("data-tinymce", "1")
                    widget.attrs.setdefault("data-editor-height", "320")
                else:
                    css = BASE_TEXTAREA_CLASS
                    widget.attrs.setdefault("rows", 4)

            elif isinstance(widget, forms.DateTimeInput):
                css = BASE_DATE_CLASS
                widget.attrs.setdefault("type", "datetime-local")

            elif isinstance(widget, forms.DateInput):
                css = BASE_DATE_CLASS
                widget.attrs.setdefault("type", "date")

            elif isinstance(widget, forms.ClearableFileInput):
                css = BASE_FILE_CLASS

            else:
                css = BASE_INPUT_CLASS

            existing = widget.attrs.get("class", "")
            widget.attrs["class"] = f"{existing} {css}".strip()

            if not isinstance(widget, (forms.CheckboxInput, forms.FileInput, forms.ClearableFileInput)):
                widget.attrs.setdefault("placeholder", field.label or name.replace("_", " ").title())

            widget.attrs.setdefault("autocomplete", "off")



# =============================================================================
# USER / PROFILE
# =============================================================================
class UserProfileForm(BaseStyledModelForm):
    class Meta:
        model = UserProfile
        fields = [
            "workspace",
            "job_title",
            "seniority",
            "contract_type",
            "avatar",
            "phone",
            "location",
            "capacity_hours_per_day",
            "capacity_hours_per_week",
            "availability_percent",
            "cost_per_day",
            "billable_rate_per_day",
            "currency",
            "performance_score",
            "velocity_contribution",
            "is_billable",
            "is_active",
            "joined_company_at",
        ]
        widgets = {
            "joined_company_at": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date"},
            ),
            "job_title": forms.TextInput(attrs={"placeholder": "Ex: CTO, Backend Lead, Product Manager"}),
            "phone": forms.TextInput(attrs={"placeholder": "Ex: +225 07 00 00 00 00"}),
            "location": forms.TextInput(attrs={"placeholder": "Ex: Abidjan, Remote"}),
            "currency": forms.TextInput(attrs={"placeholder": "Ex: XOF"}),
        }


class UserAccountForm(BaseStyledModelForm):
    class Meta:
        model = User
        fields = [
            "first_name",
            "last_name",
            "email",
        ]
        widgets = {
            "first_name": forms.TextInput(attrs={"placeholder": "Prénom"}),
            "last_name": forms.TextInput(attrs={"placeholder": "Nom"}),
            "email": forms.EmailInput(attrs={"placeholder": "Email"}),
        }


class DevFlowPasswordChangeForm(PasswordChangeForm):
    old_password = forms.CharField(
        label="Mot de passe actuel",
        widget=forms.PasswordInput(attrs={
            "autocomplete": "current-password",
            "class": BASE_INPUT_CLASS,
            "placeholder": "Mot de passe actuel",
        }),
    )
    new_password1 = forms.CharField(
        label="Nouveau mot de passe",
        widget=forms.PasswordInput(attrs={
            "autocomplete": "new-password",
            "class": BASE_INPUT_CLASS,
            "placeholder": "Nouveau mot de passe",
        }),
    )
    new_password2 = forms.CharField(
        label="Confirmation du nouveau mot de passe",
        widget=forms.PasswordInput(attrs={
            "autocomplete": "new-password",
            "class": BASE_INPUT_CLASS,
            "placeholder": "Confirmer le nouveau mot de passe",
        }),
    )


# =============================================================================
# WORKSPACE / TEAM
# =============================================================================
class WorkspaceForm(BaseStyledModelForm):
    class Meta:
        model = Workspace
        fields = [
            "name", "description", "logo",
            "owner", "is_active", "timezone", "quarter_label",
            # Papier en-tête / facturation
            "legal_name", "tagline",
            "legal_rccm", "legal_cc", "legal_tax_id",
            "address_line1", "address_line2",
            "postal_code", "city", "country",
            "phone", "website", "email",
            "bank_details", "invoice_footer_text",
            "accent_color",
        ]
        widgets = {
            "accent_color": forms.TextInput(attrs={"type": "color"}),
            "bank_details": forms.Textarea(attrs={"rows": 3}),
            "invoice_footer_text": forms.Textarea(attrs={"rows": 2}),
        }


class TeamForm(BaseStyledModelForm):
    class Meta:
        model = Team
        fields = [
            "workspace",
            "name",
            "description",
            "team_type",
            "lead",
            "color",
            "velocity_target",
            "velocity_current",
            "is_active",
        ]
        widgets = {
            "color": forms.TextInput(attrs={"type": "color"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        ws = self.current_workspace
        if ws and "lead" in self.fields:
            self.fields["lead"].queryset = User.objects.filter(
                devflow_memberships__workspace=ws,
                is_active=True,
            ).distinct().order_by("last_name", "first_name", "username")


class TeamMembershipForm(BaseStyledModelForm):
    class Meta:
        model = TeamMembership
        fields = [
            "workspace",
            "team",
            "user",
            "role",
            "status",
            "job_title",
            "capacity_points",
            "current_load_percent",
            "avatar_color",
            "joined_at",
        ]
        widgets = {
            "joined_at": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date"},
            ),
            "avatar_color": forms.TextInput(attrs={"type": "color"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        ws = self.current_workspace
        if ws:
            if "team" in self.fields:
                self.fields["team"].queryset = Team.objects.filter(
                    workspace=ws, is_archived=False
                ).order_by("name")
            if "user" in self.fields:
                # Tous les users actifs : on autorise à ajouter un user
                # pas encore membre du workspace (typique du flow d'onboarding).
                self.fields["user"].queryset = User.objects.filter(
                    is_active=True
                ).order_by("last_name", "first_name", "username")

    def clean_current_load_percent(self):
        value = self.cleaned_data.get("current_load_percent") or 0
        if value < 0 or value > 100:
            raise forms.ValidationError("La charge actuelle doit être comprise entre 0 et 100.")
        return value

    def clean(self):
        cleaned = super().clean()
        ws = cleaned.get("workspace") or self.current_workspace
        user = cleaned.get("user")
        team = cleaned.get("team")
        if ws and user:
            qs = TeamMembership.objects.filter(workspace=ws, user=user, team=team)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise ValidationError(
                    "Cet utilisateur est déjà membre %s." % (
                        f"de l'équipe « {team} »" if team else "du workspace (sans équipe)"
                    )
                )
        return cleaned


# =============================================================================
# PROJECTS
# =============================================================================
class ProjectForm(BaseStyledModelForm):

    class Meta:

        model = Project

        fields = [

            "workspace",

            "category",

            "team",

            "name",

            "code",

            "description",

            "tech_stack",

            "owner",

            "product_manager",

            "status",

            "priority",

            "health_status",

            "progress_percent",

            "ai_risk_label",

            "start_date",

            "target_date",

            "delivered_at",

            "budget",

            "is_favorite",

            "image",

        ]

        widgets = {

            "start_date": forms.DateInput(

                format="%Y-%m-%d",

                attrs={"type": "date"},

            ),

            "target_date": forms.DateInput(

                format="%Y-%m-%d",

                attrs={"type": "date"},

            ),

            "delivered_at": forms.DateInput(

                format="%Y-%m-%d",

                attrs={"type": "date"},

            ),

            "description": forms.Textarea(

                attrs={

                    "data-tinymce": "1",

                    "data-editor-height": "320",

                }

            ),

        }

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

        if "workspace" in self.fields:

            self.fields["workspace"].required = False

            self.fields["workspace"].help_text = "Le workspace peut être injecté automatiquement selon le contexte."

        if "category" in self.fields:

            self.fields["category"].required = False

            self.fields["category"].empty_label = "Sélectionner une catégorie"

            self.fields["category"].help_text = "Permet de classer le projet par typologie."

        if "team" in self.fields:

            self.fields["team"].required = False

            self.fields["team"].empty_label = "Sélectionner une équipe"

        if "owner" in self.fields:

            self.fields["owner"].required = False

            self.fields["owner"].empty_label = "Sélectionner un responsable"

        if "product_manager" in self.fields:

            self.fields["product_manager"].required = False

            self.fields["product_manager"].empty_label = "Sélectionner un product manager"

        if "name" in self.fields:

            self.fields["name"].widget.attrs["placeholder"] = "Ex: Plateforme Bestepargne"

        if "code" in self.fields:

            self.fields["code"].required = False

            self.fields["code"].widget.attrs["placeholder"] = "Ex: BEST-001 ou vide pour génération auto"

            self.fields["code"].help_text = "Laisser vide pour une génération automatique."

        if "tech_stack" in self.fields:

            self.fields["tech_stack"].widget.attrs["placeholder"] = "Django, Alpine.js, PostgreSQL..."

        if "description" in self.fields:

            self.fields["description"].widget.attrs["placeholder"] = (

                "Décrivez le périmètre, les objectifs, les parties prenantes et les livrables attendus."

            )

        if "progress_percent" in self.fields:

            self.fields["progress_percent"].widget.attrs.update(

                {

                    "min": 0,

                    "max": 100,

                    "placeholder": "0",

                }

            )

        if "ai_risk_label" in self.fields:

            self.fields["ai_risk_label"].required = False

            self.fields["ai_risk_label"].widget.attrs["placeholder"] = "Ex: Faible, Moyen, Élevé"

        if "budget" in self.fields:

            self.fields["budget"].required = False

            self.fields["budget"].widget.attrs["placeholder"] = "Montant en XOF"

        if "image" in self.fields:

            self.fields["image"].required = False

    def clean_progress_percent(self):

        value = self.cleaned_data.get("progress_percent")

        if value in [None, ""]:

            return 0

        if value < 0 or value > 100:

            raise ValidationError("Le pourcentage doit être entre 0 et 100.")

        return value

    def clean_budget(self):

        value = self.cleaned_data.get("budget")

        if value is not None and value < 0:

            raise ValidationError("Le budget ne peut pas être négatif.")

        return value

    def clean_code(self):

        value = self.cleaned_data.get("code")

        if value:

            return value.strip().upper()

        return value

    def clean_name(self):

        value = self.cleaned_data.get("name")

        if value:

            return value.strip()

        return value

    def clean(self):

        cleaned = super().clean()

        start = cleaned.get("start_date")

        target = cleaned.get("target_date")

        delivered = cleaned.get("delivered_at")

        progress = cleaned.get("progress_percent") or 0

        status = cleaned.get("status")

        if start and target and target < start:

            self.add_error("target_date", "La date cible doit être postérieure à la date de début.")

        if delivered and start and delivered < start:

            self.add_error("delivered_at", "La date de livraison ne peut pas être avant la date de début.")

        if delivered and progress < 100:

            self.add_error("progress_percent", "Un projet livré doit être à 100%.")

        if progress == 100 and not delivered:

            self.add_error("delivered_at", "Veuillez renseigner la date de livraison pour un projet terminé.")

        if status == Project.Status.DONE and not delivered:

            self.add_error("delivered_at", "Veuillez renseigner la date de livraison pour un projet terminé.")

        if target and target < timezone.now().date() and progress < 100:

            self.add_error("target_date", "Ce projet est en retard par rapport à sa date cible.")

        return cleaned

    def save(self, commit=True):

        obj = super().save(commit=False)

        progress = obj.progress_percent or 0

        risk_score = getattr(obj, "risk_score", 0) or 0

        if hasattr(obj, "status"):

            if progress >= 100:

                obj.status = Project.Status.DONE

            elif progress > 0 and obj.status == Project.Status.PLANNED:

                obj.status = Project.Status.IN_PROGRESS

        if hasattr(obj, "health_status"):

            if risk_score >= 70:

                obj.health_status = Project.HealthStatus.RED

            elif risk_score >= 40:

                obj.health_status = Project.HealthStatus.AMBER

            elif risk_score > 0:

                obj.health_status = Project.HealthStatus.GREEN

            else:

                obj.health_status = Project.HealthStatus.GRAY

        if commit:

            obj.save()

            self.save_m2m()

        return obj

class ProjectDocumentImportForm(BaseStyledModelForm):
    class Meta:
        model = ProjectDocumentImport
        fields = [
            "project",
            "file",
            "status",
        ]
        widgets = {
            "project": forms.Select(),
            "file": forms.ClearableFileInput(),
            "status": forms.Select(),
        }

    def __init__(self, *args, **kwargs):
        workspace = kwargs.pop("workspace", None)
        project = kwargs.pop("project", None)
        super().__init__(*args, **kwargs)

        self.fields["status"].required = False

        if workspace is not None:
            self.fields["project"].queryset = (
                Project.objects.filter(workspace=workspace, is_archived=False)
                .select_related("workspace", "team", "owner", "product_manager", "category")
                .order_by("name")
            )
        else:
            self.fields["project"].queryset = (
                Project.objects.filter(is_archived=False)
                .select_related("workspace", "team", "owner", "product_manager", "category")
                .order_by("name")
            )

        if project is not None:
            self.fields["project"].initial = project
            self.fields["project"].widget.attrs["readonly"] = True

    def clean_status(self):
        status = self.cleaned_data.get("status")
        return status or ProjectDocumentImport.ImportStatus.UPLOADED

class ProjectMemberForm(BaseStyledModelForm):
    class Meta:
        model = ProjectMember
        fields = [
            "project",
            "user",
            "team",
            "role",
            "allocation_percent",
            "is_primary",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        ws = self.current_workspace
        if ws:
            if "project" in self.fields:
                self.fields["project"].queryset = Project.objects.filter(
                    workspace=ws, is_archived=False
                ).order_by("name")
            if "team" in self.fields:
                self.fields["team"].queryset = Team.objects.filter(
                    workspace=ws, is_archived=False
                ).order_by("name")
            if "user" in self.fields:
                self.fields["user"].queryset = User.objects.filter(
                    is_active=True,
                    devflow_memberships__workspace=ws,
                ).distinct().order_by("last_name", "first_name", "username")

    def clean_allocation_percent(self):
        value = self.cleaned_data.get("allocation_percent") or 0
        if value < 0 or value > 100:
            raise forms.ValidationError("L'allocation doit être comprise entre 0 et 100.")
        return value

    def clean(self):
        cleaned = super().clean()
        user = cleaned.get("user")
        project = cleaned.get("project")
        new_alloc = cleaned.get("allocation_percent") or 0

        if user and project:
            # Vérifie qu'il n'y a pas déjà ce ProjectMember
            qs = ProjectMember.objects.filter(project=project, user=user)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise ValidationError(
                    f"{user} est déjà membre du projet « {project} »."
                )

            # Vérifie la capacité totale (allocation cumulée sur projets actifs)
            from django.db.models import Sum
            qs_active = ProjectMember.objects.filter(
                user=user, project__is_archived=False
            )
            if self.instance.pk:
                qs_active = qs_active.exclude(pk=self.instance.pk)
            current = qs_active.aggregate(s=Sum("allocation_percent"))["s"] or 0
            total = current + new_alloc
            if total > 100:
                # Avertissement non-bloquant via non_field_errors WARNING-niveau ?
                # On bloque par sécurité ; pour un mode soft, basculer en
                # self.add_error(None, ...).
                raise ValidationError(
                    f"Cette affectation porterait {user} à {total}% d'allocation "
                    f"totale (limite 100%). Réduisez l'allocation ou désactivez "
                    f"un autre projet."
                )
        return cleaned


# =============================================================================
# SPRINTS
# =============================================================================
class SprintForm(BaseStyledModelForm):
    class Meta:
        model = Sprint
        fields = [
            "workspace",
            "project",
            "team",
            "name",
            "number",
            "goal",
            "status",
            "start_date",
            "end_date",
            "velocity_target",
            "velocity_completed",
            "total_story_points",
            "completed_story_points",
            "remaining_story_points",
        ]
        widgets = {
            "start_date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date"},
            ),
            "end_date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date"},
            ),
        }

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        if start_date and end_date and end_date < start_date:
            self.add_error("end_date", "La date de fin doit être postérieure à la date de début.")
        return cleaned_data


class SprintMetricForm(BaseStyledModelForm):
    class Meta:
        model = SprintMetric
        fields = [
            "sprint",
            "metric_date",
            "planned_remaining_points",
            "actual_remaining_points",
            "completed_tasks",
            "added_scope_points",
            "removed_scope_points",
        ]
        widgets = {
            "metric_date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date"},
            ),
        }


class SprintReviewForm(BaseStyledModelForm):
    class Meta:
        model = SprintReview
        fields = [
            "sprint",
            "held_at",
            "facilitator",
            "demo_notes",
            "accepted_stories",
            "stakeholder_feedback",
            "velocity_actual",
        ]
        widgets = {
            "held_at": forms.DateTimeInput(),
        }


class SprintRetrospectiveForm(BaseStyledModelForm):
    class Meta:
        model = SprintRetrospective
        fields = [
            "sprint",
            "held_at",
            "facilitator",
            "went_well",
            "to_improve",
            "action_items",
            "mood_score",
        ]
        widgets = {
            "held_at": forms.DateTimeInput(),
        }

    def clean_mood_score(self):
        value = self.cleaned_data.get("mood_score")
        if value is not None and (value < 1 or value > 5):
            raise forms.ValidationError("Le score d’humeur doit être entre 1 et 5.")
        return value


# =============================================================================
# BACKLOG / TASKS
# =============================================================================
class BacklogItemForm(BaseStyledModelForm):
    class Meta:
        model = BacklogItem
        fields = [
            "workspace",
            "project",
            "sprint",
            "parent",
            "title",
            "description",
            "item_type",
            "rank",
            "story_points",
            "acceptance_criteria",
            "reporter",
        ]



class TaskForm(BaseStyledModelForm):
    class Meta:
        model = Task
        fields = [
            "project",
            "sprint",
            "backlog_item",
            "parent",
            "title",
            "description",
            "status",
            "priority",
            "risk_score",
            "progress_percent",
            "estimate_hours",
            "spent_hours",
            "start_date",
            "due_date",
            "started_at",
            "completed_at",
            "assignee",
            "is_flagged",
        ]
        widgets = {
            "start_date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date"},
            ),
            "due_date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date"},
            ),
            "started_at": forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M",
                attrs={"type": "datetime-local"},
            ),
            "completed_at": forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M",
                attrs={"type": "datetime-local"},
            ),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        self.fields["due_date"].input_formats = ["%Y-%m-%d"]
        self.fields["started_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["completed_at"].input_formats = ["%Y-%m-%dT%H:%M"]

        if self.instance and self.instance.pk:
            if self.instance.due_date:
                self.initial["due_date"] = self.instance.due_date.strftime("%Y-%m-%d")
            if self.instance.started_at:
                self.initial["started_at"] = self.instance.started_at.strftime("%Y-%m-%dT%H:%M")
            if self.instance.completed_at:
                self.initial["completed_at"] = self.instance.completed_at.strftime("%Y-%m-%dT%H:%M")

        if user and user.is_authenticated:
            workspace = getattr(getattr(user, "profile", None), "workspace", None)

            if workspace:
                self.fields["project"].queryset = self.fields["project"].queryset.filter(
                    workspace=workspace,
                    is_archived=False,
                ).order_by("name")

                self.fields["sprint"].queryset = Sprint.objects.filter(
                    workspace=workspace,
                    is_archived=False,
                ).order_by("-start_date")

                self.fields["backlog_item"].queryset = BacklogItem.objects.filter(
                    workspace=workspace,
                    is_archived=False,
                ).order_by("rank", "title")

                self.fields["parent"].queryset = Task.objects.filter(
                    workspace=workspace,
                    is_archived=False,
                ).order_by("title")

                # Si on a un projet en initial OU sur l'instance, on restreint
                # les assignees aux membres du projet (UX plus fluide, évite
                # de proposer tout le workspace).
                project_id = (
                    (self.initial.get("project") if self.initial else None)
                    or (self.data.get("project") if self.data else None)
                    or (getattr(self.instance, "project_id", None) if self.instance else None)
                )

                assignee_qs = get_user_model().objects.filter(
                    is_active=True,
                    devflow_memberships__workspace=workspace,
                ).distinct()

                if project_id:
                    project_member_ids = list(
                        ProjectMember.objects.filter(project_id=project_id)
                        .values_list("user_id", flat=True)
                    )
                    if project_member_ids:
                        assignee_qs = get_user_model().objects.filter(
                            pk__in=project_member_ids, is_active=True
                        )

                self.fields["assignee"].queryset = assignee_qs.order_by("username")

                # Pré-remplissage de l'assignee depuis l'URL (?assignee=N)
                # — utile quand on crée une tâche depuis la fiche d'un membre.
                if not self.instance.pk and not self.initial.get("assignee"):
                    pass  # le pré-remplissage par GET est géré dans la vue

    def clean_progress_percent(self):
        value = self.cleaned_data.get("progress_percent") or 0
        if value < 0 or value > 100:
            raise forms.ValidationError("Le pourcentage d'avancement doit être compris entre 0 et 100.")
        return value

    def clean_risk_score(self):
        value = self.cleaned_data.get("risk_score") or 0
        if value < 0 or value > 100:
            raise forms.ValidationError("Le score de risque doit être compris entre 0 et 100.")
        return value

    def clean(self):
        cleaned_data = super().clean()

        project = cleaned_data.get("project")
        sprint = cleaned_data.get("sprint")
        backlog_item = cleaned_data.get("backlog_item")
        parent = cleaned_data.get("parent")

        if sprint and project and sprint.project_id != project.id:
            self.add_error("sprint", "Le sprint sélectionné n'appartient pas au projet choisi.")

        if backlog_item and project and backlog_item.project_id != project.id:
            self.add_error("backlog_item", "Le backlog item sélectionné n'appartient pas au projet choisi.")

        if parent and project and parent.project_id != project.id:
            self.add_error("parent", "La tâche parente sélectionnée n'appartient pas au projet choisi.")

        return cleaned_data

class TaskAssignmentForm(BaseStyledModelForm):
    class Meta:
        model = TaskAssignment
        fields = [
            "task",
            "user",
            "assigned_by",
            "allocation_percent",
            "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        ws = self.current_workspace
        if ws:
            if "task" in self.fields:
                self.fields["task"].queryset = Task.objects.filter(
                    workspace=ws, is_archived=False
                ).order_by("-updated_at")
            if "user" in self.fields:
                self.fields["user"].queryset = User.objects.filter(
                    is_active=True,
                    devflow_memberships__workspace=ws,
                ).distinct().order_by("last_name", "first_name", "username")
            if "assigned_by" in self.fields:
                self.fields["assigned_by"].queryset = User.objects.filter(
                    is_active=True,
                    devflow_memberships__workspace=ws,
                ).distinct().order_by("last_name", "first_name", "username")
                self.fields["assigned_by"].required = False
                # Si la requête est connue, on pré-remplit avec l'utilisateur courant.
                if self.request and not self.instance.pk:
                    self.fields["assigned_by"].initial = self.request.user

    def clean_allocation_percent(self):
        value = self.cleaned_data.get("allocation_percent") or 0
        if value < 0 or value > 100:
            raise forms.ValidationError("L'allocation doit être comprise entre 0 et 100.")
        return value

    def clean(self):
        cleaned = super().clean()
        task = cleaned.get("task")
        user = cleaned.get("user")
        if task and user:
            # L'utilisateur doit être membre du projet de la tâche
            is_member = ProjectMember.objects.filter(
                project=task.project, user=user
            ).exists()
            if not is_member:
                raise ValidationError(
                    f"{user} n'est pas membre du projet « {task.project} ». "
                    f"Ajoutez-le d'abord comme membre projet."
                )
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        # Synchroniser Task.assignee FK via Task.assign() pour cohérence
        if commit:
            if instance.is_active and instance.user_id and instance.task_id:
                instance.task.assign(
                    instance.user,
                    assigned_by=instance.assigned_by,
                    allocation_percent=instance.allocation_percent or 100,
                )
                # Récupérer l'instance créée par assign()
                instance = TaskAssignment.objects.get(
                    task=instance.task, user=instance.user
                )
            else:
                instance.save()
        return instance

class TaskCommentQuickForm(forms.ModelForm):
    class Meta:
        model = TaskComment
        fields = ["task", "body", "is_internal"]
        widgets = {
            "body": forms.Textarea(
                attrs={
                    "rows": 5,
                    "placeholder": "Clique ici et commence à écrire ton commentaire…",
                    "class": "w-full resize-none border-0 bg-transparent p-0 text-sm text-[var(--text1)] placeholder:text-[var(--text3)] focus:outline-none focus:ring-0",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        task = kwargs.pop("task", None)
        super().__init__(*args, **kwargs)

        self.fields["task"].queryset = Task.objects.select_related("project").order_by("-created_at")
        self.fields["task"].widget = forms.HiddenInput()

        if task:
            self.fields["task"].initial = task.pk

        self.fields["is_internal"].required = False


class TaskCommentForm(BaseStyledModelForm):
    class Meta:
        model = TaskComment
        fields = [
            "task",
            "author",
            "body",
            "is_internal",
            "edited_at",
        ]
        widgets = {
            "edited_at": forms.DateTimeInput(),
        }


class TaskAttachmentForm(BaseStyledModelForm):
    class Meta:
        model = TaskAttachment
        fields = [
            "task",
            "uploaded_by",
            "file",
            "name",
            "mime_type",
            "size",
        ]


class TaskDependencyForm(BaseStyledModelForm):
    class Meta:
        model = TaskDependency
        fields = [
            "from_task",
            "to_task",
            "dependency_type",
            "created_by",
        ]

    def clean(self):
        cleaned_data = super().clean()
        from_task = cleaned_data.get("from_task")
        to_task = cleaned_data.get("to_task")
        if from_task and to_task and from_task == to_task:
            self.add_error("to_task", "Une tâche ne peut pas dépendre d'elle-même.")
        return cleaned_data


class TaskChecklistForm(BaseStyledModelForm):
    class Meta:
        model = TaskChecklist
        fields = [
            "task",
            "title",
            "position",
        ]


class ChecklistItemForm(BaseStyledModelForm):
    class Meta:
        model = ChecklistItem
        fields = [
            "checklist",
            "text",
            "is_checked",
            "checked_by",
            "position",
        ]

    def save(self, commit=True):
        instance = super().save(commit=False)
        if instance.is_checked and not instance.checked_at:
            instance.checked_at = timezone.now()
        elif not instance.is_checked:
            instance.checked_at = None
            instance.checked_by = None
        if commit:
            instance.save()
        return instance


# =============================================================================
# PR / RISK / AI
# =============================================================================
class PullRequestForm(BaseStyledModelForm):
    class Meta:
        model = PullRequest
        fields = [
            "workspace",
            "project",
            "task",
            "external_id",
            "title",
            "repository",
            "branch_name",
            "author",
            "status",
            "reviewers_count",
            "comments_count",
            "opened_at",
            "merged_at",
            "url",
        ]
        widgets = {
            "opened_at": forms.DateTimeInput(),
            "merged_at": forms.DateTimeInput(),
        }


class RiskForm(BaseStyledModelForm):
    class Meta:
        model = Risk
        fields = [
            "workspace",
            "project",
            "task",
            "title",
            "description",
            "severity",
            "probability",
            "status",
            "impact_score",
            "owner",
            "mitigation_plan",
            "due_date",
            "escalated_at",
        ]
        widgets = {
            "due_date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date"},
            ),
            "escalated_at": forms.DateTimeInput(),
        }


class AInsightForm(BaseStyledModelForm):
    class Meta:
        model = AInsight
        fields = [
            "workspace",
            "project",
            "sprint",
            "task",
            "insight_type",
            "severity",
            "title",
            "summary",
            "recommendation",
            "score",
            "is_read",
            "is_dismissed",
            "detected_at",
        ]
        widgets = {
            "detected_at": forms.DateTimeInput(),
        }


# =============================================================================
# NOTIFICATIONS / ACTIVITY
# =============================================================================
class NotificationForm(BaseStyledModelForm):
    class Meta:
        model = Notification
        fields = [
            "recipient",
            "workspace",
            "notification_type",
            "title",
            "body",
            "url",
            "is_read",
            "read_at",
            "metadata",
        ]
        widgets = {
            "read_at": forms.DateTimeInput(),
            "metadata": forms.Textarea(attrs={"rows": 4}),
        }


class ActivityLogForm(BaseStyledModelForm):
    class Meta:
        model = ActivityLog
        fields = [
            "workspace",
            "actor",
            "project",
            "task",
            "sprint",
            "activity_type",
            "title",
            "description",
            "metadata",
        ]
        widgets = {
            "metadata": forms.Textarea(attrs={"rows": 4}),
        }


# =============================================================================
# CHANNELS / MESSAGES
# =============================================================================
class DirectChannelForm(BaseStyledModelForm):
    class Meta:
        model = DirectChannel
        fields = [
            "workspace",
            "name",
            "is_private",
            "members",
        ]


class ChannelMembershipForm(BaseStyledModelForm):
    class Meta:
        model = ChannelMembership
        fields = [
            "channel",
            "user",
            "joined_at",
            "is_muted",
        ]
        widgets = {
            "joined_at": forms.DateTimeInput(),
        }


class MessageForm(BaseStyledModelForm):
    class Meta:
        model = Message
        fields = [
            "channel",
            "author",
            "body",
            "is_edited",
            "edited_at",
            "parent",
        ]
        widgets = {
            "edited_at": forms.DateTimeInput(),
        }


class MessageAttachmentForm(BaseStyledModelForm):
    class Meta:
        model = MessageAttachment
        fields = [
            "message",
            "file",
            "name",
            "mime_type",
            "size",
        ]


class ReactionForm(BaseStyledModelForm):
    class Meta:
        model = Reaction
        fields = [
            "user",
            "emoji",
            "task_comment",
            "message",
        ]

    def clean(self):
        cleaned_data = super().clean()
        task_comment = cleaned_data.get("task_comment")
        message = cleaned_data.get("message")

        if not task_comment and not message:
            raise forms.ValidationError("Une réaction doit être liée à un commentaire ou à un message.")
        if task_comment and message:
            raise forms.ValidationError("Une réaction ne peut pas être liée aux deux à la fois.")
        return cleaned_data


# =============================================================================
# TIMESHEET / DASHBOARD / PREFERENCES
# =============================================================================
class TimesheetEntryForm(BaseStyledModelForm):
    class Meta:
        model = TimesheetEntry
        fields = [
            "user",
            "workspace",
            "project",
            "task",
            "entry_date",
            "hours",
            "description",
            "is_billable",
            "approved_by",
            "approved_at",
        ]
        widgets = {
            "entry_date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date"},
            ),
            "approved_at": forms.DateTimeInput(),
        }


class DashboardSnapshotForm(BaseStyledModelForm):
    class Meta:
        model = DashboardSnapshot
        fields = [
            "workspace",
            "snapshot_date",
            "active_projects",
            "completed_tasks",
            "pending_tasks",
            "blocked_tasks",
            "active_members",
            "remote_members",
            "portfolio_health_percent",
            "delivery_forecast_percent",
            "open_risks",
            "velocity_score",
            "payload",
        ]
        widgets = {
            "snapshot_date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date"},
            ),
            "payload": forms.Textarea(attrs={"rows": 4}),
        }


class UserPreferenceForm(BaseStyledModelForm):
    class Meta:
        model = UserPreference
        fields = [
            "user",
            "workspace",
            "theme",
            "sidebar_collapsed",
            "default_view",
            "show_ai_panel",
            "notifications_enabled",
        ]


# =============================================================================
# LABELS
# =============================================================================
class LabelForm(BaseStyledModelForm):
    class Meta:
        model = Label
        fields = [
            "workspace",
            "name",
            "color",
            "description",
        ]
        widgets = {
            "color": forms.TextInput(attrs={"type": "color"}),
        }


class TaskLabelForm(BaseStyledModelForm):
    class Meta:
        model = TaskLabel
        fields = [
            "task",
            "label",
            "added_by",
        ]


class ProjectLabelForm(BaseStyledModelForm):
    class Meta:
        model = ProjectLabel
        fields = [
            "project",
            "label",
        ]


# =============================================================================
# MILESTONES / RELEASES / ROADMAP
# =============================================================================
class MilestoneForm(BaseStyledModelForm):
    class Meta:
        model = Milestone
        fields = [
            "workspace",
            "project",
            "name",
            "description",
            "status",
            "due_date",
            "completed_at",
            "progress_percent",
            "owner",
        ]
        widgets = {
            "due_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "completed_at": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["due_date"].input_formats = ["%Y-%m-%d"]
        self.fields["completed_at"].input_formats = ["%Y-%m-%d"]

        if self.instance and self.instance.pk:
            if self.instance.due_date:
                self.initial["due_date"] = self.instance.due_date.strftime("%Y-%m-%d")
            if self.instance.completed_at:
                self.initial["completed_at"] = self.instance.completed_at.strftime("%Y-%m-%d")

        workspace_id = self.initial.get("workspace") or self.data.get("workspace") or getattr(self.instance, "workspace_id", None)

        if workspace_id:
            self.fields["project"].queryset = Project.objects.filter(
                workspace_id=workspace_id,
                is_archived=False,
            ).order_by("name")

            member_user_ids = Workspace.objects.get(pk=workspace_id).memberships.values_list("user_id", flat=True)
            self.fields["owner"].queryset = User.objects.filter(id__in=member_user_ids).order_by("username")

        self.fields["progress_percent"].widget.attrs.setdefault("min", 0)
        self.fields["progress_percent"].widget.attrs.setdefault("max", 100)
class MilestoneTaskForm(BaseStyledModelForm):
    class Meta:
        model = MilestoneTask
        fields = [
            "milestone",
            "task",
        ]


class ReleaseForm(BaseStyledModelForm):
    class Meta:
        model = Release
        fields = [
            "workspace",
            "project",
            "name",
            "tag",
            "description",
            "status",
            "release_date",
            "released_at",
            "changelog",
            "release_url",
            "tasks",
            "sprints",
        ]
        widgets = {
            "release_date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date"},
            ),
            "released_at": forms.DateTimeInput(),
        }


class RoadmapForm(BaseStyledModelForm):
    class Meta:
        model = Roadmap
        fields = ["workspace", "name", "description", "start_date", "end_date", "is_public", "owner"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if "workspace" in self.fields:
            if self.allowed_workspaces is not None:
                self.fields["workspace"].queryset = self.allowed_workspaces

            if self.current_workspace:
                self.fields["workspace"].initial = self.current_workspace.pk
                self.initial.setdefault("workspace", self.current_workspace.pk)
                self.fields["workspace"].required = False

                if self.allowed_workspaces is not None and self.allowed_workspaces.count() == 1:
                    self.fields["workspace"].widget = forms.HiddenInput()

    def clean_workspace(self):
        workspace = self.cleaned_data.get("workspace")

        if workspace:
            return workspace

        if self.current_workspace:
            return self.current_workspace

        raise forms.ValidationError("Ce champ est obligatoire.")

    def clean(self):
        cleaned = super().clean()

        start_date = cleaned.get("start_date")
        end_date = cleaned.get("end_date")

        if start_date and end_date and end_date < start_date:
            self.add_error("end_date", "La date de fin doit être postérieure ou égale à la date de début.")

        return cleaned


class RoadmapItemForm(BaseStyledModelForm):
    class Meta:
        model = RoadmapItem
        fields = [
            "roadmap",
            "project",
            "milestone",
            "title",
            "color",
            "status",
            "start_date",
            "end_date",
            "row",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "Titre de l’élément roadmap"}),
            "color": forms.TextInput(attrs={"type": "color"}),
            "start_date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date"},
            ),
            "end_date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date"},
            ),
            "row": forms.NumberInput(attrs={"min": 0, "step": 1}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        roadmap = None

        if self.instance and self.instance.pk:
            roadmap = self.instance.roadmap
        else:
            roadmap = self.initial.get("roadmap") or self.data.get("roadmap")

        if roadmap:
            self.fields["milestone"].queryset = Milestone.objects.filter(
                project__roadmap_items__roadmap_id=roadmap
            ).distinct()
        else:
            self.fields["milestone"].queryset = Milestone.objects.all()

    def clean_title(self):
        title = (self.cleaned_data.get("title") or "").strip()
        if len(title) < 3:
            raise forms.ValidationError("Le titre doit contenir au moins 3 caractères.")
        return title

    def clean_color(self):
        color = (self.cleaned_data.get("color") or "").strip()
        if not color.startswith("#") or len(color) not in (4, 7):
            raise forms.ValidationError("La couleur doit être au format hexadécimal, par exemple #F4722B.")
        return color

    def clean_row(self):
        row = self.cleaned_data.get("row")
        if row is not None and row < 0:
            raise forms.ValidationError("La ligne ne peut pas être négative.")
        return row

    def clean(self):
        cleaned_data = super().clean()

        roadmap = cleaned_data.get("roadmap")
        project = cleaned_data.get("project")
        milestone = cleaned_data.get("milestone")
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        row = cleaned_data.get("row")

        if start_date and end_date and end_date < start_date:
            self.add_error("end_date", "La date de fin doit être postérieure ou égale à la date de début.")

        if roadmap and start_date and start_date < roadmap.start_date:
            self.add_error("start_date", "La date de début doit être comprise dans la période de la roadmap.")

        if roadmap and end_date and end_date > roadmap.end_date:
            self.add_error("end_date", "La date de fin doit être comprise dans la période de la roadmap.")

        if milestone and project and milestone.project_id != project.id:
            self.add_error("milestone", "Le jalon sélectionné ne correspond pas au projet choisi.")

        if milestone and not project and milestone.project_id:
            cleaned_data["project"] = milestone.project

        if row is not None and row > 100:
            self.add_error("row", "La ligne d’affichage semble trop élevée.")

        return cleaned_data


class BoardColumnForm(BaseStyledModelForm):
    class Meta:
        model = BoardColumn
        fields = [
            "project",
            "name",
            "mapped_status",
            "position",
            "color",
            "wip_limit",
            "is_done_column",
        ]
        widgets = {
            "color": forms.TextInput(attrs={"type": "color"}),
        }


# =============================================================================
# INVITATIONS / INTEGRATIONS / WEBHOOKS
# =============================================================================
class WorkspaceInvitationForm(BaseStyledModelForm):
    """
    Formulaire d'invitation : on n'expose ni `token` (généré côté serveur),
    ni `accepted_at` / `status` (gérés par le workflow d'acceptation).
    `expires_at` est calculé automatiquement à J+14 si non fourni.
    """

    class Meta:
        model = WorkspaceInvitation
        fields = [
            "workspace",
            "email",
            "role",
            "team",
            "expires_at",
        ]
        widgets = {
            "expires_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        ws = self.current_workspace
        if ws and "team" in self.fields:
            self.fields["team"].queryset = Team.objects.filter(
                workspace=ws, is_archived=False
            ).order_by("name")
            self.fields["team"].required = False
        if "expires_at" in self.fields:
            self.fields["expires_at"].required = False

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if not email:
            raise ValidationError("Une adresse e-mail est requise.")
        ws = self.cleaned_data.get("workspace") or self.current_workspace
        if ws:
            existing = WorkspaceInvitation.objects.filter(
                workspace=ws, email__iexact=email,
                status=WorkspaceInvitation.Status.PENDING,
            )
            if self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise ValidationError(
                    "Une invitation est déjà en attente pour cette adresse."
                )
        return email

    def save(self, commit=True, *, invited_by=None, workspace=None):
        import secrets
        from datetime import timedelta

        self.instance.token = self.instance.token or secrets.token_urlsafe(48)
        if not self.instance.expires_at:
            self.instance.expires_at = timezone.now() + timedelta(days=14)
        if invited_by and not self.instance.invited_by_id:
            self.instance.invited_by = invited_by
        if workspace and not self.instance.workspace_id:
            self.instance.workspace = workspace
        if not self.instance.status:
            self.instance.status = WorkspaceInvitation.Status.PENDING
        return super().save(commit=commit)


class IntegrationForm(BaseStyledModelForm):
    class Meta:
        model = Integration
        fields = [
            "workspace",
            "provider",
            "name",
            "status",
            "config",
            "access_token_encrypted",
            "refresh_token_encrypted",
            "token_expires_at",
            "last_synced_at",
            "error_message",
            "installed_by",
        ]
        widgets = {
            "config": forms.Textarea(attrs={"rows": 4}),
            "token_expires_at": forms.DateTimeInput(),
            "last_synced_at": forms.DateTimeInput(),
        }


class WebhookForm(BaseStyledModelForm):
    class Meta:
        model = Webhook
        fields = [
            "workspace",
            "url",
            "secret",
            "events",
            "is_active",
            "last_triggered_at",
            "failure_count",
        ]
        widgets = {
            "events": forms.Textarea(attrs={"rows": 4}),
            "last_triggered_at": forms.DateTimeInput(),
        }


# =============================================================================
# API / SETTINGS / OKR
# =============================================================================
class APIKeyForm(BaseStyledModelForm):
    class Meta:
        model = APIKey
        fields = [
            "workspace",
            "created_by",
            "name",
            "key_hash",
            "key_prefix",
            "scope",
            "is_active",
            "last_used_at",
            "expires_at",
        ]
        widgets = {
            "last_used_at": forms.DateTimeInput(),
            "expires_at": forms.DateTimeInput(),
        }


class WorkspaceSettingsForm(BaseStyledModelForm):
    class Meta:
        model = WorkspaceSettings
        fields = [
            "workspace",
            "default_sprint_duration_days",
            "story_points_scale",
            "notify_task_assigned",
            "notify_task_due_soon",
            "notify_blocked_task",
            "notify_pr_review",
            "due_soon_threshold_days",
            "ai_insights_enabled",
            "ai_risk_auto_detect",
            "ai_workload_suggestions",
            "allow_guest_access",
            "require_2fa",
            "primary_color",
            "logo_url",
        ]
        widgets = {
            "story_points_scale": forms.Textarea(attrs={"rows": 3}),
            "primary_color": forms.TextInput(attrs={"type": "color"}),
        }


class ObjectiveForm(BaseStyledModelForm):
    class Meta:
        model = Objective
        fields = [
            "workspace",
            "team",
            "owner",
            "title",
            "description",
            "level",
            "status",
            "progress_percent",
            "start_date",
            "end_date",
            "quarter_label",
        ]
        widgets = {
            "start_date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date"},
            ),
            "end_date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date"},
            ),
        }

    def clean_progress_percent(self):
        value = self.cleaned_data.get("progress_percent") or 0
        if value < 0 or value > 100:
            raise forms.ValidationError("Le pourcentage d'avancement doit être compris entre 0 et 100.")
        return value

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        if start_date and end_date and end_date < start_date:
            self.add_error("end_date", "La date de fin doit être postérieure à la date de début.")
        return cleaned_data


class KeyResultForm(BaseStyledModelForm):
    class Meta:
        model = KeyResult
        fields = [
            "objective",
            "title",
            "result_type",
            "target_value",
            "current_value",
            "unit",
            "owner",
        ]

    def clean(self):
        cleaned_data = super().clean()
        target_value = cleaned_data.get("target_value")
        current_value = cleaned_data.get("current_value")

        if target_value is not None and target_value < 0:
            self.add_error("target_value", "La valeur cible doit être positive.")
        if current_value is not None and current_value < 0:
            self.add_error("current_value", "La valeur actuelle doit être positive.")

        return cleaned_data

# =============================================================================
# FACTURATION — InvoiceClient / Invoice / InvoiceLine / InvoicePayment
# =============================================================================
class InvoiceClientForm(BaseStyledModelForm):
    class Meta:
        model = InvoiceClient
        fields = [
            "workspace", "name", "legal_name", "tax_id",
            "email", "phone",
            "address_line1", "address_line2",
            "postal_code", "city", "country",
            "contact_name", "notes",
        ]


class InvoiceForm(BaseStyledModelForm):
    class Meta:
        model = Invoice
        fields = [
            "workspace", "project", "client",
            "number", "title", "notes",
            "issue_date", "due_date", "period_start", "period_end",
            "discount_amount", "tax_rate", "currency",
            "status", "billing_mode",
        ]
        widgets = {
            "issue_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "due_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "period_start": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "period_end": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        ws = self.current_workspace
        if ws:
            if "project" in self.fields:
                self.fields["project"].queryset = Project.objects.filter(
                    workspace=ws, is_archived=False
                ).order_by("name")
            if "client" in self.fields:
                self.fields["client"].queryset = InvoiceClient.objects.filter(
                    workspace=ws, is_archived=False
                ).order_by("name")
                self.fields["client"].required = False
        for date_field in ("issue_date", "due_date", "period_start", "period_end"):
            if date_field in self.fields:
                self.fields[date_field].input_formats = ["%Y-%m-%d"]

    def clean(self):
        cleaned = super().clean()
        issue = cleaned.get("issue_date")
        due = cleaned.get("due_date")
        if issue and due and due < issue:
            self.add_error("due_date", "L'échéance doit être après la date d'émission.")
        ps = cleaned.get("period_start")
        pe = cleaned.get("period_end")
        if ps and pe and pe < ps:
            self.add_error("period_end", "La fin de période doit être après le début.")
        rate = cleaned.get("tax_rate")
        if rate is not None and (rate < 0 or rate > 100):
            self.add_error("tax_rate", "Le taux doit être compris entre 0 et 100.")
        return cleaned


class InvoiceLineForm(BaseStyledModelForm):
    class Meta:
        model = InvoiceLine
        fields = [
            "invoice", "line_type", "label", "description",
            "quantity", "unit_price", "position",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        ws = self.current_workspace
        if ws and "invoice" in self.fields:
            self.fields["invoice"].queryset = Invoice.objects.filter(
                workspace=ws, is_archived=False
            ).order_by("-issue_date")


class InvoicePaymentForm(BaseStyledModelForm):
    class Meta:
        model = InvoicePayment
        fields = [
            "invoice", "amount", "received_at", "method",
            "reference", "status", "note",
        ]
        widgets = {
            "received_at": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "note": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "received_at" in self.fields:
            self.fields["received_at"].input_formats = ["%Y-%m-%d"]
        ws = self.current_workspace
        if ws and "invoice" in self.fields:
            self.fields["invoice"].queryset = Invoice.objects.filter(
                workspace=ws, is_archived=False
            ).order_by("-issue_date")

    def clean_amount(self):
        amount = self.cleaned_data.get("amount")
        if amount is None or amount <= 0:
            raise forms.ValidationError("Le montant du paiement doit être > 0.")
        return amount


class InvoiceGenerateForm(forms.Form):
    """Formulaire de génération automatique de facture depuis un projet."""
    MODE_CHOICES = [
        ("FIXED", "Forfait — depuis les Estimate Lines validés"),
        ("TIME_AND_MATERIALS", "Régie — depuis les Timesheets approuvées"),
        ("MILESTONE", "Sur jalons livrés"),
    ]
    mode = forms.ChoiceField(choices=MODE_CHOICES, initial="FIXED")
    period_start = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        input_formats=["%Y-%m-%d"],
        help_text="Pour le mode régie : début de la période facturée.",
    )
    period_end = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        input_formats=["%Y-%m-%d"],
        help_text="Pour le mode régie : fin de la période facturée.",
    )
    tax_rate = forms.DecimalField(
        max_digits=5, decimal_places=2, initial=Decimal("18.00"),
        min_value=0, max_value=100,
        help_text="Taux de TVA appliqué (%).",
    )
    currency = forms.CharField(max_length=10, initial="XOF")
    title = forms.CharField(max_length=200, required=False)
    notes = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}), required=False
    )

    def __init__(self, *args, **kwargs):
        from decimal import Decimal as _D  # noqa: F401
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            existing = widget.attrs.get("class", "")
            widget.attrs["class"] = (
                existing + " w-full rounded-2xl border border-[var(--border)] "
                "bg-[var(--bg3)] px-4 py-3 text-sm"
            ).strip()
