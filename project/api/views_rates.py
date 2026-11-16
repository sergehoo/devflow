"""
Écran « TJM des collaborateurs » (Finance) :

* ``GET  finance/rates/?workspace=<id>``                → collaborateurs, TJM en vigueur, historique ;
* ``POST finance/rates/?workspace=<id>``                → nouvelle période tarifaire (+ revalorisation) ;
* ``PATCH  finance/rates/<pk>/?workspace=<id>``         → corriger un tarif (+ revalorisation) ;
* ``DELETE finance/rates/<pk>/?workspace=<id>[&revalue=1]`` → archiver un tarif.

Lecture : ``billing.view`` dans l'espace ; écriture : ``billing.manage`` (mêmes droits que
l'API ``billing-rates``). Les collaborateurs et projets visés doivent appartenir à l'espace.
"""
from __future__ import annotations

from rest_framework import permissions, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from project import models as dm
from project.services import billing_rates as svc
from project.services.rbac import RBACService
from project.utils.workspaces import get_user_workspace_ids


def _workspace(request) -> dm.Workspace:
    raw = str(request.query_params.get("workspace") or "").strip()
    if not (raw.isascii() and raw.isdigit() and len(raw) <= 12):
        raise ValidationError({"workspace": "Espace de travail requis."})
    if int(raw) not in set(get_user_workspace_ids(request.user)):
        raise NotFound()
    return dm.Workspace.objects.get(pk=int(raw))


def _require(request, workspace, action):
    if not RBACService.can(request.user, action, workspace=workspace):
        raise PermissionDenied("Accès réservé aux personnes autorisées à gérer les tarifs."
                               if action == "billing.manage" else "Accès réservé à la consultation des tarifs.")


def _rate(workspace, pk) -> dm.BillingRate:
    members, rates = svc.workspace_rates(workspace, rate_ids=[pk])
    rate = rates.first()
    if rate is None:
        raise NotFound()
    return rate


def _payload(request) -> dict:
    if not isinstance(request.data, dict):
        raise ValidationError({"detail": "Objet JSON attendu."})
    return dict(request.data.items())


def _wants_revalue(request, payload=None) -> bool:
    flag = (payload or {}).get("revalue")
    if flag is None:
        flag = request.query_params.get("revalue")
    return str(flag).lower() in ("1", "true", "on", "yes")


def _revalue(workspace, rate, *, since, until):
    """Revalorise les saisies du collaborateur sur la plage touchée (son projet seulement pour un tarif projet)."""
    return svc.revalue(workspace, [rate.user_id], since, until, project_id=rate.project_id)


def _error(exc: svc.RateError):
    return ValidationError({exc.field or "detail": str(exc)})


class RatesView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        workspace = _workspace(request)
        _require(request, workspace, "billing.view")
        data = svc.board(workspace)
        data["can_manage"] = RBACService.can(request.user, "billing.manage", workspace=workspace)
        return Response(data)

    def post(self, request):
        workspace = _workspace(request)
        _require(request, workspace, "billing.manage")
        payload = _payload(request)
        try:
            rate = svc.save_rate(workspace, payload)
        except svc.RateError as exc:
            raise _error(exc) from exc
        revalued = _revalue(workspace, rate, since=rate.valid_from, until=rate.valid_to) \
            if _wants_revalue(request, payload) else None
        return Response({"id": rate.pk, "revalued": revalued}, status=status.HTTP_201_CREATED)


class RateDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, pk):
        workspace = _workspace(request)
        _require(request, workspace, "billing.manage")
        rate = _rate(workspace, pk)
        payload = _payload(request)
        old_start, old_end = rate.valid_from, rate.valid_to
        try:
            rate = svc.save_rate(workspace, {**_current(rate), **payload}, rate=rate)
        except svc.RateError as exc:
            raise _error(exc) from exc
        revalued = None
        if _wants_revalue(request, payload):
            # Toute la plage touchée : ancienne et nouvelle période (la voisine reprend ce qui sort).
            ends = (old_end, rate.valid_to)
            revalued = _revalue(workspace, rate, since=min(old_start, rate.valid_from),
                                until=None if None in ends else max(ends))
        return Response({"id": rate.pk, "revalued": revalued})

    def delete(self, request, pk):
        workspace = _workspace(request)
        _require(request, workspace, "billing.manage")
        rate = _rate(workspace, pk)
        svc.archive_rate(rate)
        revalued = _revalue(workspace, rate, since=rate.valid_from, until=rate.valid_to) \
            if _wants_revalue(request) else None
        return Response({"archived": rate.pk, "revalued": revalued})


def _current(rate) -> dict:
    return {
        "worker_level": rate.worker_level, "unit": rate.unit, "currency": rate.currency,
        "cost_rate_amount": rate.cost_rate_amount, "sale_rate_amount": rate.sale_rate_amount,
        "valid_from": rate.valid_from.isoformat(), "valid_to": rate.valid_to.isoformat() if rate.valid_to else None,
        "project": rate.project_id,
    }

