"""
Finance (frontend React) : cockpit financier du portefeuille, allocation IA,
éditeur de facture (lignes, totaux, paiements). Aucune règle nouvelle : les
vues Django existantes sont exécutées (droits RBAC ``budget.view`` /
``billing.view`` / ``invoice.edit`` appliqués par elles et par
``services.billing_permissions``).
"""

from __future__ import annotations

import json
from decimal import Decimal

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404, JsonResponse
from rest_framework import permissions
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from project import models as dm
from project.api.form_bridge import describe_form, run_action_view
from project.api.throttles import AIActionRateThrottle
from project.utils.workspaces import get_user_workspace_ids


def _num(v):
    return float(v) if isinstance(v, Decimal) else v


def _workspace(request) -> dm.Workspace:
    ws_id = request.query_params.get("workspace")
    if not ws_id:
        from project.views import DashboardView

        view = DashboardView()
        view.setup(request._request)
        ws = view.get_current_workspace()
        if ws is None:
            raise NotFound("Aucun workspace.")
        return ws
    if not str(ws_id).isdigit() or int(ws_id) not in set(get_user_workspace_ids(request.user)):
        raise NotFound()
    return dm.Workspace.objects.get(pk=ws_id)


def _delegate(view_cls, request, **kwargs):
    """Exécute une vue Django renvoyant du JSON et relaie sa réponse."""
    django_request = request._request
    django_request.user = request.user
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.content_type.startswith("application/json"):
        # La vérification CSRF de DRF a déjà lu le flux : la vue historique relit ``request.body``.
        django_request._body = json.dumps(request.data if isinstance(request.data, dict) else {}).encode()
    try:
        response = view_cls.as_view()(django_request, **kwargs)
    except Http404:
        raise NotFound()
    except DjangoPermissionDenied as exc:
        raise PermissionDenied(str(exc) or None)
    if response.status_code == 403:
        raise PermissionDenied()
    data = json.loads(response.content or b"{}") if isinstance(response, JsonResponse) else {}
    if isinstance(data, dict) and "error" in data and "detail" not in data:
        data["detail"] = data["error"]
    return Response(data, status=response.status_code)


class FinancePortfolioView(APIView):
    """GET /api/v1/finance/portfolio/?workspace= — cockpit financier (ProjectBudgetService)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from project.views_financial_ai import WorkspaceFinancialPortfolioView

        ws = _workspace(request)
        view = WorkspaceFinancialPortfolioView()
        django_request = request._request
        django_request.user = request.user
        view.setup(django_request, workspace_id=ws.pk)
        response = view.dispatch(django_request, workspace_id=ws.pk)
        if response.status_code != 200:
            raise PermissionDenied("Accès aux données financières non autorisé.")
        p = response.context_data["portfolio"]
        rows = [{
            **{k: _num(v) for k, v in row.items() if k != "project"},
            "project": {"id": row["project"].pk, "name": row["project"].name, "status_label": row["project"].get_status_display()},
        } for row in p["rows"]]
        return Response({
            "workspace": {"id": ws.pk, "name": ws.name}, "rows": rows,
            "totals": {k: _num(v) for k, v in p["totals"].items()},
            "totals_real_margin": _num(p["totals_real_margin"]), "totals_forecast_margin": _num(p["totals_forecast_margin"]),
            "totals_consumption_percent": p["totals_consumption_percent"],
        })


class FinanceAllocationView(APIView):
    """GET /api/v1/finance/allocation/?workspace= — recommandations d'allocation (IA, repli heuristique)."""

    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [AIActionRateThrottle]

    def get(self, request):
        from project.views_financial_ai import WorkspaceAllocationAdviceView

        ws = _workspace(request)
        return _delegate(WorkspaceAllocationAdviceView, request, workspace_id=ws.pk)


class InvoiceLinesAPI(APIView):
    """GET / POST /api/v1/invoices/<pk>/lines/ (vue AJAX historique)."""

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser]

    def get(self, request, pk):
        from project.views_invoice_ajax import InvoiceLinesView

        return _delegate(InvoiceLinesView, request, pk=pk)

    post = get


class InvoiceLineAPI(APIView):
    """PATCH / DELETE /api/v1/invoice-lines/<pk>/."""

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser]

    def patch(self, request, pk):
        from project.views_invoice_ajax import InvoiceLineDetailView

        return _delegate(InvoiceLineDetailView, request, pk=pk)

    delete = patch


class InvoiceReorderAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser]

    def post(self, request, pk):
        from project.views_invoice_ajax import InvoiceLinesReorderView

        return _delegate(InvoiceLinesReorderView, request, pk=pk)


class InvoiceTotalsAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser]

    def patch(self, request, pk):
        from project.views_invoice_ajax import InvoiceTotalsView

        return _delegate(InvoiceTotalsView, request, pk=pk)


class InvoicePaymentsAPI(APIView):
    """GET : paiements + formulaire (InvoicePaymentForm) ; POST : InvoicePaymentCreateView."""

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def _invoice(self, request, pk):
        from project.services.billing_permissions import READ, billing_allowed

        invoice = dm.Invoice.objects.filter(pk=pk, workspace_id__in=get_user_workspace_ids(request.user)).first()
        if invoice is None:
            raise NotFound()
        if not billing_allowed(request.user, READ, invoice.workspace_id):
            raise PermissionDenied("Accès à la facturation non autorisé pour votre rôle.")
        return invoice

    def get(self, request, pk):
        from project.forms import InvoicePaymentForm
        from project.services.billing_permissions import WRITE, billing_allowed

        invoice = self._invoice(request, pk)
        return Response({
            "payments": [{"id": p.pk, "amount": _num(p.amount), "received_at": p.received_at, "method": p.get_method_display(),
                          "reference": p.reference, "status": p.get_status_display()} for p in invoice.payments.order_by("-received_at", "-pk")],
            "can_edit": billing_allowed(request.user, WRITE, invoice.workspace_id),
            "form": describe_form(InvoicePaymentForm(current_workspace=invoice.workspace)),
        })

    def post(self, request, pk):
        from project.views import InvoicePaymentCreateView

        self._invoice(request, pk)
        return run_action_view(request, InvoicePaymentCreateView, {"pk": pk})
