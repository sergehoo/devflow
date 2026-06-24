"""
DevFlow — Vues d'administration des méthodologies (PR20-PR21).

Permet à un admin workspace de créer / modifier une méthodologie
personnalisée (non-système). Les méthodologies SYSTÈME (Scrum, Kanban,
Waterfall) sont en lecture seule.

URLs :
  * /admin/methodologies/                       — liste
  * /admin/methodologies/create/                — créer
  * /admin/methodologies/<pk>/                  — détail / config sous-objets
  * /admin/methodologies/<pk>/update/           — éditer
  * /admin/methodologies/<pk>/delete/           — supprimer
  * /admin/methodologies/<pk>/statuses/add/     — ajouter un statut
  * /admin/methodologies/<pk>/roles/add/        — ajouter un rôle
  * /admin/methodologies/<pk>/kpis/add/         — ajouter un KPI
  * /admin/methodologies/<pk>/workflows/add/    — ajouter un workflow
  * /admin/methodologies/<pk>/transitions/add/  — ajouter une transition
"""

from __future__ import annotations

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.utils.text import slugify
from django.views import View
from django.views.decorators.csrf import csrf_protect

from project import models as dm
from project.utils.workspaces import get_user_workspace_ids
from project.views import DevflowBaseMixin, WorkspaceSecurityMixin


def _user_is_admin(user) -> bool:
    if user.is_superuser:
        return True
    try:
        from project.services.rbac import RBACService
        return RBACService.can(user, "workspace.manage")
    except Exception:
        return False


def _get_editable_methodology(request, pk):
    """Récupère une méthodologie modifiable par le user (custom du workspace)."""
    ws_ids = get_user_workspace_ids(request.user)
    methodology = dm.Methodology.objects.filter(pk=pk).first()
    if methodology is None:
        raise Http404("Méthodologie introuvable.")
    if methodology.is_system:
        if not request.user.is_superuser:
            raise Http404("Méthodologie système — non modifiable.")
    elif methodology.workspace_id and methodology.workspace_id not in ws_ids:
        raise Http404("Accès refusé (cross-tenant).")
    return methodology


class MethodologyListView(WorkspaceSecurityMixin, DevflowBaseMixin, View):
    template_name = "project/methodology_admin/list.html"

    def get(self, request):
        ws_ids = get_user_workspace_ids(request.user)
        from django.db.models import Q
        methodologies = (
            dm.Methodology.objects
            .filter(Q(workspace_id__in=ws_ids) | Q(workspace__isnull=True))
            .order_by("family", "name")
        )
        return render(request, self.template_name, {
            "methodologies": methodologies,
            "can_create": _user_is_admin(request.user),
            "section": "admin",
            "page_title": "Méthodologies",
            "breadcrumb": "Admin · Méthodologies",
        })


class MethodologyDetailView(WorkspaceSecurityMixin, DevflowBaseMixin, View):
    template_name = "project/methodology_admin/detail.html"

    def get(self, request, pk):
        methodology = _get_editable_methodology(request, pk)
        return render(request, self.template_name, {
            "methodology": methodology,
            "statuses": methodology.statuses.order_by("position"),
            "roles": methodology.roles.order_by("name"),
            "ceremonies": methodology.ceremonies.order_by("position"),
            "kpis": methodology.kpis.order_by("position"),
            "workflows": methodology.workflows.order_by("name"),
            "artifacts": methodology.artifacts.order_by("position"),
            "can_edit": not methodology.is_system or request.user.is_superuser,
            "section": "admin",
            "page_title": methodology.name,
            "breadcrumb": f"Admin · Méthodologies · {methodology.name}",
        })


class MethodologyCreateView(WorkspaceSecurityMixin, DevflowBaseMixin, View):
    template_name = "project/methodology_admin/form.html"

    def get(self, request):
        if not _user_is_admin(request.user):
            raise Http404("Permission insuffisante.")
        return render(request, self.template_name, {
            "methodology": None,
            "family_choices": dm.Methodology.Family.choices,
            "section": "admin",
            "page_title": "Nouvelle méthodologie",
        })

    @method_decorator(csrf_protect)
    def post(self, request):
        if not _user_is_admin(request.user):
            raise Http404("Permission insuffisante.")
        name = (request.POST.get("name") or "").strip()
        if not name:
            messages.error(request, "Le nom est obligatoire.")
            return redirect("methodology_admin_create")
        ws_ids = get_user_workspace_ids(request.user)
        # workspace = le workspace courant si dispo
        workspace = None
        try:
            workspace = self.get_current_workspace()
        except Exception:
            if ws_ids:
                workspace = dm.Workspace.objects.filter(pk=ws_ids[0]).first()

        family = request.POST.get("family") or "custom"
        code = slugify(name)[:50]
        # Éviter collision avec un code existant
        suffix = 1
        base_code = code
        while dm.Methodology.objects.filter(code=code).exists():
            code = f"{base_code}-{suffix}"
            suffix += 1

        methodology = dm.Methodology.objects.create(
            workspace=workspace,
            code=code,
            name=name[:100],
            family=family,
            description=(request.POST.get("description") or "")[:5000],
            icon=(request.POST.get("icon") or "")[:50],
            accent_color=(request.POST.get("accent_color") or "")[:7],
            is_system=False,
            is_active=True,
            config={},
        )
        messages.success(request, f"Méthodologie « {methodology.name} » créée.")
        return redirect("methodology_admin_detail", pk=methodology.pk)


class MethodologyUpdateView(WorkspaceSecurityMixin, DevflowBaseMixin, View):
    template_name = "project/methodology_admin/form.html"

    def get(self, request, pk):
        methodology = _get_editable_methodology(request, pk)
        if methodology.is_system and not request.user.is_superuser:
            raise Http404("Méthodologie système non modifiable.")
        return render(request, self.template_name, {
            "methodology": methodology,
            "family_choices": dm.Methodology.Family.choices,
            "section": "admin",
            "page_title": f"Éditer {methodology.name}",
        })

    @method_decorator(csrf_protect)
    def post(self, request, pk):
        methodology = _get_editable_methodology(request, pk)
        if methodology.is_system and not request.user.is_superuser:
            raise Http404("Méthodologie système non modifiable.")
        methodology.name = (request.POST.get("name") or methodology.name)[:100]
        methodology.family = request.POST.get("family") or methodology.family
        methodology.description = (request.POST.get("description") or "")[:5000]
        methodology.icon = (request.POST.get("icon") or "")[:50]
        methodology.accent_color = (request.POST.get("accent_color") or "")[:7]
        methodology.is_active = request.POST.get("is_active", "on") == "on"
        methodology.save()
        messages.success(request, "Méthodologie mise à jour.")
        return redirect("methodology_admin_detail", pk=methodology.pk)


class MethodologyDeleteView(WorkspaceSecurityMixin, DevflowBaseMixin, View):

    @method_decorator(csrf_protect)
    def post(self, request, pk):
        methodology = _get_editable_methodology(request, pk)
        if methodology.is_system:
            messages.error(request, "Une méthodologie système ne peut pas être supprimée.")
            return redirect("methodology_admin_detail", pk=pk)
        name = methodology.name
        methodology.delete()
        messages.success(request, f"Méthodologie « {name} » supprimée.")
        return redirect("methodology_admin_list")


# ────────────────────────────────────────────────────────────────────
# Sous-éléments (statuts, rôles, KPIs, workflows, transitions)
# ────────────────────────────────────────────────────────────────────
class MethodologyAddStatusView(WorkspaceSecurityMixin, DevflowBaseMixin, View):

    @method_decorator(csrf_protect)
    def post(self, request, pk):
        methodology = _get_editable_methodology(request, pk)
        if methodology.is_system and not request.user.is_superuser:
            raise Http404("Non modifiable.")
        name = (request.POST.get("name") or "").strip()
        if not name:
            messages.error(request, "Nom requis.")
            return redirect("methodology_admin_detail", pk=pk)
        code = slugify(name)[:50]
        last_pos = (
            methodology.statuses.order_by("-position")
            .values_list("position", flat=True).first() or 0
        )
        try:
            dm.MethodologyStatus.objects.create(
                methodology=methodology,
                code=code,
                name=name[:80],
                category=request.POST.get("category") or "todo",
                color=(request.POST.get("color") or "")[:7],
                position=last_pos + 1,
                is_initial=request.POST.get("is_initial") == "on",
                is_final=request.POST.get("is_final") == "on",
                wip_limit=int(request.POST.get("wip_limit") or 0) or None,
            )
            messages.success(request, "Statut ajouté.")
        except Exception as exc:
            messages.error(request, f"Erreur : {exc}")
        return redirect("methodology_admin_detail", pk=pk)


class MethodologyAddRoleView(WorkspaceSecurityMixin, DevflowBaseMixin, View):

    @method_decorator(csrf_protect)
    def post(self, request, pk):
        methodology = _get_editable_methodology(request, pk)
        if methodology.is_system and not request.user.is_superuser:
            raise Http404("Non modifiable.")
        name = (request.POST.get("name") or "").strip()
        if not name:
            messages.error(request, "Nom requis.")
            return redirect("methodology_admin_detail", pk=pk)
        try:
            dm.MethodologyRole.objects.create(
                methodology=methodology,
                code=slugify(name)[:50],
                name=name[:80],
                description=(request.POST.get("description") or "")[:2000],
                is_required=request.POST.get("is_required") == "on",
            )
            messages.success(request, "Rôle ajouté.")
        except Exception as exc:
            messages.error(request, f"Erreur : {exc}")
        return redirect("methodology_admin_detail", pk=pk)


class MethodologyAddKPIView(WorkspaceSecurityMixin, DevflowBaseMixin, View):

    @method_decorator(csrf_protect)
    def post(self, request, pk):
        methodology = _get_editable_methodology(request, pk)
        if methodology.is_system and not request.user.is_superuser:
            raise Http404("Non modifiable.")
        name = (request.POST.get("name") or "").strip()
        strategy = (request.POST.get("compute_strategy") or "").strip()
        if not name or not strategy:
            messages.error(request, "Nom + stratégie de calcul requis.")
            return redirect("methodology_admin_detail", pk=pk)
        try:
            dm.MethodologyKPI.objects.create(
                methodology=methodology,
                code=slugify(name)[:50],
                name=name[:80],
                unit=(request.POST.get("unit") or "")[:20],
                chart_type=request.POST.get("chart_type") or "number",
                compute_strategy=strategy[:80],
                is_pinned=request.POST.get("is_pinned") == "on",
            )
            messages.success(request, "KPI ajouté.")
        except Exception as exc:
            messages.error(request, f"Erreur : {exc}")
        return redirect("methodology_admin_detail", pk=pk)
