"""
DevFlow — Endpoints AJAX pour l'édition inline des InvoiceLine (PR-INV-AJAX).

Tous les endpoints :
  * GET/POST JSON
  * Filtrage workspace strict via get_user_workspace_ids
  * Vérification du statut de l'invoice (édition possible uniquement en DRAFT
    ou ISSUED selon l'action)
  * Recompute_totals automatique après chaque mutation
  * Renvoie le dict ``totals`` à jour pour mise à jour live de l'UI

URLs (à brancher dans urls.py) :

  POST   /billing/invoices/<pk>/lines.json       → créer une ligne
  GET    /billing/invoices/<pk>/lines.json       → liste lignes + totaux
  PATCH  /billing/lines/<pk>.json                → modifier (1+ champs)
  DELETE /billing/lines/<pk>.json                → supprimer
  POST   /billing/invoices/<pk>/lines/reorder.json → réordonner [id1, id2, ...]
  PATCH  /billing/invoices/<pk>/totals.json      → modifier tax_rate / discount
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal, InvalidOperation

from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_protect

from project import models as dm
from project.utils.workspaces import get_user_workspace_ids
from project.views import DevflowBaseMixin, WorkspaceSecurityMixin

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────
EDITABLE_STATUSES = {"DRAFT"}  # statuts où l'édition des lignes est permise
ALLOWED_LINE_TYPES = {c[0] for c in dm.InvoiceLine.LineType.choices}


def _serialize_line(line: dm.InvoiceLine) -> dict:
    return {
        "id": line.pk,
        "line_type": line.line_type,
        "line_type_display": line.get_line_type_display(),
        "label": line.label,
        "description": line.description,
        "quantity": str(line.quantity),
        "unit_price": str(line.unit_price),
        "total_amount": str(line.total_amount),
        "position": line.position,
    }


def _serialize_totals(invoice: dm.Invoice) -> dict:
    return {
        "subtotal_ht": str(invoice.subtotal_ht),
        "discount_amount": str(invoice.discount_amount or 0),
        "tax_rate": str(invoice.tax_rate),
        "tax_amount": str(invoice.tax_amount),
        "total_ttc": str(invoice.total_ttc),
        "paid_amount": str(invoice.paid_amount),
        "remaining_due": str((invoice.total_ttc or 0) - (invoice.paid_amount or 0)),
        "currency": invoice.currency,
        "status": invoice.status,
        "status_display": invoice.get_status_display(),
    }


def _to_decimal(val, default=Decimal("0")):
    if val is None or val == "":
        return default
    try:
        return Decimal(str(val))
    except (InvalidOperation, TypeError, ValueError):
        return default


def _get_invoice_for_user(request, invoice_pk):
    ws_ids = get_user_workspace_ids(request.user)
    invoice = (
        dm.Invoice.objects
        .filter(pk=invoice_pk, workspace_id__in=ws_ids)
        .first()
    )
    if invoice is None:
        raise Http404("Facture introuvable.")
    return invoice


def _get_line_for_user(request, line_pk):
    ws_ids = get_user_workspace_ids(request.user)
    line = (
        dm.InvoiceLine.objects
        .select_related("invoice")
        .filter(pk=line_pk, invoice__workspace_id__in=ws_ids)
        .first()
    )
    if line is None:
        raise Http404("Ligne introuvable.")
    return line


def _require_editable(invoice: dm.Invoice):
    if invoice.status not in EDITABLE_STATUSES:
        raise PermissionError(
            f"L'édition n'est possible qu'en statut Brouillon "
            f"(actuel : {invoice.get_status_display()})."
        )


def _parse_json_body(request) -> dict:
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return {}


# ────────────────────────────────────────────────────────────────────
# Vues
# ────────────────────────────────────────────────────────────────────
class InvoiceLinesView(WorkspaceSecurityMixin, DevflowBaseMixin, View):
    """GET (liste) + POST (créer) — /billing/invoices/<pk>/lines.json"""

    def get(self, request, pk):
        invoice = _get_invoice_for_user(request, pk)
        lines = invoice.lines.order_by("position", "id")
        return JsonResponse({
            "lines": [_serialize_line(l) for l in lines],
            "totals": _serialize_totals(invoice),
        })

    @method_decorator(csrf_protect)
    def post(self, request, pk):
        invoice = _get_invoice_for_user(request, pk)
        try:
            _require_editable(invoice)
        except PermissionError as exc:
            return JsonResponse({"error": str(exc)}, status=403)

        data = _parse_json_body(request)
        line_type = (data.get("line_type") or "SERVICE").upper()
        if line_type not in ALLOWED_LINE_TYPES:
            line_type = "SERVICE"

        # Position = max + 1
        last_pos = (
            invoice.lines.order_by("-position")
            .values_list("position", flat=True).first() or 0
        )

        line = dm.InvoiceLine.objects.create(
            invoice=invoice,
            line_type=line_type,
            label=(data.get("label") or "Nouvelle ligne")[:240],
            description=(data.get("description") or "")[:5000],
            quantity=_to_decimal(data.get("quantity"), Decimal("1")),
            unit_price=_to_decimal(data.get("unit_price"), Decimal("0")),
            position=last_pos + 1,
        )
        invoice.recompute_totals(save=True)
        invoice.refresh_from_db()
        return JsonResponse({
            "line": _serialize_line(line),
            "totals": _serialize_totals(invoice),
        }, status=201)


class InvoiceLineDetailView(WorkspaceSecurityMixin, DevflowBaseMixin, View):
    """PATCH (modifier) + DELETE (supprimer) — /billing/lines/<pk>.json"""

    @method_decorator(csrf_protect)
    def patch(self, request, pk):
        line = _get_line_for_user(request, pk)
        try:
            _require_editable(line.invoice)
        except PermissionError as exc:
            return JsonResponse({"error": str(exc)}, status=403)

        data = _parse_json_body(request)
        updates = []
        # Champs autorisés
        if "label" in data:
            line.label = (data["label"] or "")[:240]
            updates.append("label")
        if "description" in data:
            line.description = (data["description"] or "")[:5000]
            updates.append("description")
        if "line_type" in data:
            lt = (data["line_type"] or "").upper()
            if lt in ALLOWED_LINE_TYPES:
                line.line_type = lt
                updates.append("line_type")
        if "quantity" in data:
            line.quantity = _to_decimal(data["quantity"], line.quantity)
            updates.append("quantity")
        if "unit_price" in data:
            line.unit_price = _to_decimal(data["unit_price"], line.unit_price)
            updates.append("unit_price")
        if "position" in data:
            try:
                line.position = max(0, int(data["position"]))
                updates.append("position")
            except (TypeError, ValueError):
                pass

        if not updates:
            return JsonResponse({"error": "Aucun champ modifié."}, status=400)

        # save() recalcule total_amount automatiquement (cf. InvoiceLine.save)
        line.save()
        line.invoice.recompute_totals(save=True)
        line.invoice.refresh_from_db()
        return JsonResponse({
            "line": _serialize_line(line),
            "totals": _serialize_totals(line.invoice),
            "updated_fields": updates,
        })

    @method_decorator(csrf_protect)
    def delete(self, request, pk):
        line = _get_line_for_user(request, pk)
        try:
            _require_editable(line.invoice)
        except PermissionError as exc:
            return JsonResponse({"error": str(exc)}, status=403)
        invoice = line.invoice
        line.delete()
        invoice.recompute_totals(save=True)
        invoice.refresh_from_db()
        return JsonResponse({
            "deleted": pk,
            "totals": _serialize_totals(invoice),
        })


class InvoiceLinesReorderView(WorkspaceSecurityMixin, DevflowBaseMixin, View):
    """POST — /billing/invoices/<pk>/lines/reorder.json

    Body : { "order": [line_id, line_id, ...] }
    Positions assignées 1, 2, 3, ... dans l'ordre fourni.
    """

    @method_decorator(csrf_protect)
    def post(self, request, pk):
        invoice = _get_invoice_for_user(request, pk)
        try:
            _require_editable(invoice)
        except PermissionError as exc:
            return JsonResponse({"error": str(exc)}, status=403)

        data = _parse_json_body(request)
        ids = data.get("order") or []
        if not isinstance(ids, list):
            return JsonResponse({"error": "order doit être une liste."}, status=400)

        try:
            ids_int = [int(i) for i in ids]
        except (TypeError, ValueError):
            return JsonResponse({"error": "order contient des IDs invalides."}, status=400)

        # Filtre aux lignes qui appartiennent à cette invoice (sécurité)
        existing = {l.pk: l for l in invoice.lines.filter(pk__in=ids_int)}
        updated = 0
        for new_pos, pk_line in enumerate(ids_int, start=1):
            line = existing.get(pk_line)
            if line and line.position != new_pos:
                line.position = new_pos
                line.save(update_fields=["position", "updated_at"])
                updated += 1
        return JsonResponse({
            "updated": updated,
            "totals": _serialize_totals(invoice),
        })


class InvoiceTotalsView(WorkspaceSecurityMixin, DevflowBaseMixin, View):
    """PATCH — /billing/invoices/<pk>/totals.json

    Modifie ``tax_rate``, ``discount_amount`` ou ``currency`` au niveau facture.
    """

    @method_decorator(csrf_protect)
    def patch(self, request, pk):
        invoice = _get_invoice_for_user(request, pk)
        try:
            _require_editable(invoice)
        except PermissionError as exc:
            return JsonResponse({"error": str(exc)}, status=403)

        data = _parse_json_body(request)
        updates = []
        if "tax_rate" in data:
            rate = _to_decimal(data["tax_rate"], invoice.tax_rate)
            # Borne 0-100
            rate = max(Decimal("0"), min(Decimal("100"), rate))
            invoice.tax_rate = rate
            updates.append("tax_rate")
        if "discount_amount" in data:
            disc = _to_decimal(data["discount_amount"], Decimal("0"))
            invoice.discount_amount = max(Decimal("0"), disc)
            updates.append("discount_amount")
        if "currency" in data:
            invoice.currency = (data["currency"] or invoice.currency)[:10]
            updates.append("currency")
        if "notes" in data:
            invoice.notes = (data["notes"] or "")[:10000]
            updates.append("notes")
        if "title" in data:
            invoice.title = (data["title"] or "")[:240]
            updates.append("title")

        if not updates:
            return JsonResponse({"error": "Aucun champ modifié."}, status=400)

        # On sauvegarde puis on recalcule (recompute_totals fait son propre save)
        invoice.save(update_fields=updates + ["updated_at"])
        invoice.recompute_totals(save=True)
        invoice.refresh_from_db()
        return JsonResponse({
            "totals": _serialize_totals(invoice),
            "updated_fields": updates,
        })
