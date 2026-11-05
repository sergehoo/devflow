"""
Pont formulaires Django → frontend React.

Exécute la vue Django existante (``dispatch`` complet : scoping workspace,
RBAC éventuel dans ``dispatch``, ``get_form_kwargs``, ``form_valid``…) et
renvoie du JSON :

* ``GET  /api/v1/forms/<nom>/[<pk>/]`` → description des champs (libellés,
  choix déjà filtrés par workspace, valeurs initiales) ;
* ``POST /api/v1/forms/<nom>/[<pk>/]`` (multipart) → enregistrement via la
  vue Django ; 400 avec les erreurs du formulaire, sinon ``{id, messages}``.

Aucune règle métier n'est dupliquée : la vue Django reste l'unique moteur.
CSRF : imposé par ``SessionAuthentication`` (DRF) sur le POST.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from django import forms
from django.contrib.messages import get_messages
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied as DjangoPermissionDenied
from django.db.models import Model
from django.db.models.fields.files import FieldFile
from django.http import Http404
from rest_framework import permissions, status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView


def _form_views():
    """Registre nom → (vue de création, vue de modification). Import tardif (views.py est lourd)."""
    from project import views as v

    from project.api.resources import resource_form_views

    return {
        **resource_form_views(),
        "project": (v.ProjectCreateView, v.ProjectUpdateView),
        "task": (v.TaskCreateView, v.TaskUpdateView),
        "timesheet-entry": (v.TimesheetEntryCreateView, v.TimesheetEntryUpdateView),
        "team": (v.TeamCreateView, v.TeamUpdateView),
        "member": (v.TeamMembershipCreateView, v.TeamMembershipUpdateView),
    }


def _action_views():
    """Registre des actions POST (vues Django à redirection + messages, ou JSON)."""
    from project import views as v
    from project import views_budget as vb

    return {
        "task-comment": v.TaskQuickCommentView,
        "task-attachment": v.TaskQuickAttachmentView,
        "task-flag": v.TaskToggleFlagView,
        "task-done": v.TaskMarkDoneView,
        "task-extend": v.TaskExtendView,
        "task-expire": v.TaskMarkExpiredView,
        "task-archive": v.TaskArchiveView,
        "task-delete": v.TaskDeleteView,
        "timesheet-cell": v.TimesheetCalendarSaveView,
        "timesheet-week": v.TimesheetWeekValidateView,
        "timesheet-entry-delete": v.TimesheetEntryDeleteView,
        "team-archive": v.TeamArchiveView,
        "team-delete": v.TeamDeleteView,
        "member-delete": v.TeamMembershipDeleteView,
        "member-password-reset": v.TeamMembershipPasswordResetView,
        # Budget projet (vues views_budget, paramètre d'URL ``project_id``)
        "project-generate-estimates": (vb.GenerateEstimateLinesFromTasksView, "project_id"),
        "project-recalculate-budget": (vb.RecalculateProjectBudgetView, "project_id"),
        "project-refresh-financials": (vb.RefreshProjectFinancialsView, "project_id"),
    }


def _widget_type(field: forms.Field) -> str:
    w = field.widget
    if isinstance(w, forms.HiddenInput):
        return "hidden"
    if isinstance(w, forms.CheckboxInput):
        return "checkbox"
    if isinstance(w, (forms.SelectMultiple, forms.CheckboxSelectMultiple)):
        return "multiselect"
    if isinstance(w, (forms.Select, forms.RadioSelect)):
        return "select"
    if isinstance(w, forms.Textarea):
        return "textarea"
    if isinstance(w, forms.ClearableFileInput) or isinstance(w, forms.FileInput):
        return "file"
    input_type = getattr(w, "input_type", None) or "text"
    if input_type == "text" and isinstance(field, (forms.IntegerField, forms.DecimalField, forms.FloatField)):
        return "number"
    if input_type == "text" and isinstance(field, forms.DateField):
        return "date"
    return input_type


def _json_value(value):
    if value is None:
        return None
    if isinstance(value, Model):
        return value.pk
    if isinstance(value, (list, tuple, set)):
        return [_json_value(v) for v in value]
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M")
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, FieldFile):
        return value.url if value else None
    if hasattr(value, "pk"):
        return value.pk
    return value if isinstance(value, (str, int, float, bool)) else str(value)


def _label(name: str, field) -> str:
    """Libellé du champ ; libellés générés automatiquement (anglais) → français si connu."""
    from project.api.resources import FR_LABELS

    label = str(field.label or name)
    auto = name.replace("_", " ")
    if label.lower() == auto.lower() and name in FR_LABELS:
        return FR_LABELS[name]
    return label


def describe_form(form) -> dict:
    sections = getattr(form, "field_sections", {}) or {}
    fields = []
    for name, field in form.fields.items():
        kind = _widget_type(field)
        item = {
            "name": name,
            "label": _label(name, field),
            "type": kind,
            "required": bool(field.required) and not field.disabled,
            "disabled": bool(field.disabled),
            "help_text": str(field.help_text or ""),
            "section": sections.get(name),
            "value": _json_value(form[name].value()),
            "max_length": getattr(field, "max_length", None),
            "min": getattr(field, "min_value", None),
            "max": getattr(field, "max_value", None),
        }
        if kind in ("select", "multiselect"):
            item["choices"] = [
                {"value": "" if value in (None, "") else str(getattr(value, "value", value)), "label": str(label)}
                for value, label in (getattr(field, "choices", None) or getattr(field.widget, "choices", []))
            ]
        for key in ("min", "max"):
            if isinstance(item[key], Decimal):
                item[key] = float(item[key])
        fields.append(item)
    return {"fields": fields}


def form_errors(form) -> dict:
    data = {k: [e["message"] for e in v] for k, v in form.errors.get_json_data().items()}
    if "__all__" in data:
        data["non_field_errors"] = data.pop("__all__")
    return data


class LegacyFormView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def _run(self, request, name, pk):
        views = _form_views().get(name)
        if not views:
            raise NotFound("Formulaire inconnu.")
        view_class = views[1] if pk else views[0]
        django_request = request._request
        django_request.user = request.user
        kwargs = {"pk": pk} if pk else {}
        view = view_class()
        view.setup(django_request, **kwargs)
        try:
            response = view.dispatch(django_request, **kwargs)
        except Http404:
            raise NotFound()
        except DjangoPermissionDenied as exc:
            raise PermissionDenied(str(exc) or None)
        return view, response

    def get(self, request, name, pk=None):
        _view, response = self._run(request, name, pk)
        form = (getattr(response, "context_data", None) or {}).get("form")
        if form is None:
            raise NotFound()
        if pk is None and not form.is_bound:
            # Préremplissage par paramètres GET (``?task=12``) quand la vue ne le fait pas.
            for key, value in request.query_params.items():
                if key in form.fields and form.initial.get(key) in (None, ""):
                    form.initial[key] = value
        return Response(describe_form(form))

    def post(self, request, name, pk=None):
        view, response = self._run(request, name, pk)
        notices = [str(m) for m in get_messages(request._request)]
        context = getattr(response, "context_data", None) or {}
        form = context.get("form")
        if response.status_code in (301, 302) and getattr(view, "object", None) is not None:
            return Response(
                {"id": view.object.pk, "messages": notices},
                status=status.HTTP_200_OK if pk else status.HTTP_201_CREATED,
            )
        if form is not None and form.errors:
            return Response(form_errors(form), status=status.HTTP_400_BAD_REQUEST)
        return Response({"detail": "Enregistrement impossible."}, status=status.HTTP_400_BAD_REQUEST)


class LegacyActionView(APIView):
    """
    ``POST /api/v1/actions/<nom>/[<pk>/]`` (multipart) — exécute la vue Django
    d'action existante. Réponse JSON de la vue : renvoyée telle quelle ;
    redirection : ``{messages}`` (200) ou ``{detail}`` (400) si la vue a émis
    une erreur ; 403/404 conservés.
    """

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, name, pk=None):
        entry = _action_views().get(name)
        if not entry:
            raise NotFound("Action inconnue.")
        view_class, kwarg = entry if isinstance(entry, tuple) else (entry, "pk")
        return run_action_view(request, view_class, {kwarg: pk} if pk else {})


def run_action_view(request, view_class, kwargs):
    """
    Exécute une vue Django d'action (POST) et traduit sa réponse en JSON :
    JSON de la vue renvoyé tel quel ; redirection → ``{messages}`` (200) ou
    ``{detail}`` (400) si la vue a émis une erreur ; 403/404 conservés.
    """
    import json

    from django.contrib import messages as dj_messages
    from django.http import JsonResponse

    django_request = request._request
    django_request.user = request.user
    if "next" not in django_request.POST:
        # Les vues d'action redirigent vers ``next`` (fourni par l'ancien frontend).
        post = django_request.POST.copy()
        post["next"] = "/"
        django_request.POST = post
    view = view_class()
    view.setup(django_request, **kwargs)
    try:
        response = view.dispatch(django_request, **kwargs)
    except (Http404, ObjectDoesNotExist):  # certaines vues font .get() sur un queryset scopé
        raise NotFound()
    except DjangoPermissionDenied as exc:
        raise PermissionDenied(str(exc) or None)
    if isinstance(response, JsonResponse):
        data = json.loads(response.content or b"{}")
        if response.status_code >= 400 and isinstance(data, dict) and "error" in data and "detail" not in data:
            data["detail"] = data["error"]
        return Response(data, status=response.status_code)
    notices = list(get_messages(django_request))
    errors = [str(m) for m in notices if m.level >= dj_messages.WARNING]
    if response.status_code == 403:
        raise PermissionDenied()
    if response.status_code in (301, 302) and not errors:
        return Response({"messages": [str(m) for m in notices]})
    return Response({"detail": " ".join(errors) or "Action impossible."}, status=status.HTTP_400_BAD_REQUEST)
