"""
Pont « ressources » : modules CRUD de l'ancienne interface servis en JSON au
frontend React, en exécutant les vues Django existantes.

* ``GET  /api/v1/resources/``                         → registre (navigation, capacités)
* ``GET  /api/v1/resources/<nom>/``                   → ListView Django (recherche ``q``, filtres GET, pagination)
* ``GET  /api/v1/resources/<nom>/<pk>/``              → DetailView Django (champs + actions + exports)
* ``POST /api/v1/resources/<nom>/<pk>/delete/``       → DeleteView Django
* ``POST /api/v1/resources/<nom>/<pk>/actions/<a>/``  → vue d'action Django (archiver, émettre, relancer…)
* formulaires : ``/api/v1/forms/<nom>/[<pk>/]`` (``form_bridge``), alimenté par ce registre.

Aucune règle n'est dupliquée : chaque appel passe par ``dispatch`` (scoping
workspace, RBAC, droits objet, ``form_valid``). Seules les ressources
déclarées ci-dessous sont exposées.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from functools import lru_cache

from django.core.exceptions import ObjectDoesNotExist, PermissionDenied as DjangoPermissionDenied
from django.db import models
from django.http import Http404
from django.urls import NoReverseMatch, resolve, reverse
from rest_framework import permissions
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView


@dataclass(frozen=True)
class Resource:
    base: str                       # préfixe des noms d'URL Django (``<base>_list`` …)
    title: str
    singular: str
    group: str
    permission: str = ""            # filtre d'affichage (ex. "billing.view") — Django reste l'autorité
    superuser: bool = False
    columns: tuple[str, ...] = ()   # colonnes de liste (défaut : champs du formulaire)
    actions: tuple[tuple[str, str, str], ...] = ()      # (code, libellé, nom d'URL) — POST
    downloads: tuple[tuple[str, str], ...] = ()         # (libellé, nom d'URL) — GET (fichier)


ARCHIVE = lambda base: ("archive", "Archiver", f"{base}_archive")  # noqa: E731

RESOURCES: dict[str, Resource] = {
    # ── Projets ──────────────────────────────────────────────────────────
    "roadmap": Resource("roadmap", "Roadmaps", "Roadmap", "Projets", actions=(ARCHIVE("roadmap"),)),
    "roadmap-item": Resource("roadmap_item", "Éléments de roadmap", "Élément de roadmap", "Projets"),
    "milestone": Resource("milestone", "Jalons", "Jalon", "Projets", actions=(ARCHIVE("milestone"),)),
    "milestone-task": Resource("milestone_task", "Tâches de jalon", "Tâche de jalon", "Projets"),
    "release": Resource("release", "Releases", "Release", "Projets", actions=(ARCHIVE("release"),)),
    "objective": Resource("objective", "Objectifs & OKR", "Objectif", "Projets", actions=(ARCHIVE("objective"),)),
    "key-result": Resource("key_result", "Résultats clés", "Résultat clé", "Projets"),
    "risk": Resource("risk", "Risques", "Risque", "Projets", actions=(ARCHIVE("risk"),)),
    "project-member": Resource("project_member", "Membres projet", "Membre projet", "Projets"),
    "project-label": Resource("project_label", "Labels de projets", "Label de projet", "Projets"),
    "project-import": Resource("project_document_import", "Imports documentaires", "Import documentaire", "Projets"),
    "ai-insight": Resource("ai_insight", "Analyses & suggestions IA", "Analyse IA", "Projets",
                           actions=(("dismiss", "Ignorer", "ai_insight_dismiss"),)),
    "ai-proposal": Resource("ai_proposal", "Propositions IA", "Proposition IA", "Projets"),
    # ── Exécution ────────────────────────────────────────────────────────
    "backlog-item": Resource("backlog_item", "Backlog", "Élément de backlog", "Exécution",
                             actions=(ARCHIVE("backlog_item"),)),
    "sprint": Resource("sprint", "Sprints", "Sprint", "Exécution", actions=(ARCHIVE("sprint"),)),
    "sprint-review": Resource("sprint_review", "Revues de sprint", "Revue de sprint", "Exécution"),
    "sprint-retrospective": Resource("sprint_retrospective", "Rétrospectives", "Rétrospective", "Exécution"),
    "sprint-metric": Resource("sprint_metric", "Métriques de sprint", "Métrique de sprint", "Exécution"),
    "board-column": Resource("board_column", "Colonnes de board", "Colonne de board", "Exécution"),
    "pull-request": Resource("pull_request", "Pull requests", "Pull request", "Exécution"),
    "task-checklist": Resource("task_checklist", "Checklists", "Checklist", "Exécution"),
    "checklist-item": Resource("checklist_item", "Éléments de checklist", "Élément de checklist", "Exécution"),
    "task-dependency": Resource("task_dependency", "Dépendances de tâches", "Dépendance", "Exécution"),
    "task-label": Resource("task_label", "Labels de tâches", "Label de tâche", "Exécution"),
    "task-assignment": Resource("task_assignment", "Affectations", "Affectation", "Exécution"),
    # ── Finance ──────────────────────────────────────────────────────────
    "project-budget": Resource("project_budget", "Budgets projet", "Budget projet", "Finance", permission="budget.view"),
    "estimate-line": Resource("project_estimate_line", "Lignes d'estimation", "Ligne d'estimation", "Finance",
                              permission="budget.view"),
    "project-revenue": Resource("project_revenue", "Revenus projet", "Revenu projet", "Finance", permission="budget.view"),
    "project-expense": Resource("project_expense", "Dépenses", "Dépense", "Finance", permission="budget.view",
                                actions=(("approve-level1", "Valider (niveau 1)", "project_expense_approve_level1"),
                                         ("approve-level2", "Valider (niveau 2)", "project_expense_approve_level2"),
                                         ("reject", "Rejeter", "project_expense_reject"))),
    "invoice": Resource("invoice", "Factures", "Facture", "Finance", permission="billing.view",
                        actions=(("issue", "Émettre", "invoice_issue"), ("mark-sent", "Marquer envoyée", "invoice_mark_sent"),
                                 ("cancel", "Annuler la facture", "invoice_cancel")),
                        downloads=(("PDF", "invoice_pdf"), ("Word", "invoice_docx"), ("Impression", "invoice_print"))),
    "invoice-client": Resource("invoice_client", "Clients", "Client", "Finance", permission="billing.view"),
    # ── Réunions ─────────────────────────────────────────────────────────
    "meeting": Resource("meeting", "Réunions", "Réunion", "Réunions",
                        actions=(("send-minutes", "Envoyer le compte rendu", "meeting_send_minutes"),),
                        downloads=(("Compte rendu PDF", "meeting_minutes_pdf"), ("Compte rendu Word", "meeting_minutes_docx"))),
    "meeting-series": Resource("meeting_series", "Séries récurrentes", "Série récurrente", "Réunions",
                               actions=(("regenerate", "Régénérer les occurrences", "meeting_series_regenerate"),)),
    "meeting-decision": Resource("meeting_decisions", "Registre des décisions", "Décision", "Réunions"),
    # ── Paramètres ───────────────────────────────────────────────────────
    "workspace-settings": Resource("workspace_settings", "Paramètres du workspace", "Paramètres", "Paramètres",
                                   permission="settings.manage"),
    "workspace-invitation": Resource("workspace_invitation", "Invitations", "Invitation", "Paramètres",
                                     permission="members.invite",
                                     actions=(("resend", "Renvoyer", "workspace_invitation_resend"),
                                              ("revoke", "Révoquer", "workspace_invitation_revoke"))),
    "label": Resource("label", "Labels", "Label", "Paramètres"),
    "integration": Resource("integration", "Intégrations", "Intégration", "Paramètres", permission="integration.manage"),
    "webhook": Resource("webhook", "Webhooks", "Webhook", "Paramètres", permission="webhook.manage"),
    "api-key": Resource("api_key", "Clés API", "Clé API", "Paramètres", permission="integration.manage"),
    "methodology": Resource("methodology_admin", "Méthodologies", "Méthodologie", "Paramètres", superuser=True),
    "activity-log": Resource("activity_log", "Journal d'activité", "Activité", "Paramètres"),
}

# Les filtres de liste (``?project=``, ``?status=``…) sont lus par les ListView
# Django elles-mêmes : la requête GET leur est transmise telle quelle.

# Liens React des modèles déjà migrés par des écrans dédiés.
CORE_ROUTES = {"Project": "/projects/{}", "Task": "/tasks/{}", "Team": "/teams/{}", "Workspace": "/workspaces/{}"}
SENSITIVE = re.compile(r"(secret|token|hash|password|^key$|api_key|signing)", re.I)
SKIPPED_COLUMN_TYPES = (models.TextField, models.JSONField, models.FileField, models.ManyToManyField)


def _view_class(url_name: str, **kwargs):
    try:
        match = resolve(reverse(url_name, kwargs=kwargs or None))
    except NoReverseMatch:
        return None
    return getattr(match.func, "view_class", None)


@lru_cache(maxsize=None)
def _views(name: str) -> dict:
    res = RESOURCES[name]
    return {
        "list": _view_class(f"{res.base}_list"),
        "detail": _view_class(f"{res.base}_detail", pk=0),
        "create": _view_class(f"{res.base}_create"),
        "update": _view_class(f"{res.base}_update", pk=0),
        "delete": _view_class(f"{res.base}_delete", pk=0),
    }


def resource_form_views() -> dict:
    """Formulaires exposés au pont ``forms/`` : (création, modification) des ressources."""
    out = {}
    for name in RESOURCES:
        v = _views(name)
        if v["create"] or v["update"]:
            out[name] = (v["create"], v["update"])
    return out


@lru_cache(maxsize=None)
def _model_resource() -> dict:
    out = {}
    for name in RESOURCES:
        view = _views(name)["list"] or _views(name)["detail"]
        model = getattr(view, "model", None)
        if model is not None and _views(name)["detail"]:
            out.setdefault(model, name)
    return out


def _link(obj) -> str | None:
    if obj is None:
        return None
    model = type(obj)
    if model.__name__ in CORE_ROUTES and model._meta.app_label == "project":
        return CORE_ROUTES[model.__name__].format(obj.pk)
    name = _model_resource().get(model)
    return f"/m/{name}/{obj.pk}" if name else None


def _scalar(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _cell(obj, f):
    """Valeur affichable d'un champ : libellé de choix, lien de relation, URL de fichier."""
    if f.many_to_many:
        manager = getattr(obj, f.name, None)
        items = list(manager.all()[:20]) if manager is not None else []
        return {"kind": "list", "items": [{"label": str(i), "link": _link(i)} for i in items]}
    if f.is_relation:
        related = getattr(obj, f.name, None)
        return None if related is None else {"kind": "ref", "label": str(related), "link": _link(related)}
    if isinstance(f, models.FileField):
        file = getattr(obj, f.name)
        return {"kind": "file", "label": file.name.rsplit("/", 1)[-1], "url": file.url} if file else None
    if f.choices:
        raw = getattr(obj, f.name)
        return {"kind": "choice", "value": raw, "label": str(getattr(obj, f"get_{f.name}_display")())}
    if isinstance(f, models.JSONField):
        return None
    return _scalar(getattr(obj, f.name))


def _field(model, name):
    try:
        return model._meta.get_field(name)
    except Exception:
        return None


def _displayable(f) -> bool:
    return (
        f is not None and getattr(f, "concrete", False) or getattr(f, "many_to_many", False)
    ) and not SENSITIVE.search(f.name) and f.name != "id"


@lru_cache(maxsize=None)
def _columns(name: str, model) -> tuple[str, ...]:
    res = RESOURCES[name]
    if res.columns:
        return res.columns
    form_class = getattr(_views(name)["create"] or _views(name)["update"], "form_class", None)
    candidates = list(getattr(getattr(form_class, "_meta", None), "fields", None) or [f.name for f in model._meta.fields])
    cols = []
    for n in candidates:
        f = _field(model, n)
        if not _displayable(f) or n == "workspace" or isinstance(f, SKIPPED_COLUMN_TYPES):
            continue
        cols.append(n)
        if len(cols) == 5:
            break
    return tuple(cols)


FR_LABELS = {
    "created_at": "Créé le", "updated_at": "Modifié le", "name": "Nom", "title": "Titre", "status": "Statut",
    "project": "Projet", "team": "Équipe", "workspace": "Workspace", "owner": "Responsable", "user": "Utilisateur",
    "description": "Description", "start_date": "Début", "end_date": "Fin", "due_date": "Échéance",
    "priority": "Priorité", "severity": "Gravité", "probability": "Probabilité", "is_archived": "Archivé",
    "archived_at": "Archivé le", "number": "Numéro", "goal": "Objectif", "task": "Tâche", "email": "Email",
    "role": "Rôle", "amount": "Montant", "currency": "Devise", "notes": "Notes", "type": "Type", "date": "Date",
    "label": "Label", "color": "Couleur", "position": "Position", "is_active": "Actif", "created_by": "Créé par",
    "assignee": "Assigné à", "author": "Auteur", "body": "Contenu", "url": "Lien", "sprint": "Sprint",
    "milestone": "Jalon", "roadmap": "Roadmap", "objective": "Objectif", "progress_percent": "Avancement (%)",
    "client": "Client", "invoice": "Facture", "issue_date": "Date d'émission", "total": "Total", "phone": "Téléphone",
    "address": "Adresse", "meeting": "Réunion", "scheduled_at": "Planifiée le", "location": "Lieu",
    "from_task": "Tâche dépendante", "to_task": "Tâche requise", "dependency_type": "Type de dépendance",
    "checklist": "Checklist", "text": "Texte", "is_checked": "Coché", "checked_by": "Coché par",
    "added_by": "Ajouté par", "assigned_by": "Affecté par", "allocation_percent": "Allocation (%)",
    "uploaded_by": "Déposé par", "file": "Fichier", "invited_by": "Invité par", "expires_at": "Expire le",
    "accepted_at": "Acceptée le", "code": "Code", "category": "Catégorie", "value": "Valeur",
    "target_value": "Cible", "current_value": "Valeur actuelle", "impact_score": "Score d'impact",
    "mitigation_plan": "Plan de mitigation", "escalated_at": "Escaladé le", "actor": "Auteur",
    "activity_type": "Type d'activité", "version": "Version", "release_date": "Date de release",
    "workspace": "Workspace", "rank": "Rang", "story_points": "Points", "item_type": "Type", "parent": "Parent",
    "reporter": "Rapporteur", "acceptance_criteria": "Critères d'acceptation", "is_internal": "Interne",
    "edited_at": "Modifié le", "name_fr": "Nom", "unit": "Unité", "quantity": "Quantité", "unit_price": "Prix unitaire",
    "payment_date": "Date de paiement", "reference": "Référence", "method": "Méthode", "expense_date": "Date de dépense",
    "approved_budget": "Budget validé", "approved_by": "Validé par", "approved_at": "Validé le", "comment": "Commentaire",
    "event": "Événement", "events": "Événements", "secret": "Secret", "is_enabled": "Activé", "provider": "Fournisseur",
    "summary": "Résumé", "content": "Contenu", "decision": "Décision", "decided_at": "Décidé le", "recurrence": "Récurrence",
    "duration_minutes": "Durée (min)", "agenda": "Ordre du jour", "minutes": "Compte rendu", "participants": "Participants",
    "attendees": "Participants", "severity_score": "Score de gravité", "confidence": "Confiance", "insight_type": "Type d'analyse",
    "recommendation": "Recommandation", "score": "Score", "phase": "Phase", "estimate_hours": "Estimation (h)",
    "spent_hours": "Temps passé (h)", "risk_score": "Score de risque", "started_at": "Démarré le", "completed_at": "Terminé le",
    "is_flagged": "Signalée", "backlog_item": "Élément de backlog", "token": "Jeton", "language": "Langue",
}


def _label(model, name) -> str:
    f = _field(model, name)
    verbose = str(getattr(f, "verbose_name", name))
    if verbose == name.replace("_", " ") and name in FR_LABELS:
        return FR_LABELS[name]
    return verbose[:1].upper() + verbose[1:]


def _run(view_class, request, kwargs):
    """Exécute la vue Django (dispatch complet) ; erreurs Django → erreurs DRF."""
    if view_class is None:
        raise NotFound()
    django_request = request._request
    django_request.user = request.user
    view = view_class()
    view.setup(django_request, **kwargs)
    from project.api.form_bridge import new_messages, stale_message_count

    stale = stale_message_count(django_request)
    try:
        response = view.dispatch(django_request, **kwargs)
    except (Http404, ObjectDoesNotExist):
        raise NotFound()
    except DjangoPermissionDenied as exc:
        raise PermissionDenied(str(exc) or None)
    if response.status_code == 403:
        raise PermissionDenied()
    if response.status_code in (301, 302):
        # Les vues refusent souvent par message + redirection.
        detail = " ".join(str(m) for m in new_messages(django_request, stale)) or "Accès non autorisé."
        raise PermissionDenied(detail)
    return view, getattr(response, "context_data", None) or {}


def _resource(name: str) -> Resource:
    if name not in RESOURCES:
        raise NotFound("Module inconnu.")
    return RESOURCES[name]


def _urls(name, url_names, pk):
    out = []
    for label, url_name in url_names:
        try:
            out.append({"label": label, "href": reverse(url_name, kwargs={"pk": pk})})
        except NoReverseMatch:
            continue
    return out


class ResourceRegistryView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        items = []
        for name, res in RESOURCES.items():
            v = _views(name)
            if not v["list"]:
                continue
            items.append({
                "name": name, "title": res.title, "singular": res.singular, "group": res.group,
                "permission": res.permission, "superuser": res.superuser,
                "legacy_list": reverse(f"{res.base}_list"),
                "can_create": bool(v["create"]), "has_detail": bool(v["detail"]),
                "can_update": bool(v["update"]), "can_delete": bool(v["delete"]),
            })
        return Response({"resources": items})


class ResourceListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, name):
        _resource(name)
        view, ctx = _run(_views(name)["list"], request, {})
        object_list = ctx.get("object_list")
        model = getattr(view, "model", None) or getattr(object_list, "model", None)
        page = ctx.get("page_obj")
        objects = list(object_list or [])
        if model is None:
            model = type(objects[0]) if objects else None
        cols = _columns(name, model) if model is not None else ()
        return Response({
            "columns": [{"name": c, "label": _label(model, c)} for c in cols],
            "results": [
                {"id": o.pk, "label": str(o), "link": _link(o),
                 "cells": {c: _cell(o, _field(model, c)) for c in cols}}
                for o in objects
            ],
            "count": page.paginator.count if page else len(objects),
            "page": page.number if page else 1,
            "num_pages": page.paginator.num_pages if page else 1,
        })


class ResourceDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, name, pk):
        res = _resource(name)
        view, ctx = _run(_views(name)["detail"], request, {"pk": pk})
        obj = ctx.get("object") or getattr(view, "object", None)
        if obj is None:
            raise NotFound()
        model = type(obj)
        fields = [f for f in model._meta.get_fields() if _displayable(f) and not f.auto_created]
        actions = [
            {"code": code, "label": label}
            for code, label, url_name in res.actions
            if _view_class(url_name, pk=pk) is not None
        ]
        return Response({
            "id": obj.pk, "label": str(obj),
            "fields": [{"name": f.name, "label": _label(model, f.name), "value": _cell(obj, f)} for f in fields],
            "actions": actions,
            "downloads": _urls(name, res.downloads, pk),
            "legacy_url": reverse(f"{res.base}_detail", kwargs={"pk": pk}),
        })


class ResourceDeleteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, name, pk):
        from project.api.form_bridge import run_action_view

        _resource(name)
        view_class = _views(name)["delete"]
        if view_class is None:
            raise NotFound()
        return run_action_view(request, view_class, {"pk": pk})


class ResourceActionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, name, pk, action):
        from project.api.form_bridge import run_action_view

        res = _resource(name)
        url_name = next((u for code, _l, u in res.actions if code == action), None)
        view_class = _view_class(url_name, pk=pk) if url_name else None
        if view_class is None:
            raise NotFound("Action inconnue.")
        return run_action_view(request, view_class, {"pk": pk})


__all__ = [
    "RESOURCES", "ResourceRegistryView", "ResourceListView", "ResourceDetailView",
    "ResourceDeleteView", "ResourceActionView", "resource_form_views",
]
