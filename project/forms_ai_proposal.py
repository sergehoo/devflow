"""Formulaires pour le workflow ProjectAIProposal."""

from __future__ import annotations

from django import forms

from project import models as dm
from project.forms_budget import StyledModelForm


class ProjectAIProposalItemEditForm(StyledModelForm):
    """Formulaire d'édition inline d'un item de proposition IA."""

    class Meta:
        model = dm.ProjectAIProposalItem
        fields = [
            "title",
            "description",
            "priority",
            "complexity",
            "estimate_hours",
            "recommended_profile",
            "recommended_assignee",
            "sprint_ref",
            "milestone_ref",
            "start_date",
            "end_date",
            "velocity_target",
        ]
        widgets = {
            "title": forms.TextInput(),
            "description": forms.Textarea(attrs={"rows": 3}),
            "priority": forms.Select(choices=[
                ("", "—"),
                ("LOW", "Low"),
                ("MEDIUM", "Medium"),
                ("HIGH", "High"),
                ("CRITICAL", "Critique"),
            ]),
            "complexity": forms.Select(choices=[
                ("", "—"),
                ("LOW", "Faible"),
                ("MEDIUM", "Moyenne"),
                ("HIGH", "Élevée"),
            ]),
            "estimate_hours": forms.NumberInput(attrs={"step": "0.5", "min": "0"}),
            "recommended_profile": forms.TextInput(),
            "sprint_ref": forms.TextInput(),
            "milestone_ref": forms.TextInput(),
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "velocity_target": forms.NumberInput(attrs={"min": "0"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Limite les assignees aux membres du projet pour la cohérence
        instance = kwargs.get("instance")
        if instance and instance.proposal_id:
            project = instance.proposal.project
            user_ids = list(
                project.members.values_list("user_id", flat=True)
            )
            self.fields["recommended_assignee"].queryset = (
                self.fields["recommended_assignee"]
                .queryset
                .filter(pk__in=user_ids)
            )
        # Tous les champs ne sont pas pertinents pour tous les kinds — c'est OK,
        # le template n'affiche que ceux utiles.

        for name, field in self.fields.items():
            field.required = False


class ProjectAIProposalRegenerateForm(forms.Form):
    """Formulaire minimal pour relancer une génération IA."""

    use_ai = forms.BooleanField(
        required=False,
        initial=True,
        label="Utiliser l'IA (sinon heuristique)",
    )
