"""
Mise en forme commune des exports Excel tabulaires de DevFlow (openpyxl) :
bandeau titre + mention de génération, tableau avec en-têtes, filtres Excel,
ligne d'en-tête figée, cellules multilignes, statuts colorés, impression
paysage, onglet « Informations » (date, exporteur, périmètre, filtres).

Utilisé par les exports timesheets et tickets. Le classeur de suivi de la
Direction (``tracking_board``) garde sa mise en page historique propre.
"""

from __future__ import annotations

import io

GENERATED_MENTION = "Généré automatiquement depuis DevFlow"
EMPTY_MENTION = "Aucune donnée pour le périmètre et les filtres appliqués."
FONT = "Aptos Narrow"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
TONES = {  # fond, texte
    "success": ("C6EFCE", "006100"), "info": ("DDEBF7", "1F4E78"), "danger": ("FFC7CE", "9C0006"),
    "warning": ("FFEB9C", "9C5700"), "muted": ("F2F2F2", "404040"),
}


def name(user) -> str:
    return (user.get_full_name() or user.get_username()) if user else ""


class Styles:
    def __init__(self):
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

        thin = Side(style="thin", color="BFBFBF")
        self.border = Border(left=thin, right=thin, top=thin, bottom=thin)
        self.header_fill = PatternFill("solid", start_color="FFE699", end_color="FFE699")
        self.total_fill = PatternFill("solid", start_color="F2F2F2", end_color="F2F2F2")
        self.header_font = Font(name=FONT, size=11, bold=True)
        self.font = Font(name=FONT, size=11)
        self.bold = Font(name=FONT, size=11, bold=True)
        self.title = Font(name=FONT, size=16, bold=True)
        self.note = Font(name=FONT, size=10, italic=True, color="595959")
        self.wrap = Alignment(horizontal="left", vertical="top", wrap_text=True)
        self.center = Alignment(horizontal="center", vertical="center", wrap_text=True)
        self.right = Alignment(horizontal="right", vertical="top")

    def tone(self, cell, tone: str | None):
        from openpyxl.styles import Font, PatternFill

        if tone not in TONES:
            return
        fill, color = TONES[tone]
        cell.fill = PatternFill("solid", start_color=fill, end_color=fill)
        cell.font = Font(name=FONT, size=11, bold=True, color=color)


def table(ws, styles, top, headers, rows, *, widths=None, formats=None, tones=None, autofilter=True, empty=EMPTY_MENTION):
    """
    En-tête à la ligne ``top`` puis les lignes ; renvoie la ligne suivante.
    ``tones`` : ``{colonne: [ton par ligne]}`` (``success``, ``danger``…).
    """
    from openpyxl.utils import get_column_letter

    for col, label in enumerate(headers, start=1):
        cell = ws.cell(row=top, column=col, value=label)
        cell.font = styles.header_font
        cell.fill = styles.header_fill
        cell.alignment = styles.center
        cell.border = styles.border
        if widths:
            ws.column_dimensions[get_column_letter(col)].width = widths[col - 1]
    ws.row_dimensions[top].height = 30
    row_index = top + 1
    for index, values in enumerate(rows):
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=row_index, column=col, value=value)
            cell.font = styles.font
            cell.border = styles.border
            cell.alignment = styles.right if isinstance(value, (int, float)) and not isinstance(value, bool) else styles.wrap
            if formats and formats.get(col):
                cell.number_format = formats[col]
            if tones and col in tones:
                styles.tone(cell, tones[col][index])
        row_index += 1
    if not rows:
        ws.cell(row=row_index, column=1, value=empty).font = styles.note
        row_index += 1
    elif autofilter:
        ws.auto_filter.ref = f"A{top}:{get_column_letter(len(headers))}{row_index - 1}"
    return row_index


def page_setup(ws, header_row):
    """En-tête figé, paysage A4 ajusté en largeur, titres répétés, pied de page."""
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = f"{header_row}:{header_row}"
    ws.oddFooter.left.text = GENERATED_MENTION
    ws.oddFooter.right.text = "Page &P / &N"


def banner(ws, styles, title, lines, width):
    """Titre (ligne 1) et lignes d'information (ligne 2) fusionnés sur ``width`` colonnes."""
    from openpyxl.utils import get_column_letter

    last = get_column_letter(width)
    ws.merge_cells(f"A1:{last}1")
    ws["A1"] = title
    ws["A1"].font = styles.title
    ws.row_dimensions[1].height = 24
    ws.merge_cells(f"A2:{last}2")
    ws["A2"] = "\n".join(lines)
    ws["A2"].font = styles.note
    ws["A2"].alignment = styles.wrap
    ws.row_dimensions[2].height = 15 * max(1, len(lines)) + 4


def stamp(exporter, now) -> str:
    return f"{GENERATED_MENTION} — le {now:%d/%m/%Y} à {now:%H:%M} — exporté par {name(exporter) or 'DevFlow'}"


def info_sheet(wb, styles, *, exporter, workspace, now, scope, filter_lines, extra=()):
    info = wb.create_sheet("Informations")
    info.column_dimensions["A"].width = 26
    info.column_dimensions["B"].width = 100
    rows = (
        ("Origine", GENERATED_MENTION),
        ("Date de génération", f"{now:%d/%m/%Y %H:%M}"),
        ("Exporté par", name(exporter) or "DevFlow"),
        ("Espace de travail", getattr(workspace, "name", workspace) or "—"),
        ("Périmètre appliqué", scope),
        ("Filtres appliqués", "\n".join(filter_lines) if filter_lines else "aucun"),
        *extra,
    )
    for index, (label, value) in enumerate(rows, start=1):
        info.cell(row=index, column=1, value=label).font = styles.bold
        cell = info.cell(row=index, column=2, value=value)
        cell.font = styles.font
        cell.alignment = styles.wrap


def save(wb) -> bytes:
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def filename(prefix: str, *parts: str) -> str:
    from django.utils.text import slugify

    slug = "_".join(slugify(p).replace("-", "_") for p in parts if p)
    return f"{prefix}{('_' + slug) if slug else ''}.xlsx"


def response(content: bytes, file_name: str):
    from django.http import HttpResponse

    res = HttpResponse(content, content_type=XLSX_MIME)
    res["Content-Disposition"] = f'attachment; filename="{file_name}"'
    res["Cache-Control"] = "no-store"
    return res
