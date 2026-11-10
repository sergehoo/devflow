"""
Chantier « ai » — structuration automatique des projets par l'IA (frontend React).

Fines vues DRF au-dessus des vues Django et services existants (aucune règle
métier réécrite) :

* Genesis (``ai/genesis/``) : ``ProjectGenesisForm`` + ``ProjectGenesisService``
  (mêmes validations que ``ProjectGenesisView``, workspace vérifié par
  ``user_can_access_workspace``) ;
* propositions IA (``ai-proposals/…``, ``projects/<id>/ai-proposals/…``) : les
  vues ``views_ai_proposal`` sont exécutées telles quelles (``dispatch``
  complet : ``AIProposalAccessMixin``, journalisation, ``ProposalApplyService``) ;
* import documentaire (``imports/…``) : vues ``ProjectDocumentImport*`` ; l'analyse
  enchaîne ``ProjectDocumentAIService.extract_text`` puis Genesis (nouveau projet)
  ou ``ProjectAIStructureService`` (projet rattaché) ;
* copilote projet (``projects/<id>/copilot/…``) : ``services.methodology.copilot``
  et ``AIActionLog`` (RBAC des outils appliqué par ``execute_tool``).

Sécurité : objets résolus dans les workspaces de l'utilisateur (404 sinon),
RBAC (``RBACService.can``, 403 sinon) sur toute écriture ou génération,
``AIActionRateThrottle`` sur toute action pouvant appeler un fournisseur IA
payant, repli heuristique des services quand l'IA est désactivée.

Droits (matrice ``services/rbac.py``) :

* ``project.create`` (workspace) : Genesis, analyse d'un document sans projet ;
* ``ai.generate_roadmap`` (projet) : déclenchement, régénération, analyse d'un
  document rattaché à un projet ;
* ``project.edit`` (projet) : validation / rejet / édition des éléments, « Tout
  valider », rejet et application d'une proposition.

Sur un projet, ses responsables (owner / product manager) gardent la main,
comme pour les tâches (``services.task_permissions``). La lecture reste ouverte
aux membres du workspace (comme l'ancienne interface).
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from django.contrib import messages as dj_messages
from django.contrib.messages import get_messages
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied as DjangoPermissionDenied
from django.db.models import Count
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import Resolver404, resolve
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.text import Truncator
from rest_framework import permissions, status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from project import models as dm
from project.api.form_bridge import describe_form, form_errors
from project.api.resources import _run as run_legacy_view
from project.api.throttles import AIActionRateThrottle
from project.utils.workspaces import get_user_workspace_ids, user_can_access_workspace

logger = logging.getLogger(__name__)

Proposal = dm.ProjectAIProposal
Item = dm.ProjectAIProposalItem

RUNNING = {Proposal.Status.PENDING, Proposal.Status.GENERATING}
EDITABLE = {Proposal.Status.READY, Proposal.Status.PARTIALLY_VALIDATED, Proposal.Status.VALIDATED}

# Objets créés par ProposalApplyService / copilote → routes React.
OBJECT_ROUTES = {
    "Task": "/tasks/{}", "Sprint": "/m/sprint/{}", "Milestone": "/m/milestone/{}",
    "BacklogItem": "/m/backlog-item/{}", "RoadmapItem": "/m/roadmap-item/{}", "Roadmap": "/m/roadmap/{}",
    "TaskDependency": "/m/task-dependency/{}", "TaskAssignment": "/m/task-assignment/{}",
    "Risk": "/m/risk/{}", "Invoice": "/m/invoice/{}", "InvoiceClient": "/m/invoice-client/{}",
    "ProjectMeeting": "/meetings/{}", "Project": "/projects/{}",
}

ITEM_FIELD_LABELS = {
    "title": "Titre", "description": "Description", "priority": "Priorité", "complexity": "Complexité",
    "estimate_hours": "Charge estimée (h)", "recommended_profile": "Profil recommandé",
    "recommended_assignee": "Membre recommandé", "sprint_ref": "Sprint (réf.)", "milestone_ref": "Jalon (réf.)",
    "start_date": "Début", "end_date": "Fin / échéance", "velocity_target": "Vélocité cible",
}


# ─────────────────────────────────────────────────────────────────────────
# Utilitaires
# ─────────────────────────────────────────────────────────────────────────
def _iso(value):
    return value.isoformat() if value else None


def _user_label(user) -> str:
    if user is None:
        return ""
    return user.get_full_name() or user.get_username()


def _flag(value, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "on", "yes", "oui"}


def _object_link(model: str, pk) -> str | None:
    route = OBJECT_ROUTES.get(model or "")
    return route.format(pk) if route and pk else None


def _project_or_404(request, pk) -> dm.Project:
    return get_object_or_404(
        dm.Project.objects.select_related("workspace"),
        pk=pk, workspace_id__in=get_user_workspace_ids(request.user),
    )


# ─────────────────────────────────────────────────────────────────────────
# Droits (RBAC) — le masquage des boutons côté React n'est qu'un confort
# ─────────────────────────────────────────────────────────────────────────
RIGHT_CREATE = "project.create"
RIGHT_GENERATE = "ai.generate_roadmap"
RIGHT_STRUCTURE = "project.edit"


def _can(user, action: str, *, project=None, workspace=None) -> bool:
    from project.services.rbac import RBACService

    if project is not None:
        if user.pk in (project.owner_id, project.product_manager_id):
            return True  # responsables du projet (même règle que task_permissions)
        return RBACService.can(user, action, target=project)
    return RBACService.can(user, action, workspace=workspace)


def _require(user, action: str, **scope) -> None:
    if not _can(user, action, **scope):
        raise PermissionDenied("Action non autorisée pour votre rôle.")


def ai_status() -> dict:
    """Fournisseur IA actif (sinon les services basculent sur leurs heuristiques)."""
    try:
        from project.services.ai.factory import get_ai_provider

        provider = get_ai_provider()
        available = bool(provider.is_available())
    except Exception:  # pragma: no cover — configuration cassée
        return {"available": False, "provider": ""}
    name = getattr(provider, "name", "") or ""
    if available and getattr(provider, "providers", None):
        names = [p.name for p in provider.providers if p.is_available()]
        name = names[0] if names else name
    return {"available": available, "provider": name if available else ""}


def _dispatch(request, view_class, kwargs, *, ajax=False):
    """Exécute une vue Django existante (dispatch complet) ; erreurs Django → erreurs DRF."""
    django_request = request._request
    django_request.user = request.user
    if ajax:
        django_request.META["HTTP_X_REQUESTED_WITH"] = "XMLHttpRequest"
        django_request.__dict__.pop("headers", None)  # ``headers`` est mis en cache
    if django_request.method == "POST" and "next" not in django_request.POST:
        post = django_request.POST.copy()
        post["next"] = "/"
        django_request.POST = post
    view = view_class()
    view.setup(django_request, **kwargs)
    try:
        response = view.dispatch(django_request, **kwargs)
    except (Http404, ObjectDoesNotExist):
        raise NotFound()
    except DjangoPermissionDenied as exc:
        raise PermissionDenied(str(exc) or None)
    if response.status_code == 403:
        raise PermissionDenied()
    return response, list(get_messages(django_request))


def _legacy_object(request, view_class, pk):
    """Objet résolu par le ``get_object`` (queryset scopé workspace) d'une DetailView existante."""
    django_request = request._request
    django_request.user = request.user
    view = view_class()
    view.setup(django_request, pk=pk)
    try:
        return view.get_object()
    except (Http404, ObjectDoesNotExist):
        raise NotFound()


def _redirect_target(response):
    """(nom d'URL, kwargs) de la redirection émise par une vue Django."""
    if response.status_code not in (301, 302):
        return None, {}
    try:
        match = resolve(urlsplit(response.get("Location", "")).path)
    except Resolver404:
        return None, {}
    return match.url_name, match.kwargs


def _action_result(response, notices) -> Response:
    """Vue d'action Django → JSON : JSON renvoyé tel quel ; redirection = succès sauf message d'erreur."""
    if isinstance(response, JsonResponse):
        data = json.loads(response.content or b"{}")
        if response.status_code >= 400 and isinstance(data, dict) and "error" in data and "detail" not in data:
            data["detail"] = data["error"]
        return Response(data, status=response.status_code)
    errors = [str(m) for m in notices if m.level >= dj_messages.ERROR]
    if response.status_code in (301, 302) and not errors:
        return Response({"messages": [str(m) for m in notices]})
    return Response({"detail": " ".join(errors) or "Action impossible."}, status=status.HTTP_400_BAD_REQUEST)


# Au-delà, une proposition « en attente / en cours » est considérée bloquée
# (worker indisponible, ancienne proposition orpheline) : l'interface cesse de la suivre.
GENERATION_TIMEOUT = timedelta(minutes=15)


def _is_running(p) -> bool:
    return p.status in RUNNING and bool(p.created_at) and timezone.now() - p.created_at < GENERATION_TIMEOUT


def _conflict(detail: str) -> Response:
    return Response({"detail": detail}, status=status.HTTP_409_CONFLICT)


# ─────────────────────────────────────────────────────────────────────────
# Sérialisation des propositions
# ─────────────────────────────────────────────────────────────────────────
def _get_proposal(request, pk) -> dm.ProjectAIProposal:
    """Même règle d'accès que l'ancienne interface (``AIProposalAccessMixin``) : 404 hors workspace."""
    from project.views_ai_proposal import AIProposalAccessMixin

    mixin = AIProposalAccessMixin()
    request._request.user = request.user
    mixin.request = request._request
    return mixin.get_proposal(pk)


def _items_counts(proposal_ids) -> dict[int, int]:
    rows = Item.objects.filter(proposal_id__in=proposal_ids).values("proposal_id").annotate(n=Count("id"))
    return {r["proposal_id"]: r["n"] for r in rows}


def _proposal_row(p, items_count: int) -> dict:
    return {
        "id": p.pk,
        "status": p.status,
        "status_label": p.get_status_display(),
        "project": {"id": p.project_id, "name": p.project.name},
        "items_count": items_count,
        "used_provider": p.used_provider,
        "triggered_by": _user_label(p.triggered_by),
        "created_at": _iso(p.created_at),
        "running": _is_running(p),
    }


def _as_list(value) -> list[str]:
    return [str(v) for v in value if v not in (None, "")] if isinstance(value, list) else []


def _item(i: dm.ProjectAIProposalItem) -> dict:
    applied = None
    if i.applied_object_id:
        applied = {
            "model": i.applied_object_model, "id": i.applied_object_id,
            "link": _object_link(i.applied_object_model, i.applied_object_id),
        }
    assignee = i.recommended_assignee
    return {
        "id": i.pk,
        "kind": i.kind,
        "kind_label": i.get_kind_display(),
        "item_status": i.item_status,
        "item_status_label": i.get_item_status_display(),
        "local_ref": i.local_ref,
        "title": i.title,
        "description": i.description,
        "order_index": i.order_index,
        "priority": i.priority,
        "complexity": i.complexity,
        "estimate_hours": float(i.estimate_hours or 0),
        "recommended_profile": i.recommended_profile,
        "recommended_assignee": {"id": assignee.pk, "name": _user_label(assignee)} if assignee else None,
        "sprint_ref": i.sprint_ref,
        "milestone_ref": i.milestone_ref,
        "depends_on_refs": _as_list(i.depends_on_refs),
        "acceptance_criteria": _as_list(i.acceptance_criteria),
        "start_date": _iso(i.start_date),
        "end_date": _iso(i.end_date),
        "velocity_target": i.velocity_target,
        "edited_by": _user_label(i.edited_by),
        "edited_at": _iso(i.edited_at),
        "applied": applied,
    }


def _ensure_item_editable(proposal, item):
    """
    Un élément appliqué ou une proposition close ne se modifie plus : revalider un
    élément APPLIED le ferait recréer au prochain « Appliquer » (doublons).
    """
    if item.item_status == Item.ItemStatus.APPLIED:
        return _conflict("Cet élément a déjà été appliqué au projet.")
    if proposal.status not in EDITABLE:
        return _conflict("La proposition n'est plus modifiable dans son état actuel.")
    return None


# ─────────────────────────────────────────────────────────────────────────
# Statut IA
# ─────────────────────────────────────────────────────────────────────────
class AIStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(ai_status())


# ─────────────────────────────────────────────────────────────────────────
# Genesis — création d'un projet complet depuis un brief
# ─────────────────────────────────────────────────────────────────────────
class GenesisView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_throttles(self):
        if self.request.method == "POST":
            return [AIActionRateThrottle()]
        return super().get_throttles()

    def get(self, request):
        from project.api.views_auth import _current_workspace
        from project.views_ai_genesis import ProjectGenesisForm

        from project.services.rbac import rbac_workspace_ids

        form = ProjectGenesisForm(user=request.user)
        # Seuls les workspaces où l'utilisateur peut créer un projet sont proposés.
        workspaces = form.fields["workspace"].queryset.filter(pk__in=rbac_workspace_ids(request.user, RIGHT_CREATE))
        form.fields["workspace"].queryset = workspaces
        current = _current_workspace(request.user)
        if current and workspaces.filter(pk=current.pk).exists():
            form.initial["workspace"] = current.pk
        data = describe_form(form)
        data["ai"] = ai_status()
        data["can_create"] = workspaces.exists()
        return Response(data)

    def post(self, request):
        from project.services.ai.services.project_genesis import ProjectGenesisService
        from project.views_ai_genesis import ProjectGenesisForm

        payload = request.data
        form = ProjectGenesisForm(payload, user=request.user)
        if not form.is_valid():
            return Response(form_errors(form), status=status.HTTP_400_BAD_REQUEST)
        workspace = form.cleaned_data["workspace"]
        # SECURITY (convention n°4) : workspace reçu vérifié explicitement.
        if not user_can_access_workspace(request.user, workspace):
            raise PermissionDenied("Workspace inaccessible.")
        _require(request.user, RIGHT_CREATE, workspace=workspace)
        try:
            result = ProjectGenesisService.create_project_from_brief(
                workspace=workspace,
                name=form.cleaned_data["name"],
                description=form.cleaned_data["description"],
                owner=request.user,
                priority=form.cleaned_data["priority"],
                target_date=form.cleaned_data.get("target_date"),
                methodology=form.cleaned_data.get("methodology") or None,
                use_ai=_flag(payload.get("use_ai"), True),
                auto_apply=form.cleaned_data.get("auto_apply", False),
            )
        except ValueError as exc:
            return Response({"non_field_errors": [str(exc)]}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            logger.exception("Genesis (API React) failed")
            return Response({"detail": f"Erreur Genesis IA : {exc}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        applied = result.proposal.status == Proposal.Status.APPLIED
        counts = result.counts or {}
        if applied:
            message = (
                f"Projet « {result.project.name} » créé par DevFlow AI ({result.used_provider}). "
                f"{counts.get('tasks', 0)} tâche(s), {counts.get('sprints', 0)} sprint(s), "
                f"{counts.get('milestones', 0)} jalon(s) générés."
            )
        else:
            message = "Projet créé. Une proposition IA est prête à validation."
        return Response({
            "project": {"id": result.project.pk, "name": result.project.name},
            "proposal": {"id": result.proposal.pk, "status": result.proposal.status,
                         "status_label": result.proposal.get_status_display()},
            "applied": applied,
            "used_provider": result.used_provider,
            "counts": counts,
            "messages": [message],
        }, status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────────────────────────────────
# Propositions IA
# ─────────────────────────────────────────────────────────────────────────
class AIProposalListView(APIView):
    """Liste globale (``ProjectAIProposalListView`` : filtres ``status`` / ``project``, pagination)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from project.views_ai_proposal import ProjectAIProposalListView

        _view, ctx = run_legacy_view(ProjectAIProposalListView, request, {})
        proposals = list(ctx.get("object_list") or [])
        counts = _items_counts([p.pk for p in proposals])
        page = ctx.get("page_obj")
        return Response({
            "results": [_proposal_row(p, counts.get(p.pk, 0)) for p in proposals],
            "count": page.paginator.count if page else len(proposals),
            "page": page.number if page else 1,
            "num_pages": page.paginator.num_pages if page else 1,
            "status_choices": [{"value": v, "label": str(lbl)} for v, lbl in Proposal.Status.choices],
        })


class AIProposalDetailView(APIView):
    """Aperçu complet (contexte de ``ProjectAIProposalDetailView`` : éléments, cohérence, journal)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        from project.views_ai_proposal import ProjectAIProposalDetailView

        _view, ctx = run_legacy_view(ProjectAIProposalDetailView, request, {"pk": pk})
        p = ctx.get("proposal")
        if p is None:
            raise NotFound()
        items = list(p.items.select_related("recommended_assignee", "edited_by").order_by("order_index", "id"))
        coherence = ctx.get("coherence") or {}
        can_edit = _can(request.user, RIGHT_STRUCTURE, project=p.project)
        running = _is_running(p)
        closed = p.status in (Proposal.Status.APPLIED, Proposal.Status.REJECTED)
        by_kind: dict[str, int] = {}
        applied_by_kind: dict[str, int] = {}
        for i in items:
            by_kind[i.kind] = by_kind.get(i.kind, 0) + 1
            if i.item_status == Item.ItemStatus.APPLIED:
                applied_by_kind[i.kind] = applied_by_kind.get(i.kind, 0) + 1
        return Response({
            "id": p.pk,
            "status": p.status,
            "status_label": p.get_status_display(),
            "project": {"id": p.project_id, "name": p.project.name},
            "summary": p.summary,
            "risks_summary": p.risks_summary,
            "recommendations": [str(r) for r in (ctx.get("recommendations") or [])],
            "used_provider": p.used_provider,
            "used_model": p.used_model,
            "tokens_used": p.tokens_used,
            "error_message": p.error_message,
            "triggered_by": _user_label(p.triggered_by),
            "validated_by": _user_label(p.validated_by),
            "validated_at": _iso(p.validated_at),
            "applied_at": _iso(p.applied_at),
            "rejected_at": _iso(p.rejected_at),
            "created_at": _iso(p.created_at),
            "updated_at": _iso(p.updated_at),
            "running": running,
            # États autorisés par le serveur (409 sinon) ET droits de l'utilisateur (403 sinon).
            "can_edit": can_edit,
            "editable": can_edit and p.status in EDITABLE,
            "can_validate_all": can_edit and not closed and p.status not in RUNNING,
            "can_apply": can_edit and p.status in EDITABLE,
            "can_reject": can_edit and not closed and not running,
            "can_regenerate": _can(request.user, RIGHT_GENERATE, project=p.project),
            "counts": {
                "total": len(items),
                "validated": sum(1 for i in items if i.item_status == Item.ItemStatus.VALIDATED),
                "by_kind": by_kind,
                "applied_by_kind": applied_by_kind,
            },
            "coherence": {
                "total_hours": float(coherence.get("total_hours") or 0),
                "unassigned_tasks": coherence.get("unassigned_tasks", 0),
                "broken_dependencies": coherence.get("broken_dependencies", []),
                "load_rows": [
                    {"user_id": r["user"].pk, "label": r["label"], "hours": r["hours"]}
                    for r in coherence.get("load_rows", [])
                ],
            },
            "kinds": [{"value": v, "label": str(lbl)} for v, lbl in Item.Kind.choices],
            "items": [_item(i) for i in items],
            "logs": [
                {"id": log.pk, "action": log.action, "action_label": log.get_action_display(),
                 "actor": _user_label(log.actor), "message": log.message, "created_at": _iso(log.created_at)}
                for log in p.logs.select_related("actor").order_by("-created_at")
            ],
        })


class AIProposalActionView(APIView):
    """``validate-all`` / ``reject`` / ``apply`` / ``regenerate`` — vues Django existantes."""

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get_throttles(self):
        if self.kwargs.get("action") == "regenerate":  # nouvel appel au fournisseur IA
            return [AIActionRateThrottle()]
        return super().get_throttles()

    def post(self, request, pk, action):
        from project import views_ai_proposal as v

        if action not in ("validate-all", "reject", "apply", "regenerate"):
            raise NotFound("Action inconnue.")
        proposal = _get_proposal(request, pk)
        _require(request.user, RIGHT_GENERATE if action == "regenerate" else RIGHT_STRUCTURE, project=proposal.project)
        kwargs = {"pk": proposal.pk}
        if action == "validate-all":
            if proposal.status in (Proposal.Status.APPLIED, Proposal.Status.REJECTED) or proposal.status in RUNNING:
                return _conflict("La proposition ne peut plus être validée.")
            return _action_result(*_dispatch(request, v.ProjectAIProposalValidateAllView, kwargs))
        if action == "reject":
            if proposal.status == Proposal.Status.APPLIED:
                return _conflict("Une proposition appliquée ne peut plus être rejetée.")
            if proposal.status == Proposal.Status.REJECTED:
                return _conflict("Cette proposition est déjà rejetée.")
            if _is_running(proposal):
                # Génération active : le rejet attend sa fin. Une proposition bloquée
                # (au-delà de GENERATION_TIMEOUT) reste rejetable ; le service ne
                # repasse alors jamais une proposition rejetée en « prête ».
                return _conflict("La génération est en cours : attendez qu'elle se termine pour rejeter la proposition.")
            return _action_result(*_dispatch(request, v.ProjectAIProposalRejectView, kwargs))
        if action == "apply":
            response = _action_result(*_dispatch(request, v.ProjectAIProposalApplyView, kwargs))
            if response.status_code == 200:
                applied = (
                    proposal.items.filter(item_status=Item.ItemStatus.APPLIED)
                    .values("kind").annotate(n=Count("id"))
                )
                response.data.update({
                    "project_id": proposal.project_id,
                    "applied_by_kind": {r["kind"]: r["n"] for r in applied},
                })
            return response
        # regenerate
        source = _source_import(proposal)
        if source is not None:
            return _regenerate_from_document(request, proposal, source)
        try:
            response, notices = _dispatch(request, v.ProjectAIProposalRegenerateView, kwargs)
        except (NotFound, PermissionDenied):
            raise
        except Exception as exc:
            logger.exception("AI proposal regenerate failed for proposal %s", proposal.pk)
            return Response({"detail": f"La régénération a échoué : {exc}"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        url_name, url_kwargs = _redirect_target(response)
        if url_name != "ai_proposal_detail":
            return Response({"detail": "Régénération impossible."}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"id": int(url_kwargs["pk"]), "messages": [str(m) for m in notices]},
                        status=status.HTTP_201_CREATED)


def _source_import(proposal):
    """Import documentaire dont la proposition est issue (son texte est retransmis à l'IA)."""
    return (
        dm.ProjectDocumentImport.objects
        .filter(project_id=proposal.project_id, ai_payload__proposal_id=proposal.pk)
        .exclude(extracted_text="")
        .order_by("-updated_at", "-id")
        .first()
    )


def _regenerate_from_document(request, proposal, source):
    """
    Régénération d'une proposition issue d'un import : même traitement que
    ``ProjectAIProposalRegenerateView`` (formulaire ``use_ai``, nouvelle
    proposition, l'ancienne reste dans l'historique), avec le texte du document
    source comme contexte — sinon la nouvelle proposition perdrait le périmètre
    décrit par le document. L'import pointe ensuite vers la nouvelle proposition.
    """
    from project.services.ai.services.project_structure import ProjectAIStructureService
    from project.views_ai_proposal import ProjectAIProposalRegenerateForm

    form = ProjectAIProposalRegenerateForm(request.data)
    use_ai = form.cleaned_data.get("use_ai", True) if form.is_valid() else True
    try:
        result = ProjectAIStructureService.generate_for_project(
            project=proposal.project, triggered_by=request.user, use_ai=use_ai,
            document_text=source.extracted_text,
        )
    except Exception as exc:
        logger.exception("AI proposal regenerate (document %s) failed for proposal %s", source.pk, proposal.pk)
        return Response({"detail": f"La régénération a échoué : {exc}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    new = result.proposal
    source.ai_payload = {
        **(source.ai_payload if isinstance(source.ai_payload, dict) else {}),
        "proposal_id": new.pk,
        "used_provider": result.used_provider,
        "summary": (new.summary or "")[:2000],
        "structure": new.raw_payload or {},
    }
    source.save(update_fields=["ai_payload", "updated_at"])
    name = _file_meta(source.file)["file_name"]
    return Response({
        "id": new.pk,
        "messages": [f"Nouvelle proposition générée à partir du document « {name} » "
                     f"({result.items_created} items, {result.used_provider})."],
    }, status=status.HTTP_201_CREATED)


class AIProposalItemActionView(APIView):
    """Validation / rejet d'un élément (``ProjectAIProposalItemValidateView`` / ``…RejectView``)."""

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk, item_pk, action):
        from project import views_ai_proposal as v

        view_class = {"validate": v.ProjectAIProposalItemValidateView,
                      "reject": v.ProjectAIProposalItemRejectView}.get(action)
        if view_class is None:
            raise NotFound("Action inconnue.")
        proposal = _get_proposal(request, pk)
        item = get_object_or_404(proposal.items.all(), pk=item_pk)
        _require(request.user, RIGHT_STRUCTURE, project=proposal.project)
        refused = _ensure_item_editable(proposal, item)
        if refused:
            return refused
        response = _action_result(*_dispatch(request, view_class, {"pk": proposal.pk, "item_pk": item.pk}))
        if response.status_code == 200:
            item.refresh_from_db()
            proposal.refresh_from_db(fields=["status"])
            response.data = {**(response.data or {}), "item": _item(item),
                             "proposal_status": proposal.status,
                             "proposal_status_label": proposal.get_status_display()}
        return response


class AIProposalItemFormView(APIView):
    """Édition d'un élément (formulaire ``ProjectAIProposalItemEditForm`` via ``ProjectAIProposalItemEditView``)."""

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def _target(self, request, pk, item_pk):
        proposal = _get_proposal(request, pk)
        item = get_object_or_404(proposal.items.select_related("recommended_assignee"), pk=item_pk)
        return proposal, item

    @staticmethod
    def _describe(form) -> dict:
        data = describe_form(form)
        for field in data["fields"]:
            field["label"] = ITEM_FIELD_LABELS.get(field["name"], field["label"])
        return data

    def get(self, request, pk, item_pk):
        from project.views_ai_proposal import ProjectAIProposalItemEditView

        proposal, item = self._target(request, pk, item_pk)
        response, _notices = _dispatch(request, ProjectAIProposalItemEditView, {"pk": proposal.pk, "item_pk": item.pk})
        form = (getattr(response, "context_data", None) or {}).get("form")
        if form is None:
            raise NotFound()
        data = self._describe(form)
        data["item"] = _item(item)
        return Response(data)

    def post(self, request, pk, item_pk):
        from project.views_ai_proposal import ProjectAIProposalItemEditView

        proposal, item = self._target(request, pk, item_pk)
        _require(request.user, RIGHT_STRUCTURE, project=proposal.project)
        refused = _ensure_item_editable(proposal, item)
        if refused:
            return refused
        response, notices = _dispatch(request, ProjectAIProposalItemEditView, {"pk": proposal.pk, "item_pk": item.pk})
        if response.status_code in (301, 302):
            item.refresh_from_db()
            return Response({"id": item.pk, "messages": [str(m) for m in notices], "item": _item(item)})
        form = (getattr(response, "context_data", None) or {}).get("form")
        if form is not None and form.errors:
            return Response(form_errors(form), status=status.HTTP_400_BAD_REQUEST)
        return Response({"detail": "Enregistrement impossible."}, status=status.HTTP_400_BAD_REQUEST)


class ProjectAIProposalsView(APIView):
    """Historique des propositions d'un projet (``ProjectAIProposalsForProjectView``)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        from project.views_ai_proposal import ProjectAIProposalsForProjectView

        project = _project_or_404(request, pk)
        _view, ctx = run_legacy_view(ProjectAIProposalsForProjectView, request, {"project_pk": project.pk})
        proposals = list(ctx.get("object_list") or [])
        counts = _items_counts([p.pk for p in proposals])
        return Response({
            "project": {"id": project.pk, "name": project.name,
                        "methodology_label": project.get_methodology_display() if project.methodology else ""},
            "proposals": [_proposal_row(p, counts.get(p.pk, 0)) for p in proposals],
            "ai": ai_status(),
            "can_trigger": _can(request.user, RIGHT_GENERATE, project=project),
        })


class ProjectAIProposalTriggerAPIView(APIView):
    """Déclenchement asynchrone (``ProjectAIProposalTriggerView``, mode AJAX : Celery, repli thread)."""

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [AIActionRateThrottle]

    def post(self, request, pk):
        from project.views_ai_proposal import ProjectAIProposalTriggerView

        project = _project_or_404(request, pk)
        _require(request.user, RIGHT_GENERATE, project=project)
        response, notices = _dispatch(request, ProjectAIProposalTriggerView, {"project_pk": project.pk}, ajax=True)
        result = _action_result(response, notices)
        if result.status_code == 200:
            result.status_code = status.HTTP_202_ACCEPTED
        return result


class ProjectAIProposalStatusAPIView(APIView):
    """Statut / progression de la dernière proposition (``ProjectAIProposalStatusView``)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        from project.views_ai_proposal import ProjectAIProposalStatusView

        project = _project_or_404(request, pk)
        response, notices = _dispatch(request, ProjectAIProposalStatusView, {"project_pk": project.pk})
        return _action_result(response, notices)


# ─────────────────────────────────────────────────────────────────────────
# Copilote projet
# ─────────────────────────────────────────────────────────────────────────
def _project_ref(project) -> dict:
    return {
        "id": project.pk, "name": project.name,
        "methodology": project.methodology or "",
        "methodology_label": project.get_methodology_display() if project.methodology else "",
    }


class ProjectCopilotChatView(APIView):
    """Même traitement que ``ProjectCopilotAPIView`` (outils audités et soumis au RBAC)."""

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser]
    throttle_classes = [AIActionRateThrottle]

    def post(self, request, pk):
        from project.services.methodology.copilot import chat

        project = _project_or_404(request, pk)
        payload = request.data if isinstance(request.data, dict) else {}
        message = str(payload.get("message") or "").strip()
        if not message:
            return Response({"detail": "Message vide."}, status=status.HTTP_400_BAD_REQUEST)
        history = [
            (h.get("role"), str(h.get("content") or "")[:4000])
            for h in (payload.get("history") or []) if isinstance(h, dict)
        ][-10:]
        result = chat(project, request.user, message[:4000], history=history)
        for action in result.get("actions_executed") or []:
            res = action.get("result") if isinstance(action, dict) else None
            if isinstance(res, dict):
                action["link"] = _object_link(res.get("object_type"), res.get("object_id"))
        return Response(result)


class ProjectCopilotLogsView(APIView):
    """Journal d'actions IA du projet (``ProjectCopilotLogView`` : 50 dernières)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        project = _project_or_404(request, pk)
        logs = project.ai_action_logs.select_related("user").order_by("-created_at")[:50]
        return Response({
            "project": _project_ref(project),
            "ai": ai_status(),
            "logs": [
                {
                    "id": log.pk, "created_at": _iso(log.created_at), "tool_name": log.tool_name,
                    "user": _user_label(log.user), "status": log.status, "status_label": log.get_status_display(),
                    "duration_ms": log.duration_ms, "error_message": log.error_message,
                    "affected": (
                        {"type": log.affected_object_type, "id": log.affected_object_id,
                         "link": _object_link(log.affected_object_type, log.affected_object_id)}
                        if log.affected_object_type else None
                    ),
                }
                for log in logs
            ],
        })


# ─────────────────────────────────────────────────────────────────────────
# Import documentaire
# ─────────────────────────────────────────────────────────────────────────
def _file_meta(file) -> dict:
    name = file.name.rsplit("/", 1)[-1] if file else ""
    try:
        url = file.url if file else ""
    except ValueError:
        url = ""
    return {"file_name": name, "file_ext": name.rsplit(".", 1)[-1].lower() if "." in name else "", "file_url": url}


def _import_excerpt(obj) -> str:
    """Comme la liste historique : message d'erreur (90 car.) sinon début du texte extrait (100 car.)."""
    if obj.error_message:
        return Truncator(obj.error_message).chars(90)
    if obj.extracted_text:
        return Truncator(strip_tags(obj.extracted_text)).chars(100)
    return ""


def _import_row(obj) -> dict:
    return {
        "id": obj.pk,
        **_file_meta(obj.file),
        "status": obj.status,
        "status_label": obj.get_status_display(),
        "project": {"id": obj.project_id, "name": obj.project.name} if obj.project_id else None,
        "workspace": obj.workspace.name if obj.workspace_id else "",
        "uploaded_by": _user_label(obj.uploaded_by),
        "created_at": _iso(obj.created_at),
        "has_error": bool(obj.error_message),
        "excerpt": _import_excerpt(obj),
    }


ANALYSIS_LOCK = timedelta(minutes=10)


def _analysis_running(obj) -> bool:
    return obj.status == dm.ProjectDocumentImport.ImportStatus.PROCESSING and (
        obj.updated_at and timezone.now() - obj.updated_at < ANALYSIS_LOCK
    )


class ImportListView(APIView):
    """Liste (``ProjectDocumentImportListView`` : recherche ``q``, filtres, statistiques, pagination)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from project.views import ProjectDocumentImportListView

        query = request._request.GET
        if query.get("project") and not query["project"].isdigit():
            # ``?project=abc`` faisait lever une ValueError (500) dans la vue historique.
            query = query.copy()
            query.pop("project")
            request._request.GET = query
        _view, ctx = run_legacy_view(ProjectDocumentImportListView, request, {})
        imports = list(ctx.get("object_list") or [])
        page = ctx.get("page_obj")
        workspace = ctx.get("current_workspace")
        return Response({
            # Filtre ``?workspace=`` (validé par la vue : 404 hors des workspaces de l'utilisateur).
            "workspaces": [{"id": w.pk, "name": w.name} for w in (ctx.get("workspace_list") or [])],
            "results": [_import_row(o) for o in imports],
            "count": page.paginator.count if page else len(imports),
            "page": page.number if page else 1,
            "num_pages": page.paginator.num_pages if page else 1,
            "stats": ctx.get("stats") or {},
            "status_choices": [{"value": v, "label": str(lbl)} for v, lbl in dm.ProjectDocumentImport.ImportStatus.choices],
            "projects": [{"id": p.pk, "name": p.name} for p in (ctx.get("project_list") or [])],
            "workspace": {"id": workspace.pk, "name": workspace.name} if workspace else None,
        })


class ImportDetailView(APIView):
    """Fiche (``ProjectDocumentImportDetailView``) + proposition IA issue de l'analyse."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        from project.views import ProjectDocumentImportDetailView

        _view, ctx = run_legacy_view(ProjectDocumentImportDetailView, request, {"pk": pk})
        obj = ctx.get("import_obj") or ctx.get("object")
        if obj is None:
            raise NotFound()
        payload = obj.ai_payload if isinstance(obj.ai_payload, dict) else {}
        proposal = None
        if payload.get("proposal_id"):
            p = (
                Proposal.objects.filter(pk=payload["proposal_id"], workspace_id__in=get_user_workspace_ids(request.user))
                .select_related("project").first()
            )
            if p is not None:
                proposal = {"id": p.pk, "status": p.status, "status_label": p.get_status_display(),
                            "project_id": p.project_id}
        running = bool(_analysis_running(obj))
        return Response({
            **_import_row(obj),
            "extracted_text": obj.extracted_text,
            "ai_payload": obj.ai_payload or None,
            "error_message": obj.error_message,
            "updated_at": _iso(obj.updated_at),
            "related": [_import_row(r) for r in ctx.get("related_imports") or []],
            "proposal": proposal,
            "analysis_running": running,
            "can_analyze": not running and _can_analyze(request.user, obj),
            "ai": ai_status(),
        })


def _can_analyze(user, obj) -> bool:
    """Document rattaché : génération IA sur ce projet ; sinon l'analyse crée un projet."""
    if obj.project_id:
        return _can(user, RIGHT_GENERATE, project=obj.project)
    return _can(user, RIGHT_CREATE, workspace=obj.workspace)


class ImportAnalyzeView(APIView):
    """
    Analyse IA d'un document importé :
    1. extraction du texte (``ProjectDocumentAIService.extract_text`` — PDF, DOCX) ;
    2. document rattaché à un projet → proposition de structure pour ce projet
       (``ProjectAIStructureService``, texte transmis à l'IA) ; sinon → nouveau
       projet par Genesis (proposition à valider, ou appliquée si ``auto_apply``) ;
    3. revue / application dans l'aperçu de la proposition.
    Repli heuristique des services quand l'IA est désactivée.
    """

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    throttle_classes = [AIActionRateThrottle]

    def post(self, request, pk):
        from project.services.ai.services.project_genesis import ProjectGenesisService
        from project.services.ai.services.project_structure import ProjectAIStructureService
        from project.services.project_document_ai_service import ProjectDocumentAIService
        from project.views import ProjectDocumentImportDetailView

        obj = _legacy_object(request, ProjectDocumentImportDetailView, pk)
        if not user_can_access_workspace(request.user, obj.workspace):
            raise NotFound()
        if obj.project_id and obj.project.workspace_id not in get_user_workspace_ids(request.user):
            raise NotFound()
        if not _can_analyze(request.user, obj):
            raise PermissionDenied("Action non autorisée pour votre rôle.")
        if _analysis_running(obj):
            return _conflict("Une analyse est déjà en cours pour ce document.")

        Status = dm.ProjectDocumentImport.ImportStatus
        use_ai = _flag(request.data.get("use_ai"), True)
        auto_apply = _flag(request.data.get("auto_apply"), False)
        name = str(request.data.get("name") or "").strip()[:160]

        def fail(message, code=status.HTTP_400_BAD_REQUEST):
            obj.status = Status.FAILED
            obj.error_message = message
            obj.save(update_fields=["status", "error_message", "updated_at"])
            return Response({"detail": message}, status=code)

        obj.status = Status.PROCESSING
        obj.error_message = ""
        obj.save(update_fields=["status", "error_message", "updated_at"])

        try:
            text = (ProjectDocumentAIService.extract_text(obj.file) or "").strip()
        except Exception as exc:
            return fail(f"Extraction du texte impossible ({exc}). Formats pris en charge : PDF, Word (.docx).")
        if not text:
            return fail("Aucun texte exploitable n'a été trouvé dans ce document.")
        obj.extracted_text = text
        obj.save(update_fields=["extracted_text", "updated_at"])

        counts = {}
        try:
            if obj.project_id:
                result = ProjectAIStructureService.generate_for_project(
                    project=obj.project, triggered_by=request.user, use_ai=use_ai, document_text=text,
                )
                proposal, project, provider = result.proposal, obj.project, result.used_provider
            else:
                stem = PurePosixPath(obj.file.name).stem.replace("_", " ").replace("-", " ").strip()
                result = ProjectGenesisService.create_project_from_brief(
                    workspace=obj.workspace,
                    name=name or stem[:160] or "Projet importé",
                    description=text[:8000],
                    owner=request.user,
                    use_ai=use_ai,
                    auto_apply=auto_apply,
                )
                proposal, project, provider, counts = result.proposal, result.project, result.used_provider, result.counts
        except ValueError as exc:
            return fail(str(exc))
        except Exception as exc:
            logger.exception("Document import analysis failed for import %s", obj.pk)
            return fail(f"Analyse IA impossible : {exc}", status.HTTP_500_INTERNAL_SERVER_ERROR)

        obj.project = project
        obj.ai_payload = {
            "source": "devflow.ai.structure",
            "proposal_id": proposal.pk,
            "project_id": project.pk,
            "used_provider": provider,
            "summary": (proposal.summary or "")[:2000],
            "counts": counts,
            "structure": proposal.raw_payload or {},
        }
        obj.status = Status.COMPLETED
        obj.save(update_fields=["project", "ai_payload", "status", "updated_at"])
        return Response({
            "import_id": obj.pk,
            "project": {"id": project.pk, "name": project.name},
            "proposal": {"id": proposal.pk, "status": proposal.status, "status_label": proposal.get_status_display()},
            "applied": proposal.status == Proposal.Status.APPLIED,
            "used_provider": provider,
            "counts": counts,
        })
