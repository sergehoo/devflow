"""
Vues pour la création d'un projet **complet** par IA (DevFlow Genesis).

L'utilisateur fournit juste un nom + description ; l'IA crée le projet,
sa roadmap, ses sprints, milestones, backlog, tâches, dépendances et
affectations. Le tout en un seul écran, en moins de 30s.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from project import models as dm
from project.forms_budget import StyledModelForm
from project.services.ai.services.chat import DevFlowContextBuilder
from project.services.ai.services.project_genesis import ProjectGenesisService

logger = logging.getLogger(__name__)


# =========================================================================
# Formulaire minimaliste
# =========================================================================
class ProjectGenesisForm(forms.Form):
    name = forms.CharField(
        label="Nom du projet",
        max_length=160,
        widget=forms.TextInput(attrs={
            "placeholder": "ex: Plateforme e-commerce v3",
            "class": "w-full rounded-[14px] border border-devborder bg-devbg3 px-4 py-3 text-sm text-devtext1",
            "autofocus": True,
        }),
    )
    description = forms.CharField(
        label="Décrivez le projet (objectif, périmètre, contraintes)",
        widget=forms.Textarea(attrs={
            "placeholder": "Refonte du site marchand avec gestion paiement, back-office et application mobile...",
            "rows": 5,
            "class": "w-full rounded-[14px] border border-devborder bg-devbg3 px-4 py-3 text-sm text-devtext1",
        }),
    )
    workspace = forms.ModelChoiceField(
        label="Workspace",
        queryset=dm.Workspace.objects.filter(is_archived=False),
        widget=forms.Select(attrs={
            "class": "w-full rounded-[14px] border border-devborder bg-devbg3 px-4 py-3 text-sm text-devtext1",
        }),
    )
    priority = forms.ChoiceField(
        label="Priorité",
        choices=dm.Project.Priority.choices,
        initial=dm.Project.Priority.MEDIUM,
        widget=forms.Select(attrs={
            "class": "w-full rounded-[14px] border border-devborder bg-devbg3 px-4 py-3 text-sm text-devtext1",
        }),
    )
    target_date = forms.DateField(
        label="Date cible (facultatif)",
        required=False,
        widget=forms.DateInput(attrs={
            "type": "date",
            "class": "w-full rounded-[14px] border border-devborder bg-devbg3 px-4 py-3 text-sm text-devtext1",
        }),
    )
    auto_apply = forms.BooleanField(
        label="Appliquer automatiquement la structure générée",
        required=False,
        initial=True,
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user and user.is_authenticated:
            owned = dm.Workspace.objects.filter(owner=user, is_archived=False)
            membered = dm.Workspace.objects.filter(
                memberships__user=user, is_archived=False
            ).distinct()
            self.fields["workspace"].queryset = (owned | membered).distinct().order_by("name")


# =========================================================================
# Vues
# =========================================================================
class ProjectGenesisView(LoginRequiredMixin, View):
    """
    GET  : affiche le formulaire (nom, description, workspace, priorité)
    POST : déclenche la génération IA + création + redirige vers le cockpit
    """

    template_name = "project/ai_genesis/form.html"

    def get(self, request, *args, **kwargs):
        form = ProjectGenesisForm(user=request.user)
        return render(request, self.template_name, {"form": form})

    def post(self, request, *args, **kwargs):
        form = ProjectGenesisForm(request.POST, user=request.user)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        try:
            result = ProjectGenesisService.create_project_from_brief(
                workspace=form.cleaned_data["workspace"],
                name=form.cleaned_data["name"],
                description=form.cleaned_data["description"],
                owner=request.user,
                priority=form.cleaned_data["priority"],
                target_date=form.cleaned_data.get("target_date"),
                use_ai=True,
                auto_apply=form.cleaned_data.get("auto_apply", True),
            )
        except ValueError as exc:
            form.add_error(None, str(exc))
            return render(request, self.template_name, {"form": form})
        except Exception as exc:
            logger.exception("Genesis failed")
            messages.error(request, f"Erreur Genesis IA : {exc}")
            return render(request, self.template_name, {"form": form})

        applied = result.proposal.status == dm.ProjectAIProposal.Status.APPLIED
        msg = (
            f"✨ Projet « {result.project.name} » créé par DevFlow AI ({result.used_provider}). "
            f"{result.counts.get('tasks', 0)} tâche(s), "
            f"{result.counts.get('sprints', 0)} sprint(s), "
            f"{result.counts.get('milestones', 0)} milestone(s) générés."
        ) if applied else (
            f"Projet créé. Une proposition IA est prête à validation."
        )
        messages.success(request, msg)

        if applied:
            return redirect("project_detail", pk=result.project.pk)
        return redirect("ai_proposal_detail", pk=result.proposal.pk)


class ProjectGenesisAPIView(LoginRequiredMixin, View):
    """
    Endpoint JSON utilisable depuis le panneau IA :
    POST {"name": "...", "description": "...", "workspace_id": int}
    """

    def post(self, request, *args, **kwargs):
        try:
            payload = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

        name = (payload.get("name") or "").strip()
        description = (payload.get("description") or "").strip()
        workspace_id = payload.get("workspace_id")

        if not name or not description:
            return JsonResponse(
                {"ok": False, "error": "name et description sont obligatoires"},
                status=400,
            )

        workspace = None
        if workspace_id:
            workspace = dm.Workspace.objects.filter(pk=workspace_id).first()
        if not workspace:
            workspace = DevFlowContextBuilder._infer_workspace(request.user)
        if not workspace:
            return JsonResponse({"ok": False, "error": "aucun workspace disponible"}, status=400)

        target_date_raw = payload.get("target_date")
        target_date = None
        if target_date_raw:
            try:
                target_date = datetime.fromisoformat(str(target_date_raw)).date()
            except Exception:
                target_date = None

        try:
            result = ProjectGenesisService.create_project_from_brief(
                workspace=workspace,
                name=name,
                description=description,
                owner=request.user,
                priority=payload.get("priority") or dm.Project.Priority.MEDIUM,
                target_date=target_date,
                use_ai=bool(payload.get("use_ai", True)),
                auto_apply=bool(payload.get("auto_apply", True)),
            )
        except ValueError as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:
            logger.exception("Genesis API failed")
            return JsonResponse({"ok": False, "error": str(exc)}, status=500)

        return JsonResponse({
            "ok": True,
            "project": {
                "id": result.project.pk,
                "name": result.project.name,
                "url": reverse("project_detail", kwargs={"pk": result.project.pk}),
            },
            "proposal": {
                "id": result.proposal.pk,
                "status": result.proposal.status,
                "url": reverse("ai_proposal_detail", kwargs={"pk": result.proposal.pk}),
            },
            "used_provider": result.used_provider,
            "counts": result.counts,
        })
