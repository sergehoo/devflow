"""Formulaires membres / employés (onboarding + hiérarchie)."""

from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from project import models as dm
from project.forms import (
    BASE_DATE_CLASS,
    BASE_INPUT_CLASS,
    BASE_SELECT_CLASS,
    _user_choice_label,
)
from project.services.team_onboarding import workspace_users

User = get_user_model()


def _style(form):
    for name, field in form.fields.items():
        widget = field.widget
        if isinstance(widget, forms.RadioSelect):
            continue
        if isinstance(widget, forms.Select):
            css = BASE_SELECT_CLASS
        elif isinstance(widget, forms.DateInput):
            css = BASE_DATE_CLASS
        else:
            css = BASE_INPUT_CLASS
        widget.attrs["class"] = f"{widget.attrs.get('class', '')} {css}".strip()
        widget.attrs.setdefault("autocomplete", "off")


def would_create_cycle(employee, manager, workspace) -> bool:
    """True si ``manager`` est (in)directement subordonné de ``employee``."""
    profile = dm.UserProfile.objects.filter(user=manager, workspace=workspace).first()
    seen = set()
    while profile is not None and profile.pk not in seen:
        if profile.user_id == employee.pk:
            return True
        seen.add(profile.pk)
        profile = profile.manager
    return False


class EmployeeOnboardingForm(forms.Form):
    MODE_EXISTING = "existing"
    MODE_NEW = "new"

    mode = forms.ChoiceField(
        label="Type d'ajout",
        choices=[
            (MODE_EXISTING, "Utilisateur existant du workspace"),
            (MODE_NEW, "Nouvel employé (invitation par email)"),
        ],
        initial=MODE_EXISTING,
        widget=forms.RadioSelect,
    )
    user = forms.ModelChoiceField(label="Utilisateur", queryset=User.objects.none(), required=False)
    first_name = forms.CharField(label="Prénom", max_length=150, required=False)
    last_name = forms.CharField(label="Nom", max_length=150, required=False)
    email = forms.EmailField(label="Email", required=False)
    job_title = forms.CharField(label="Fonction", max_length=120, required=False)
    team = forms.ModelChoiceField(label="Équipe", queryset=dm.Team.objects.none(), required=False)
    role = forms.ChoiceField(
        label="Rôle", choices=dm.TeamMembership.Role.choices,
        initial=dm.TeamMembership.Role.DEVELOPER,
    )
    weekly_capacity = forms.DecimalField(
        label="Capacité hebdomadaire (h)", min_value=Decimal("1"), max_value=Decimal("80"),
        decimal_places=2, initial=Decimal("40"),
    )
    arrival_date = forms.DateField(
        label="Date d'arrivée", initial=timezone.localdate,
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
    )
    manager = forms.ModelChoiceField(
        label="Manager direct (N+1)", queryset=User.objects.none(), required=False,
    )

    def __init__(self, *args, workspace=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = workspace
        users = workspace_users(workspace)
        self.fields["user"].queryset = users.filter(is_active=True)
        self.fields["manager"].queryset = users.filter(is_active=True, profile__workspace=workspace)
        self.fields["user"].label_from_instance = _user_choice_label
        self.fields["manager"].label_from_instance = _user_choice_label
        self.fields["team"].queryset = (
            dm.Team.objects.filter(workspace=workspace, is_archived=False).order_by("name")
            if workspace else dm.Team.objects.none()
        )
        _style(self)

    def clean_email(self):
        return (self.cleaned_data.get("email") or "").strip().lower()

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get("mode")
        user = cleaned.get("user")
        manager = cleaned.get("manager")
        team = cleaned.get("team")

        if mode == self.MODE_EXISTING:
            if not user:
                self.add_error("user", "Sélectionnez un utilisateur du workspace.")
                return cleaned
            if manager and manager.pk == user.pk:
                self.add_error("manager", "Un collaborateur ne peut pas être son propre manager.")
            elif manager and would_create_cycle(user, manager, self.workspace):
                self.add_error("manager", "Cette affectation créerait un cycle hiérarchique.")
            profile = dm.UserProfile.objects.filter(user=user).first()
            if manager and profile and profile.workspace_id != self.workspace.pk:
                self.add_error("manager", "Le profil de cet utilisateur est rattaché à un autre workspace.")
            if dm.TeamMembership.objects.filter(workspace=self.workspace, user=user, team=team).exists():
                self.add_error(
                    "team",
                    f"Cet utilisateur est déjà membre {'de cette équipe' if team else 'du workspace (sans équipe)'}.",
                )
        elif mode == self.MODE_NEW:
            for name in ("first_name", "last_name", "email"):
                if not cleaned.get(name):
                    self.add_error(name, "Champ obligatoire pour un nouvel employé.")
            email = cleaned.get("email")
            if email and User.objects.filter(email__iexact=email).exists():
                self.add_error(
                    "email",
                    "Un compte existe déjà avec cet email. Choisissez « Utilisateur existant » "
                    "ou utilisez une autre adresse.",
                )
        return cleaned


class ManagerField(forms.ModelChoiceField):
    """Champ N+1 réutilisable dans le formulaire d'édition d'appartenance."""

    def __init__(self, workspace, **kwargs):
        qs = workspace_users(workspace).filter(is_active=True, profile__workspace=workspace)
        super().__init__(queryset=qs, required=False, label="Manager direct (N+1)", **kwargs)
        self.label_from_instance = _user_choice_label
        self.widget.attrs["class"] = BASE_SELECT_CLASS
