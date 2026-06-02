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
    Donne une URI exploitable par WeasyPrint pour le logo.

    Ordre de priorité (du plus fiable au plus fragile) :

      1. **data: URI base64** — on lit le fichier directement depuis le
         storage Django et on encode son contenu en base64. Aucune
         requête HTTP ni accès filesystem secondaire requis par
         WeasyPrint → c'est la méthode la plus fiable derrière un
         reverse-proxy, dans un conteneur Docker isolé, ou quand
         /media/ n'est pas joignable depuis le conteneur (DNS interne,
         SSL, etc.).
      2. **file://** local — si le storage est local et accessible
         depuis le process WeasyPrint, c'est la 2e option fiable.
      3. **URL absolue HTTP(S)** — fallback si le logo est sur un CDN
         externe et que les 2 premières ne marchent pas.

    Décision design : on privilégie data: pour ne PAS dépendre du
    réseau, ce qui rendait le logo invisible en prod (le conteneur
    Django n'arrivait pas à charger /media/ via HTTPS depuis sa propre
    instance).
    """
    if not workspace or not getattr(workspace, "logo", None):
        return ""

    # 1) Data URI base64 — méthode privilégiée
    try:
        import base64
        import mimetypes
        with workspace.logo.open("rb") as fh:
            data = fh.read()
        if data:
            name = getattr(workspace.logo, "name", "") or ""
            mime = mimetypes.guess_type(name)[0] or "image/png"
            encoded = base64.b64encode(data).decode("ascii")
            return f"data:{mime};base64,{encoded}"
    except Exception as exc:
        logger.warning(
            "Cannot encode workspace logo as data URI (%s): %s",
            getattr(workspace.logo, "name", "?"), exc,
        )

    # 2) file:// local
    try:
        return f"file://{workspace.logo.path}"
    except Exception:
        pass

    # 3) URL absolue HTTP
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
    return logo_url
