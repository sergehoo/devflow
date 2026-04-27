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
            "internal_participants": forms.SelectMultiple(),
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
            self.fields["sprint"].queryset = dm.Sprint.objects.filter(
                workspace=ws, is_archived=False,
            ).order_by("-start_date")

        # Champs facultatifs
        for f in ("sprint", "location", "meeting_link", "external_participants",
                  "agenda", "notes", "decisions", "blockers", "next_steps"):
            if f in self.fields:
                self.fields[f].required = False

    def clean(self):
        data = super().clean()
        project = data.get("project")
        sprint = data.get("sprint")
        if project and sprint and sprint.project_id != project.pk:
            self.add_error("sprint", "Le sprint sélectionné n'appartient pas au projet choisi.")
        return data


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
