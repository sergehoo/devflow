"""
Droits de facturation (RBAC) — appliqués à TOUTES les vues de facturation
(historiques, AJAX et pont React). Lecture : ``billing.view`` ; écriture :
``invoice.edit`` (matrice RBAC : propriétaire du workspace ; le chef de projet
est en lecture seule, membre et client sans accès).

Avant ce garde, les vues ne filtraient que par workspace : un simple membre
pouvait créer, émettre, annuler une facture ou enregistrer un paiement.
"""

from __future__ import annotations

from functools import wraps

from django.core.exceptions import PermissionDenied

from project import models as dm

READ, WRITE = "billing.view", "invoice.edit"
DENIED = "Accès à la facturation non autorisé pour votre rôle."


def billing_allowed(user, action: str, workspace_id) -> bool:
    from project.services.rbac import RBACService

    if user.is_superuser:
        return True
    workspace = dm.Workspace.objects.filter(pk=workspace_id).only("id", "owner_id").first() if workspace_id else None
    return workspace is not None and RBACService.can(user, action, workspace=workspace)


def guard(view_cls, action, model=None, lookup: str = "pk", ws_field: str = "workspace_id"):
    """Enveloppe ``dispatch`` : workspace de l'objet (``lookup``) sinon workspace courant.
    ``action`` : droit, ou dictionnaire par méthode HTTP (``{"GET": READ, "*": WRITE}``)."""
    original = view_cls.dispatch

    @wraps(original)
    def dispatch(self, request, *args, **kwargs):
        user = request.user
        if user.is_authenticated and not user.is_superuser:
            ws_id = None
            key = kwargs.get(lookup)
            if model is not None and key is not None:
                ws_id = model.objects.filter(pk=key).values_list(ws_field, flat=True).first()
                if ws_id is None:  # objet absent : la vue renvoie son 404 habituel
                    return original(self, request, *args, **kwargs)
                from project.utils.workspaces import get_user_workspace_ids

                if ws_id not in set(get_user_workspace_ids(user)):  # autre tenant : 404, sans révéler l'existence
                    from django.http import Http404
                    raise Http404
            else:
                current = getattr(self, "get_current_workspace", None)
                ws = current() if current else None
                ws_id = getattr(ws, "pk", None)
            needed = action.get(request.method, action.get("*")) if isinstance(action, dict) else action
            if not billing_allowed(user, needed, ws_id):
                raise PermissionDenied(DENIED)
        return original(self, request, *args, **kwargs)

    view_cls.dispatch = dispatch
    return view_cls


def apply_guards() -> None:
    """Appelé une fois (AppConfig.ready) : protège les vues de facturation existantes."""
    from project import views as v
    from project import views_invoice_ajax as ax

    Inv, Cli, Line, Proj = dm.Invoice, dm.InvoiceClient, dm.InvoiceLine, dm.Project
    for cls in (v.InvoiceListView, v.InvoiceClientListView):
        guard(cls, READ)
    for cls in (v.InvoiceDetailView, v.InvoicePrintView, v.InvoicePDFView, v.InvoiceDocxView):
        guard(cls, READ, Inv)
    guard(v.InvoiceClientDetailView, READ, Cli)
    for cls in (v.InvoiceCreateView, v.InvoiceClientCreateView, v.InvoiceLineCreateView):
        guard(cls, WRITE)
    for cls in (v.InvoiceUpdateView, v.InvoiceDeleteView, v.InvoiceIssueView, v.InvoiceMarkSentView, v.InvoiceCancelView,
                v.InvoicePaymentCreateView):
        guard(cls, WRITE, Inv)
    for cls in (v.InvoiceClientUpdateView, v.InvoiceClientDeleteView):
        guard(cls, WRITE, Cli)
    for cls in (v.InvoiceLineUpdateView, v.InvoiceLineDeleteView):
        guard(cls, WRITE, Line, ws_field="invoice__workspace_id")
    guard(v.InvoiceGenerateFromProjectView, WRITE, Proj, lookup="project_pk")
    guard(ax.InvoiceLinesView, {"GET": READ, "*": WRITE}, Inv)
    for cls in (ax.InvoiceLinesReorderView, ax.InvoiceTotalsView):
        guard(cls, WRITE, Inv)
    guard(ax.InvoiceLineDetailView, WRITE, Line, ws_field="invoice__workspace_id")
