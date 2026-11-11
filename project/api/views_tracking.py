"""
Chantier « pilotage » — Suivi Pôle Développement (frontend React).

* ``tracking/board/`` : vue consolidée (lignes, indicateurs, graphiques, filtres) ;
* ``tracking/export/`` : export Excel « Direction » et rapports PDF, mêmes filtres ;
* ``tracking/brief/`` : synthèse factuelle (GET) ou reformulée par l'IA (POST) ;
* ``tracking/projects/<id>/`` : synthèse d'un projet (fiche projet) ;
* ``tracking/imports/…`` : assistant d'import du classeur de suivi.

Sécurité : le périmètre vient exclusivement de ``tracking_board.board_scope``
(RBAC côté serveur) ; la vue, les indicateurs et les exports partent des mêmes
lignes, on ne peut donc pas exporter plus que ce que l'on voit. L'import exige
``project.create`` dans l'espace de travail visé ; un import d'un autre espace
répond 404.
"""

from __future__ import annotations

from django.core.paginator import Paginator
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from project import models as dm
from project.api.throttles import AIActionRateThrottle
from project.services import tracking_board as board
from project.services import tracking_import as importer
from project.services.rbac import rbac_workspace_ids
from project.utils.workspaces import get_user_workspace_ids, user_can_access_workspace, users_in_workspaces

IMPORT_RIGHT = "project.create"
MAX_ITEMS = 40  # éléments par cellule renvoyés à l'écran (le total reste indiqué)


def _digits(raw) -> bool:
    raw = str(raw or "")
    return bool(raw) and raw.isascii() and raw.isdigit() and len(raw) <= 12


def _name(user) -> str:
    return (user.get_full_name() or user.get_username()) if user else ""


def _scope(request) -> dict:
    scope = board.board_scope(request.user)
    if not scope["full"] and not scope["assigned"]:
        raise PermissionDenied("Le suivi n'est pas accessible avec votre rôle.")
    return scope


def _filters(request) -> dict:
    try:
        return board.parse_filters(request.query_params)
    except board.TrackingFilterError as exc:
        raise ValidationError({"detail": str(exc)}) from exc


def _row(row) -> dict:
    """Ligne pour l'écran : listes bornées, totaux conservés."""
    path = f"/projects/{row['pk']}" if row["kind"] == "project" else f"/tasks/{row['pk']}"
    return {
        **row,
        "done": row["done"][-MAX_ITEMS:], "done_count": len(row["done"]),
        "next": row["next"][:MAX_ITEMS], "next_count": len(row["next"]),
        "url": path,
    }


def _import_workspaces(user) -> list[int]:
    return rbac_workspace_ids(user, IMPORT_RIGHT)


class TrackingBoardView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        scope = _scope(request)
        filters = _filters(request)
        rows = board.build_rows(scope, request.user)
        visible = board.apply_filters(rows, filters)
        return Response({
            "rows": [_row(r) for r in visible],
            "count": len(visible), "total": len(rows),
            **board.summarize(visible),
            "options": board.filter_options(rows),
            "filters": board.describe_filters(filters, rows),
            "scope": {"label": board.scope_label(scope), "restricted": bool(scope["assigned"])},
            "can_import": bool(_import_workspaces(request.user)),
            "generated_at": timezone.now().isoformat(),
        })


class TrackingExportView(APIView):
    """``?fmt=xlsx`` (défaut) ou ``?fmt=pdf&variant=direction|weekly|monthly``, avec les filtres de l'écran."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        scope = _scope(request)
        filters = _filters(request)
        fmt = request.query_params.get("fmt") or "xlsx"
        variant = request.query_params.get("variant") or "direction"
        if fmt not in ("xlsx", "pdf") or variant not in board.REPORTS:
            raise ValidationError({"detail": "Format d'export inconnu."})
        rows = board.build_rows(scope, request.user)
        context = {
            "user": request.user, "scope_text": board.scope_label(scope),
            "filter_lines": board.describe_filters(filters, rows),
        }
        rows = board.apply_filters(rows, filters)
        stamp = timezone.localdate().isoformat()
        if fmt == "xlsx":
            content = board.export_xlsx(rows, **context)
            name = f"Suivi_Pole_Developpement_{stamp}.xlsx"
            mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            content = board.export_pdf(rows, variant=variant, **context)
            name = f"Suivi_Pole_Developpement_{variant}_{stamp}.pdf"
            mime = "application/pdf"
        response = HttpResponse(content, content_type=mime)
        response["Content-Disposition"] = f'attachment; filename="{name}"'
        response["Cache-Control"] = "no-store"
        return response


class TrackingBriefView(APIView):
    """Synthèse de pilotage sur les lignes visibles. POST : reformulation par l'IA DevFlow."""

    permission_classes = [permissions.IsAuthenticated]

    def get_throttles(self):
        return [AIActionRateThrottle()] if self.request.method == "POST" else []

    def _brief(self, request):
        scope = _scope(request)
        rows = board.apply_filters(board.build_rows(scope, request.user), _filters(request))
        return board.build_brief(rows)

    def get(self, request):
        return Response(self._brief(request))

    def post(self, request):
        if not rbac_workspace_ids(request.user, "ai.summarize"):
            raise PermissionDenied("Synthèse IA non autorisée pour votre rôle.")
        return Response(board.rewrite_brief_with_ai(self._brief(request)))


class TrackingProjectView(APIView):
    """Synthèse d'un projet : vue consolidée des tâches, risques, décisions et du journal existants."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        scope = board.board_scope(request.user)
        project = board.visible_project(scope, request.user, pk)
        if project is None:
            raise NotFound()
        rows = board.build_rows(scope, request.user, project_id=project.pk)
        row = next((r for r in rows if r["kind"] == "project"), None)
        activity = (dm.ActivityLog.objects.filter(project=project).select_related("actor")
                    .order_by("-created_at")[:8])
        return Response({
            "row": _row(row) if row else None,
            "activities": [_row(r) for r in rows if r["kind"] == "task"],
            "recent": [{"id": a.pk, "title": a.title, "actor": _name(a.actor),
                        "type": a.get_activity_type_display(), "created_at": a.created_at.isoformat()}
                       for a in activity],
        })


# ---------------------------------------------------------------------------
# Assistant d'import
# ---------------------------------------------------------------------------
def _state(payload) -> str:
    if payload.get("applied_at") and not payload.get("rolled_back_at"):
        return "applied"
    if payload.get("rolled_back_at"):
        return "rolled_back"
    return "analyzed" if payload.get("analysis") else "uploaded"


def _import_summary(obj) -> dict:
    payload = obj.ai_payload or {}
    return {
        "id": obj.pk,
        "file_name": obj.file.name.rsplit("/", 1)[-1] if obj.file else "",
        "workspace": {"id": obj.workspace_id, "name": obj.workspace.name},
        "uploaded_by": _name(obj.uploaded_by),
        "created_at": obj.created_at.isoformat(),
        "state": _state(payload),
        "stats": (payload.get("analysis") or {}).get("stats") or {},
        "applied_at": payload.get("applied_at"), "applied_by": payload.get("applied_by"),
        "rolled_back_at": payload.get("rolled_back_at"), "rolled_back_by": payload.get("rolled_back_by"),
    }


def _get_import(request, pk):
    """Import de suivi d'un espace de l'utilisateur (404 sinon), droit d'import requis (403)."""
    obj = (dm.ProjectDocumentImport.objects.select_related("workspace", "uploaded_by")
           .filter(pk=pk, workspace_id__in=get_user_workspace_ids(request.user)).first())
    if obj is None or (obj.ai_payload or {}).get("kind") != importer.KIND:
        raise NotFound()
    if obj.workspace_id not in _import_workspaces(request.user):
        raise PermissionDenied("Import réservé aux rôles autorisés.")
    return obj


def _import_detail(obj) -> dict:
    payload = obj.ai_payload or {}
    workspace = obj.workspace
    container = importer.container_project(workspace)
    return {
        **_import_summary(obj),
        "analysis": payload.get("analysis"),
        "decisions": payload.get("decisions"),
        "report": payload.get("report"),
        "rollback": payload.get("rollback"),
        "options": {
            "users": sorted(({"id": u.pk, "name": _name(u)} for u in users_in_workspaces([workspace.pk])),
                            key=lambda u: u["name"].lower()),
            "projects": [{"id": pk, "name": name, "container": bool(container and pk == container.pk)}
                         for pk, name in dm.Project.objects.filter(workspace=workspace, is_archived=False)
                         .order_by("name").values_list("id", "name")],
            "labels": [{"id": pk, "name": name, "kind": kind} for pk, name, kind in
                       dm.Label.objects.filter(workspace=workspace).order_by("name").values_list("id", "name", "kind")],
            "project_statuses": [{"value": v, "label": str(label)} for v, label in dm.Project.Status.choices],
            "task_statuses": [{"value": v, "label": str(label)} for v, label in dm.Task.Status.choices],
            "alert_kinds": [{"value": k, "label": importer.ALERT_LABELS[k]} for k in importer.ALERT_KINDS],
            "severities": [{"value": v, "label": str(label)} for v, label in dm.Risk.Severity.choices],
        },
    }


class TrackingImportListView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        allowed = _import_workspaces(request.user)
        if not allowed:
            raise PermissionDenied("Import réservé aux rôles autorisés.")
        imports = (dm.ProjectDocumentImport.objects.select_related("workspace", "uploaded_by")
                   .filter(workspace_id__in=allowed, ai_payload__kind=importer.KIND).order_by("-id")[:30])
        return Response({
            "results": [_import_summary(o) for o in imports],
            "workspaces": [{"id": pk, "name": name} for pk, name in
                           dm.Workspace.objects.filter(id__in=allowed).order_by("name").values_list("id", "name")],
        })

    def post(self, request):
        raw = request.data.get("workspace")
        if not _digits(raw):
            raise ValidationError({"workspace": "Espace de travail requis."})
        workspace = dm.Workspace.objects.filter(pk=int(raw)).first()
        if not user_can_access_workspace(request.user, workspace):
            raise NotFound()
        if workspace.pk not in _import_workspaces(request.user):
            raise PermissionDenied("Import réservé aux rôles autorisés.")
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": "Fichier requis."})
        if not upload.name.lower().endswith(".xlsx"):
            raise ValidationError({"file": "Un classeur Excel (.xlsx) est attendu."})
        if upload.size > importer.MAX_FILE_BYTES:
            raise ValidationError({"file": "Fichier trop volumineux (10 Mo maximum)."})
        obj = dm.ProjectDocumentImport.objects.create(
            workspace=workspace, uploaded_by=request.user, file=upload, ai_payload={"kind": importer.KIND})
        try:
            analysis = importer.analyze(obj)
        except importer.TrackingImportError as exc:
            obj.file.delete(save=False)
            obj.delete()
            raise ValidationError({"file": str(exc)}) from exc
        obj.ai_payload = {"kind": importer.KIND, "analysis": analysis}
        obj.save(update_fields=["ai_payload", "updated_at"])
        return Response(_import_detail(obj), status=status.HTTP_201_CREATED)


class TrackingImportDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        return Response(_import_detail(_get_import(request, pk)))


class TrackingImportActionView(APIView):
    """``analyze`` (relance l'analyse), ``apply`` (décisions de l'assistant), ``rollback`` (annulation logique)."""

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser]
    action = ""

    def post(self, request, pk):
        _get_import(request, pk)
        try:
            with transaction.atomic():
                obj = (dm.ProjectDocumentImport.objects.select_for_update()
                       .select_related("workspace", "uploaded_by").get(pk=pk))
                payload = obj.ai_payload or {}
                if self.action == "analyze":
                    if _state(payload) == "applied":
                        raise importer.TrackingImportError("Import déjà appliqué : annulez-le avant de le réanalyser.")
                    payload["analysis"] = importer.analyze(obj)
                    payload.pop("decisions", None)
                    obj.ai_payload = payload
                    obj.save(update_fields=["ai_payload", "updated_at"])
                elif self.action == "apply":
                    decisions = request.data.get("decisions") if isinstance(request.data, dict) else None
                    if decisions is not None and not isinstance(decisions, dict):
                        raise importer.TrackingImportError("Décisions invalides.")
                    importer.apply_import(obj, decisions or {}, request.user)
                else:
                    importer.rollback_import(obj, request.user)
        except importer.TrackingImportError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(_import_detail(obj))


class TrackingImportRecordsView(APIView):
    """Journal d'audit : chaque donnée du fichier, sa ligne d'origine et ce qu'elle est devenue."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        obj = _get_import(request, pk)
        raw = request.query_params.get("page") or "1"
        if not _digits(raw):
            raise ValidationError({"page": "Page invalide."})
        page = Paginator(obj.records.order_by("id"), 100).get_page(int(raw))
        return Response({
            "count": page.paginator.count, "page": page.number, "num_pages": page.paginator.num_pages,
            "results": [{
                "id": r.pk, "section": r.section, "row": r.row_number, "field": r.field, "index": r.item_index,
                "text": r.original_text[:600], "action": r.action, "action_label": r.get_action_display(),
                "target_model": r.target_model, "target_id": r.target_id,
                "rolled_back": r.rolled_back_at is not None,
            } for r in page.object_list],
        })


class TrackingImportTaskSearchView(APIView):
    """Recherche d'une tâche existante à laquelle rattacher une action à venir."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        obj = _get_import(request, pk)
        query = (request.query_params.get("q") or "").strip()[:80]
        if len(query) < 2:
            return Response({"results": []})
        tasks = (dm.Task.objects.filter(workspace=obj.workspace, is_archived=False, title__icontains=query)
                 .select_related("project").order_by("-id")[:20])
        return Response({"results": [{"id": t.pk, "title": t.title, "project": t.project.name} for t in tasks]})
