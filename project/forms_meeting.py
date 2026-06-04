"""Formulaires module Réunions DevFlow."""

from __future__ import annotations

from django import forms

from project import models as dm
from project.forms_budget import StyledModelForm


class ProjectMeetingForm(StyledModelForm):
    class Meta:
        model = dm.ProjectMeeting
        fields = [
            "project",
            "projects",  # PR-MEET-3 : revue multi-projets (comité)
            "sprint",
            "title",
            "meeting_type",
            "status",
            "scheduled_at",
            "duration_minutes",
            "location",
            "meeting_link",
            "organizer",
            "internal_participants",
            "external_participants",
            "agenda",
            "notes",
            "decisions",
            "blockers",
            "next_steps",
        ]
        widgets = {
            "title": forms.TextInput(),
            "scheduled_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "duration_minutes": forms.NumberInput(attrs={"min": 5, "step": 5}),
            "location": forms.TextInput(),
            "meeting_link": forms.URLInput(),
            "internal_participants": forms.SelectMultiple(attrs={"size": 6}),
            "projects": forms.SelectMultiple(attrs={"size": 6}),
            "external_participants": forms.Textarea(attrs={"rows": 3}),
            "agenda": forms.Textarea(attrs={"rows": 4}),
            "notes": forms.Textarea(attrs={"rows": 8}),
            "decisions": forms.Textarea(attrs={"rows": 4}),
            "blockers": forms.Textarea(attrs={"rows": 3}),
            "next_steps": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        # Compat avec DevflowCreateView qui passe ces kwargs
        self.current_workspace = kwargs.pop("current_workspace", None)
        self.allowed_workspaces = kwargs.pop("allowed_workspaces", None)
        kwargs.pop("request", None)
        super().__init__(*args, **kwargs)

        self.fields["scheduled_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        if self.instance and self.instance.pk and self.instance.scheduled_at:
            self.initial["scheduled_at"] = self.instance.scheduled_at.strftime("%Y-%m-%dT%H:%M")

        # Filtrage par workspace
        ws = self.current_workspace
        if ws:
            self.fields["project"].queryset = self.fields["project"].queryset.filter(
                workspace=ws, is_archived=False,
            ).order_by("name")
            if "projects" in self.fields:
                self.fields["projects"].queryset = dm.Project.objects.filter(
                    workspace=ws, is_archived=False,
                ).order_by("name")
            self.fields["sprint"].queryset = dm.Sprint.objects.filter(
                workspace=ws, is_archived=False,
            ).order_by("-start_date")

        # PR-MEET-3 : project devient optionnel (réunion comité multi-projets)
        if "project" in self.fields:
            self.fields["project"].required = False
            self.fields["project"].empty_label = "— Aucun projet principal (comité) —"
            self.fields["project"].help_text = (
                "Optionnel. Laissez vide pour une réunion qui passe en "
                "revue plusieurs projets (cf. champ ci-dessous)."
            )

        # Champs facultatifs
        for f in ("sprint", "projects", "location", "meeting_link",
                  "external_participants", "agenda", "notes",
                  "decisions", "blockers", "next_steps"):
            if f in self.fields:
                self.fields[f].required = False

    def clean(self):
        data = super().clean()
        project = data.get("project")
        sprint = data.get("sprint")
        if project and sprint and sprint.project_id != project.pk:
            self.add_error("sprint", "Le sprint sélectionné n'appartient pas au projet choisi.")
        return data


class MeetingSeriesForm(StyledModelForm):
    """Création / édition d'une série récurrente de réunions."""

    class Meta:
        model = dm.MeetingSeries
        fields = [
            "name", "description", "meeting_type",
            "recurrence", "weekday", "month_day",
            "time_local", "duration_minutes",
            "start_date", "end_date", "is_active",
            "location", "meeting_link",
            "organizer",
            "default_participants",
            "default_projects",
            "default_agenda",
        ]
        widgets = {
            "name": forms.TextInput(),
            "description": forms.Textarea(attrs={"rows": 2}),
            "time_local": forms.TimeInput(attrs={"type": "time"}),
            "start_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "end_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "default_agenda": forms.Textarea(attrs={"rows": 4}),
            "default_participants": forms.SelectMultiple(attrs={"size": 6}),
            "default_projects": forms.SelectMultiple(attrs={"size": 6}),
            "weekday": forms.Select(choices=[
                (0, "Lundi"), (1, "Mardi"), (2, "Mercredi"), (3, "Jeudi"),
                (4, "Vendredi"), (5, "Samedi"), (6, "Dimanche"),
            ]),
        }

    def __init__(self, *args, **kwargs):
        self.current_workspace = kwargs.pop("current_workspace", None)
        self.allowed_workspaces = kwargs.pop("allowed_workspaces", None)
        kwargs.pop("request", None)
        super().__init__(*args, **kwargs)

        for f in ("start_date", "end_date"):
            if f in self.fields:
                self.fields[f].input_formats = ["%Y-%m-%d"]

        ws = self.current_workspace
        if ws:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            users_qs = (
                User.objects.filter(
                    devflow_memberships__workspace=ws, is_active=True,
                ).distinct().order_by("last_name", "first_name", "username")
            )
            if "default_participants" in self.fields:
                self.fields["default_participants"].queryset = users_qs
            if "organizer" in self.fields:
                self.fields["organizer"].queryset = users_qs
                self.fields["organizer"].required = False
            if "default_projects" in self.fields:
                self.fields["default_projects"].queryset = dm.Project.objects.filter(
                    workspace=ws, is_archived=False,
                ).order_by("name")

        for f in ("description", "end_date", "weekday", "month_day",
                  "location", "meeting_link", "default_agenda",
                  "organizer", "default_participants", "default_projects"):
            if f in self.fields:
                self.fields[f].required = False

    def clean(self):
        data = super().clean()
        rec = data.get("recurrence")
        wd = data.get("weekday")
        md = data.get("month_day")
        sd = data.get("start_date")
        ed = data.get("end_date")
        tl = data.get("time_local")

        if rec in (dm.MeetingSeries.Recurrence.WEEKLY,
                   dm.MeetingSeries.Recurrence.BIWEEKLY):
            if wd is None:
                self.add_error("weekday", "Choisissez un jour de la semaine.")
        if rec == dm.MeetingSeries.Recurrence.MONTHLY and md is None:
            self.add_error(
                "month_day",
                "Indiquez le jour du mois (0 = dernier jour, 1-31 sinon).",
            )
        if not tl:
            self.add_error("time_local", "L'heure est requise.")
        if not sd:
            self.add_error("start_date", "La date de début est requise.")
        if sd and ed and ed < sd:
            self.add_error("end_date", "La date de fin doit être après le début.")
        return data


class MeetingProjectReviewForm(StyledModelForm):
    """Une revue projet à l'intérieur d'une réunion (utilisée en formset)."""

    class Meta:
        model = dm.MeetingProjectReview
        fields = [
            "project", "position",
            "status_snapshot", "progress_pct",
            "achievements", "blockers",
            "decisions", "actions_to_take",
            "next_milestone", "next_milestone_date",
            "presented_by",
        ]
        widgets = {
            "achievements": forms.Textarea(attrs={"rows": 2}),
            "blockers": forms.Textarea(attrs={"rows": 2}),
            "decisions": forms.Textarea(attrs={"rows": 2}),
            "actions_to_take": forms.Textarea(attrs={"rows": 3}),
            "next_milestone_date": forms.DateInput(
                format="%Y-%m-%d", attrs={"type": "date"},
            ),
            "progress_pct": forms.NumberInput(attrs={"min": 0, "max": 100}),
            "position": forms.NumberInput(attrs={"min": 0}),
        }

    def __init__(self, *args, **kwargs):
        self.current_workspace = kwargs.pop("current_workspace", None)
        kwargs.pop("allowed_workspaces", None)
        kwargs.pop("request", None)
        super().__init__(*args, **kwargs)

        ws = self.current_workspace
        if ws:
            if "project" in self.fields:
                self.fields["project"].queryset = dm.Project.objects.filter(
                    workspace=ws, is_archived=False,
                ).order_by("name")
            if "presented_by" in self.fields:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                self.fields["presented_by"].queryset = (
                    User.objects.filter(
                        devflow_memberships__workspace=ws, is_active=True,
                    ).distinct().order_by("last_name", "first_name", "username")
                )
                self.fields["presented_by"].required = False

        for f in ("achievements", "blockers", "decisions", "actions_to_take",
                  "next_milestone", "next_milestone_date", "presented_by",
                  "position"):
            if f in self.fields:
                self.fields[f].required = False


def build_project_review_formset(current_workspace, extra=0):
    """Construit l'inline formset des revues projet, scopé au workspace."""
    class _ScopedForm(MeetingProjectReviewForm):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("current_workspace", current_workspace)
            super().__init__(*args, **kwargs)

    return forms.inlineformset_factory(
        dm.ProjectMeeting,
        dm.MeetingProjectReview,
        form=_ScopedForm,
        extra=extra,
        can_delete=True,
    )


class MeetingActionItemForm(StyledModelForm):
    class Meta:
        model = dm.MeetingActionItem
        fields = ["title", "description", "owner", "due_date", "priority", "status"]
        widgets = {
            "title": forms.TextInput(),
            "description": forms.Textarea(attrs={"rows": 3}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        kwargs.pop("current_workspace", None)
        kwargs.pop("allowed_workspaces", None)
        kwargs.pop("request", None)
        super().__init__(*args, **kwargs)
        for name in ("description", "owner", "due_date"):
            if name in self.fields:
                self.fields[name].required = False
