"""
Service de génération de PDF facture avec papier en-tête du workspace.
Utilise WeasyPrint pour produire un PDF A4 prêt à envoyer au client.
"""

from __future__ import annotations

import io
import logging

from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def render_invoice_pdf(invoice, *, request=None) -> bytes:
    """
    Rend une facture en PDF (bytes) avec le papier en-tête du workspace.

    Le template `invoice/pdf.html` reçoit :
      - invoice (avec lines, payments)
      - workspace (papier en-tête)
      - logo_uri (URI absolu du logo, ou data: si non joignable)
    """
    from weasyprint import HTML, CSS

    workspace = invoice.workspace
    logo_uri = _resolve_logo_uri(workspace, request=request)

    context = {
        "invoice": invoice,
        "workspace": workspace,
        "logo_uri": logo_uri,
        "lines": invoice.lines.all().order_by("position", "id"),
        "payments": invoice.payments.all().order_by("-received_at"),
        "client": invoice.client,
        "project": invoice.project,
    }

    html_str = render_to_string("project/invoice/pdf.html", context)
    base_url = request.build_absolute_uri("/") if request else None

    pdf_io = io.BytesIO()
    HTML(string=html_str, base_url=base_url).write_pdf(target=pdf_io)
    return pdf_io.getvalue()


def _resolve_logo_uri(workspace, *, request=None) -> str:
    """
    Donne une URL absolue exploitable par WeasyPrint pour le logo.
    Priorité : MEDIA_URL absolu > URL absolue construite via request > path local.
    """
    if not workspace or not getattr(workspace, "logo", None):
        return ""
    try:
        logo_url = workspace.logo.url
    except Exception:
        return ""

    if logo_url.startswith(("http://", "https://", "data:")):
        return logo_url
    if request is not None:
        try:
            return request.build_absolute_uri(logo_url)
        except Exception:
            pass
    # WeasyPrint accepte aussi un chemin local file://
    try:
        return f"file://{workspace.logo.path}"
    except Exception:
        return logo_url
