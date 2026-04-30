"""
Vues du workflow ProjectAIProposal.

Routes (toutes préfixées /ai-proposals/) :
- GET  /                                → liste des propositions du workspace
- GET  /<pk>/                           → cockpit prévisualisation
- POST /<pk>/regenerate/                → régénérer la proposition
- POST /<pk>/items/<item_pk>/validate/  → valide un item
- POST /<pk>/items/<item_pk>/reject/    → rejette un item
- GET/POST /<pk>/items/<item_pk>/edit/  → modifie un item (formulaire)
- POST /<pk>/validate-all/              → valide tous les items pending
- POST /<pk>/reject-all/                → rejette toute la proposition
- POST /<pk>/apply/                     → applique la proposition validée
- GET  /projects/<project_pk>/ai-proposals/ → historique côté projet
"""

from __future__ import annotations

import logging
from collections import defaultdict
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView, UpdateView

from project import models as dm
from project.forms_ai_proposal import (
    ProjectAIProposalItemEditForm,
    ProjectAIProposalRegenerateForm,
)
from project.services.ai.services.proposal_apply import ProposalApplyService
from project.services.ai.services.project_structure import (
    ProjectAIStructureService,
)

logger = logging.getLogger(__name__)


class AIProposalAccessMixin(LoginRequiredMixin):
    """Vérifie l'accès au workspace."""

    def get_proposal(self, pk):
        return get_object_or_404(
            dm.ProjectAIProposal.objects
            .select_related("project", "project__workspace", "triggered_by", "validated_by"),
            pk=pk,
        )


# =========================================================================
# Liste / historique
# =========================================================================
class ProjectAIProposalListView(LoginRequiredMixin, ListView):
    model = dm.ProjectAIProposal
    template_name = "project/ai_proposal/list.html"
    context_object_name = "proposals"
    paginate_by = 25

    def get_queryset(self):
        qs = (
            dm.ProjectAIProposal.objects
            .select_related("project", "workspace", "triggered_by")
            .order_by("-created_at")
        )
        project_id = self.request.GET.get("project")
        status = self.request.GET.get("status")
        if project_id:
            qs = qs.filter(project_id=project_id)
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = dm.ProjectAIProposal.Status.choices
        ctx["current_status"] = self.request.GET.get("status", "")
        ctx["current_project"] = self.request.GET.get("project", "")
        return ctx


# =========================================================================
# Cockpit (prévisualisation)
# =========================================================================
class ProjectAIProposalDetailView(AIProposalAccessMixin, DetailView):
    model = dm.ProjectAIProposal
    template_name = "project/ai_proposal/preview.html"
    context_object_name = "proposal"
    pk_url_kwarg = "pk"

    def get_queryset(self):
        return (
            dm.ProjectAIProposal.objects
            .select_related("project", "workspace", "triggered_by", "validated_by")
            .prefetch_related("items", "logs")
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        proposal = self.object

        items_by_kind = defaultdict(list)
        for item in proposal.items.all().order_by("order_index"):
            items_by_kind[item.kind].append(item)

        ctx["items_by_kind"] = dict(items_by_kind)
        ctx["task_items"] = items_by_kind.get(dm.ProjectAIProposalItem.Kind.TASK, [])
        ctx["sprint_items"] = items_by_kind.get(dm.ProjectAIProposalItem.Kind.SPRINT, [])
        ctx["milestone_items"] = items_by_kind.get(dm.ProjectAIProposalItem.Kind.MILESTONE, [])
        ctx["roadmap_items"] = items_by_kind.get(dm.ProjectAIProposalItem.Kind.ROADMAP_ITEM, [])
        ctx["backlog_items"] = items_by_kind.get(dm.ProjectAIProposalItem.Kind.BACKLOG, [])
        ctx["dependency_items"] = items_by_kind.get(dm.ProjectAIProposalItem.Kind.DEPENDENCY, [])
        ctx["assignment_items"] = items_by_kind.get(dm.ProjectAIProposalItem.Kind.ASSIGNMENT, [])
        ctx["recommendations"] = proposal.recommendations or []

        # Indicateurs de cohérence
        ctx["coherence"] = self._build_coherence(proposal, ctx["task_items"])
        ctx["status_class"] = {
            dm.ProjectAIProposal.Status.PENDING: "b-cyan",
            dm.ProjectAIProposal.Status.GENERATING: "b-cyan",
            dm.ProjectAIProposal.Status.READY: "b-amber",
            dm.ProjectAIProposal.Status.PARTIALLY_VALIDATED: "b-amber",
            dm.ProjectAIProposal.Status.VALIDATED: "b-green",
            dm.ProjectAIProposal.Status.APPLIED: "b-green",
            dm.ProjectAIProposal.Status.REJECTED: "b-red",
            dm.ProjectAIProposal.Status.FAILED: "b-red",
        }.get(proposal.status, "b-cyan")
        return ctx

    def _build_coherence(self, proposal, task_items):
        # Charge par membre
        load_by_user = defaultdict(lambda: Decimal("0"))
        unassigned = 0
        for t in task_items:
            if t.recommended_assignee_id:
                load_by_user[t.recommended_assignee] += Decimal(t.estimate_hours or 0)
            else:
                unassigned += 1

        load_rows = sorted(
            (
                {
                    "user": user,
                    "label": str(user),
                    "hours": float(hours),
                }
                for user, hours in load_by_user.items()
            ),
            key=lambda r: -r["hours"],
        )

        # Dépendances non résolues : ref qui n'existe pas
        all_refs = {item.local_ref for item in proposal.items.all() if item.local_ref}
        broken_deps = []
        for t in task_items:
            for ref in (t.depends_on_refs or []):
                if ref and ref not in all_refs:
                    broken_deps.append({"task": t.local_ref, "missing": ref})

        return {
            "load_rows": load_rows,
            "unassigned_tasks": unassigned,
            "broken_dependencies": broken_deps,
            "total_hours": sum(r["hours"] for r in load_rows),
        }


# =========================================================================
# Item-level actions
# =========================================================================
class ProjectAIProposalItemValidateView(AIProposalAccessMixin, View):
    def post(self, request, pk, item_pk):
        proposal = self.get_proposal(pk)
        item = get_object_or_404(proposal.items.all(), pk=item_pk)
        item.item_status = dm.ProjectAIProposalItem.ItemStatus.VALIDATED
        item.edited_by = request.user
        item.edited_at = timezone.now()
        item.save(update_fields=["item_status", "edited_by", "edited_at", "updated_at"])

        dm.ProjectAIProposalLog.objects.create(
            proposal=proposal,
            action=dm.ProjectAIProposalLog.Action.ITEM_VALIDATED,
            actor=request.user,
            message=f"Item {item.local_ref or item.pk} validé.",
        )
        self._update_proposal_status(proposal)
        if request.headers.get("HX-Request"):
            return JsonResponse({"ok": True, "item_status": item.item_status})
        messages.success(request, "Élément validé.")
        return redirect("ai_proposal_detail", pk=proposal.pk)

    @staticmethod
    def _update_proposal_status(proposal):
        items = proposal.items.all()
        statuses = set(items.values_list("item_status", flat=True))
        if statuses == {dm.ProjectAIProposalItem.ItemStatus.VALIDATED}:
            proposal.status = dm.ProjectAIProposal.Status.VALIDATED
        elif dm.ProjectAIProposalItem.ItemStatus.VALIDATED in statuses:
            proposal.status = dm.ProjectAIProposal.Status.PARTIALLY_VALIDATED
        proposal.save(update_fields=["status", "updated_at"])


class ProjectAIProposalItemRejectView(AIProposalAccessMixin, View):
    def post(self, request, pk, item_pk):
        proposal = self.get_proposal(pk)
        item = get_object_or_404(proposal.items.all(), pk=item_pk)
        item.item_status = dm.ProjectAIProposalItem.ItemStatus.REJECTED
        item.edited_by = request.user
        item.edited_at = timezone.now()
        item.save(update_fields=["item_status", "edited_by", "edited_at", "updated_at"])

        dm.ProjectAIProposalLog.objects.create(
            proposal=proposal,
            action=dm.ProjectAIProposalLog.Action.ITEM_REJECTED,
            actor=request.user,
            message=f"Item {item.local_ref or item.pk} rejeté.",
        )
        if request.headers.get("HX-Request"):
            return JsonResponse({"ok": True, "item_status": item.item_status})
        messages.warning(request, "Élément rejeté.")
        return redirect("ai_proposal_detail", pk=proposal.pk)


class ProjectAIProposalItemEditView(AIProposalAccessMixin, UpdateView):
    model = dm.ProjectAIProposalItem
    form_class = ProjectAIProposalItemEditForm
    template_name = "project/ai_proposal/item_form.html"
    pk_url_kwarg = "item_pk"

    def get_queryset(self):
        return dm.ProjectAIProposalItem.objects.select_related(
            "proposal", "proposal__project", "recommended_assignee"
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["proposal"] = self.object.proposal
        return ctx

    def form_valid(self, form):
        item = form.save(commit=False)
        item.item_status = dm.ProjectAIProposalItem.ItemStatus.EDITED
        item.edited_by = self.request.user
        item.edited_at = timezone.now()
        item.save()

        dm.ProjectAIProposalLog.objects.create(
            proposal=item.proposal,
            action=dm.ProjectAIProposalLog.Action.ITEM_EDITED,
            actor=self.request.user,
            message=f"Item {item.local_ref or item.pk} modifié.",
        )
        messages.success(self.request, "Élément mis à jour.")
        return redirect("ai_proposal_detail", pk=item.proposal_id)


# =========================================================================
# Proposal-level actions
# =========================================================================
class ProjectAIProposalValidateAllView(AIProposalAccessMixin, View):
    def post(self, request, pk):
        proposal = self.get_proposal(pk)
        proposal.items.filter(
            item_status__in=[
                dm.ProjectAIProposalItem.ItemStatus.PROPOSED,
                dm.ProjectAIProposalItem.ItemStatus.EDITED,
            ]
        ).update(
            item_status=dm.ProjectAIProposalItem.ItemStatus.VALIDATED,
            edited_by=request.user,
            edited_at=timezone.now(),
        )
        proposal.status = dm.ProjectAIProposal.Status.VALIDATED
        proposal.validated_by = request.user
        proposal.validated_at = timezone.now()
        proposal.save(update_fields=["status", "validated_by", "validated_at", "updated_at"])

        dm.ProjectAIProposalLog.objects.create(
            proposal=proposal,
            action=dm.ProjectAIProposalLog.Action.VALIDATED,
            actor=request.user,
            message="Tous les items validés en lot.",
        )
        messages.success(request, "Proposition validée. Vous pouvez l'appliquer au projet.")
        return redirect("ai_proposal_detail", pk=proposal.pk)


class ProjectAIProposalRejectView(AIProposalAccessMixin, View):
    def post(self, request, pk):
        proposal = self.get_proposal(pk)
        proposal.status = dm.ProjectAIProposal.Status.REJECTED
        proposal.rejected_at = timezone.now()
        proposal.save(update_fields=["status", "rejected_at", "updated_at"])
        proposal.items.update(
            item_status=dm.ProjectAIProposalItem.ItemStatus.REJECTED,
        )
        dm.ProjectAIProposalLog.objects.create(
            proposal=proposal,
            action=dm.ProjectAIProposalLog.Action.REJECTED,
            actor=request.user,
            message="Proposition entièrement rejetée.",
        )
        messages.warning(request, "Proposition rejetée.")
        return redirect("ai_proposal_list")


class ProjectAIProposalApplyView(AIProposalAccessMixin, View):
    def post(self, request, pk):
        proposal = self.get_proposal(pk)
        try:
            counts = ProposalApplyService.apply(proposal, actor=request.user)
            messages.success(
                request,
                "Proposition appliquée : "
                + ", ".join(f"{v} {k}" for k, v in counts.items() if v),
            )
            return redirect("project_detail", pk=proposal.project_id)
        except Exception as exc:
            logger.exception("apply proposal failed")
            messages.error(request, f"Application impossible : {exc}")
            return redirect("ai_proposal_detail", pk=proposal.pk)


class ProjectAIProposalRegenerateView(AIProposalAccessMixin, View):
    def get(self, request, pk):
        proposal = self.get_proposal(pk)
        return render(
            request,
            "project/ai_proposal/regenerate_form.html",
            {"proposal": proposal, "form": ProjectAIProposalRegenerateForm()},
        )

    def post(self, request, pk):
        old_proposal = self.get_proposal(pk)
        form = ProjectAIProposalRegenerateForm(request.POST)
        use_ai = True
        if form.is_valid():
            use_ai = form.cleaned_data.get("use_ai", True)

        result = ProjectAIStructureService.generate_for_project(
            project=old_proposal.project,
            triggered_by=request.user,
            use_ai=use_ai,
        )
        messages.success(
            request,
            f"Nouvelle proposition générée ({result.items_created} items, {result.used_provider}).",
        )
        return redirect("ai_proposal_detail", pk=result.proposal.pk)


class ProjectAIProposalsForProjectView(LoginRequiredMixin, ListView):
    """Historique des propositions IA d'un projet donné."""

    template_name = "project/ai_proposal/project_history.html"
    context_object_name = "proposals"

    def get_queryset(self):
        return (
            dm.ProjectAIProposal.objects
            .filter(project_id=self.kwargs["project_pk"])
            .select_related("triggered_by", "validated_by")
            .order_by("-created_at")
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["project"] = get_object_or_404(dm.Project, pk=self.kwargs["project_pk"])
        return ctx


class ProjectAIProposalTriggerView(LoginRequiredMixin, View):
    """Déclenchement manuel d'une proposition IA pour un projet existant."""

    def post(self, request, project_pk):
        project = get_object_or_404(dm.Project, pk=project_pk)
        result = ProjectAIStructureService.generate_for_project(
            project=project,
            triggered_by=request.user,
            use_ai=True,
        )
        messages.success(request, "Proposition IA générée.")
        return redirect("ai_proposal_detail", pk=result.proposal.pk)


# =========================================================================
# Endpoint AJAX : statut de la dernière proposition IA d'un projet
# Utilisé par le widget de progression dans la fiche projet.
# =========================================================================
class ProjectAIProposalStatusView(LoginRequiredMixin, View):
    """GET /projects/<project_pk>/ai-proposals/status/  → JSON statut + ETA."""

    # Étapes affichées à l'utilisateur (label + part du temps total)
    _STEPS = [
        (5, "Initialisation"),
        (15, "Lecture du contexte projet et des équipes"),
        (35, "Construction de la roadmap et des phases"),
        (55, "Découpage en jalons et sprints"),
        (75, "Génération du backlog et des tâches"),
        (90, "Affectation par rôle / profil"),
        (98, "Sauvegarde et indexation"),
    ]

    # Durée typique en secondes (estimation prudente)
    _TYPICAL_DURATION_S = 90

    def get(self, request, project_pk):
        from django.http import JsonResponse
        project = get_object_or_404(dm.Project, pk=project_pk)
        proposal = (
            dm.ProjectAIProposal.objects.filter(project=project)
            .order_by("-created_at").first()
        )
        if not proposal:
            return JsonResponse({
                "status": None,
                "label": "Aucune proposition",
                "progress": 0,
                "eta_seconds": 0,
                "step_label": "—",
            })

        status = proposal.status
        elapsed = (timezone.now() - proposal.created_at).total_seconds()

        # Calcule progress + step selon le statut
        if status in (dm.ProjectAIProposal.Status.READY,
                      dm.ProjectAIProposal.Status.VALIDATED,
                      dm.ProjectAIProposal.Status.APPLIED,
                      dm.ProjectAIProposal.Status.PARTIALLY_VALIDATED):
            progress = 100
            step = "Génération terminée"
            eta = 0
        elif status == dm.ProjectAIProposal.Status.FAILED:
            progress = 0
            step = "Échec — vous pouvez relancer"
            eta = 0
        elif status == dm.ProjectAIProposal.Status.REJECTED:
            progress = 100
            step = "Rejetée"
            eta = 0
        else:
            # En cours — interpolation linéaire avec courbe ralentie en fin
            ratio = min(1.0, elapsed / self._TYPICAL_DURATION_S)
            # Easing : montée rapide puis lente sur les dernières 10%
            progress = int((ratio ** 0.7) * 92)
            progress = max(2, min(99, progress))
            # Choisit le step courant
            step = self._STEPS[0][1]
            for thr, lbl in self._STEPS:
                if progress >= thr:
                    step = lbl
            eta = max(0, int(self._TYPICAL_DURATION_S - elapsed))

        return JsonResponse({
            "proposal_id": proposal.pk,
            "status": status,
            "status_label": dict(dm.ProjectAIProposal.Status.choices).get(status, status),
            "progress": progress,
            "step_label": step,
            "eta_seconds": eta,
            "items_created": getattr(proposal, "items_created", 0),
            "used_provider": proposal.used_provider or "",
            "tokens_used": proposal.tokens_used or 0,
            "is_terminal": progress in (0, 100),
        })
