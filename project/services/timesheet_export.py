"""
Export Excel des timesheets (openpyxl, déjà utilisé par DevFlow).

* ``entries_workbook`` : saisies filtrées de l'historique → feuilles « Synthèse »
  (par collaborateur), « Feuilles de temps » (une ligne par collaborateur et par
  semaine, statut et dernière action de validation), « Saisies » (détail) et
  « Informations » (date, exporteur, périmètre, filtres).
* ``week_workbook`` : la feuille de temps hebdomadaire d'un collaborateur, telle
  qu'affichée dans DevFlow (tâches / activités × jours), avec son historique de
  validation, le détail des saisies et les informations d'export.

Les données reçues sont déjà limitées au périmètre de l'utilisateur par les vues :
ce module ne fait que les mettre en forme.
"""

from __future__ import annotations

import io
from collections import defaultdict
from datetime import date, timedelta

from django.utils import timezone

from project import models as dm

GENERATED_MENTION = "Généré automatiquement depuis DevFlow"
EMPTY_MENTION = "Aucune saisie pour le périmètre et les filtres appliqués."
SCOPE_TEXT = "vos saisies et celles de vos collaborateurs (N-1, N-2…)"
FONT = "Aptos Narrow"
WEEKDAYS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
# Libellés de l'interface (Brouillon / Soumise / Validée / Rejetée), pas ceux du modèle (« Approuvé »…).
STATUS_LABELS = {"DRAFT": "Brouillon", "SUBMITTED": "Soumise", "APPROVED": "Validée", "REJECTED": "Rejetée"}
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _name(user) -> str:
    return (user.get_full_name() or user.get_username()) if user else ""


def _hours(value) -> float:
    return float(value or 0)


def week_label(monday: date) -> str:
    return f"S{monday.isocalendar()[1]:02d} {monday.isocalendar()[0]}"


def log_text(log) -> str:
    """« Validée par Léa le 06/10/2026 à 10:00 — commentaire »."""
    if log is None:
        return ""
    when = timezone.localtime(log.created_at)
    text = f"{log.get_action_display()} par {_name(log.actor) or '—'} le {when:%d/%m/%Y à %H:%M}"
    comment = (getattr(log, "comment", "") or "").strip()
    return f"{text} — {comment}" if comment else text


def last_logs(workspace, pairs) -> dict:
    """Dernière action de validation par (collaborateur, lundi), en une requête."""
    pairs = set(pairs)
    if not pairs or workspace is None:
        return {}
    logs = (
        dm.TimesheetApprovalLog.objects
        .filter(workspace=workspace, employee_id__in={u for u, _ in pairs}, week_start__in={m for _, m in pairs})
        .select_related("actor").order_by("-created_at")
    )
    found = {}
    for log in logs:
        found.setdefault((log.employee_id, log.week_start), log)
    return found


def consolidated(statuses) -> str:
    from project.services.timesheet_workflow import consolidated_status

    return consolidated_status(statuses)


# ---------------------------------------------------------------------------
# Mise en forme commune
# ---------------------------------------------------------------------------
class _Styles:
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
        self.status_fills = {
            dm.TimesheetEntry.ApprovalStatus.APPROVED: ("C6EFCE", "006100"),
            dm.TimesheetEntry.ApprovalStatus.SUBMITTED: ("DDEBF7", "1F4E78"),
            dm.TimesheetEntry.ApprovalStatus.REJECTED: ("FFC7CE", "9C0006"),
            dm.TimesheetEntry.ApprovalStatus.DRAFT: ("F2F2F2", "404040"),
        }

    def status(self, cell, status):
        from openpyxl.styles import Font, PatternFill

        fill, color = self.status_fills.get(status, ("FFFFFF", "000000"))
        cell.fill = PatternFill("solid", start_color=fill, end_color=fill)
        cell.font = Font(name=FONT, size=11, bold=True, color=color)


def _table(ws, styles, top, headers, rows, *, widths=None, formats=None, status_col=None, statuses=None, autofilter=True):
    """En-tête + lignes à partir de la ligne ``top`` ; renvoie la ligne suivante."""
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
            if status_col == col and statuses is not None:
                styles.status(cell, statuses[index])
        row_index += 1
    if not rows:
        ws.cell(row=row_index, column=1, value=EMPTY_MENTION).font = styles.note
        row_index += 1
    elif autofilter:
        ws.auto_filter.ref = f"A{top}:{get_column_letter(len(headers))}{row_index - 1}"
    return row_index


def _page_setup(ws, header_row):
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = f"{header_row}:{header_row}"
    ws.oddFooter.left.text = GENERATED_MENTION
    ws.oddFooter.right.text = "Page &P / &N"


def _info_sheet(wb, styles, *, exporter, workspace, now, filter_lines, extra=()):
    info = wb.create_sheet("Informations")
    info.column_dimensions["A"].width = 26
    info.column_dimensions["B"].width = 100
    rows = (
        ("Origine", GENERATED_MENTION),
        ("Date de génération", f"{now:%d/%m/%Y %H:%M}"),
        ("Exporté par", _name(exporter) or "DevFlow"),
        ("Espace de travail", workspace.name if workspace else "—"),
        ("Périmètre appliqué", SCOPE_TEXT),
        ("Filtres appliqués", "\n".join(filter_lines) if filter_lines else "aucun"),
        *extra,
    )
    for index, (label, value) in enumerate(rows, start=1):
        info.cell(row=index, column=1, value=label).font = styles.bold
        cell = info.cell(row=index, column=2, value=value)
        cell.font = styles.font
        cell.alignment = styles.wrap


def _banner(ws, styles, title, lines, width):
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


def _save(wb) -> bytes:
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _entry_values(e) -> list:
    monday = e.entry_date - timedelta(days=e.entry_date.weekday())
    return [
        e.entry_date, week_label(monday), _name(e.user), e.project.name if e.project_id else "",
        e.task.title if e.task_id else "", e.description or "", _hours(e.hours),
        "Oui" if e.is_billable else "Non", STATUS_LABELS.get(e.approval_status, e.approval_status),
    ]


ENTRY_HEADERS = ["Date", "Semaine", "Collaborateur", "Projet", "Tâche", "Description", "Heures", "Facturable", "Statut"]
ENTRY_WIDTHS = [12, 11, 24, 28, 36, 50, 9, 11, 13]


# ---------------------------------------------------------------------------
# Historique filtré
# ---------------------------------------------------------------------------
def entries_workbook(entries, *, exporter, workspace, filter_lines, now=None) -> bytes:
    from openpyxl import Workbook

    now = timezone.localtime(now or timezone.now())
    styles = _Styles()
    entries = list(entries)
    stamp = f"{GENERATED_MENTION} — le {now:%d/%m/%Y} à {now:%H:%M} — exporté par {_name(exporter) or 'DevFlow'}"
    filters_text = f"Filtres : {' · '.join(filter_lines) if filter_lines else 'aucun'}"

    weeks = {}
    people = {}
    for e in entries:
        monday = e.entry_date - timedelta(days=e.entry_date.weekday())
        week = weeks.setdefault((e.user_id, monday), {
            "user": e.user, "monday": monday, "hours": 0.0, "billable": 0.0, "count": 0, "statuses": set(),
        })
        week["hours"] += _hours(e.hours)
        week["billable"] += _hours(e.hours) if e.is_billable else 0.0
        week["count"] += 1
        week["statuses"].add(e.approval_status)
        person = people.setdefault(e.user_id, {"user": e.user, "hours": 0.0, "billable": 0.0, "weeks": set(), "projects": set()})
        person["hours"] += _hours(e.hours)
        person["billable"] += _hours(e.hours) if e.is_billable else 0.0
        person["weeks"].add(monday)
        if e.project_id:
            person["projects"].add(e.project.name)
    logs = last_logs(workspace, weeks.keys())

    wb = Workbook()
    summary = wb.active
    summary.title = "Synthèse"
    week_status = {key: consolidated(w["statuses"]) for key, w in weeks.items()}
    status_counts = defaultdict(lambda: defaultdict(int))
    for (user_id, _), status in week_status.items():
        status_counts[user_id][status] += 1
    people_rows = sorted(people.values(), key=lambda p: _name(p["user"]).lower())
    _banner(summary, styles, "Timesheets — synthèse par collaborateur", [stamp, filters_text], 9)
    end = _table(
        summary, styles, 4,
        ["Collaborateur", "Heures", "Facturables", "Non facturables", "% facturable", "Semaines", "Validées", "En attente / brouillon", "Projets"],
        [[
            _name(p["user"]), round(p["hours"], 2), round(p["billable"], 2), round(p["hours"] - p["billable"], 2),
            (p["billable"] / p["hours"]) if p["hours"] else 0, len(p["weeks"]),
            status_counts[p["user"].pk][dm.TimesheetEntry.ApprovalStatus.APPROVED],
            len(p["weeks"]) - status_counts[p["user"].pk][dm.TimesheetEntry.ApprovalStatus.APPROVED],
            ", ".join(sorted(p["projects"])),
        ] for p in people_rows],
        widths=[28, 10, 12, 15, 12, 11, 10, 20, 60], formats={2: "0.00", 3: "0.00", 4: "0.00", 5: "0%"},
    )
    if people_rows:
        total = sum(p["hours"] for p in people_rows)
        billable = sum(p["billable"] for p in people_rows)
        for col, value in enumerate(["Total", round(total, 2), round(billable, 2), round(total - billable, 2),
                                     (billable / total) if total else 0, len({m for _, m in weeks})], start=1):
            cell = summary.cell(row=end, column=col, value=value)
            cell.font = styles.bold
            cell.fill = styles.total_fill
            cell.border = styles.border
            cell.number_format = {2: "0.00", 3: "0.00", 4: "0.00", 5: "0%"}.get(col, "General")
    _page_setup(summary, 4)

    sheets = wb.create_sheet("Feuilles de temps")
    week_rows = sorted(weeks.values(), key=lambda w: (-w["monday"].toordinal(), _name(w["user"]).lower()))
    _banner(sheets, styles, "Feuilles de temps hebdomadaires", [stamp, filters_text], 10)
    _table(
        sheets, styles, 4,
        ["Collaborateur", "Semaine", "Du", "Au", "Heures", "Facturables", "Non facturables", "Saisies", "Statut", "Dernière action"],
        [[
            _name(w["user"]), week_label(w["monday"]), w["monday"], w["monday"] + timedelta(days=6),
            round(w["hours"], 2), round(w["billable"], 2), round(w["hours"] - w["billable"], 2), w["count"],
            STATUS_LABELS.get(week_status[(w["user"].pk, w["monday"])], "—"),
            log_text(logs.get((w["user"].pk, w["monday"]))),
        ] for w in week_rows],
        widths=[28, 11, 12, 12, 9, 12, 15, 9, 13, 60],
        formats={3: "DD/MM/YYYY", 4: "DD/MM/YYYY", 5: "0.00", 6: "0.00", 7: "0.00"},
        status_col=9, statuses=[week_status[(w["user"].pk, w["monday"])] for w in week_rows],
    )
    _page_setup(sheets, 4)

    detail = wb.create_sheet("Saisies")
    _banner(detail, styles, "Détail des saisies", [stamp, filters_text], len(ENTRY_HEADERS))
    _table(detail, styles, 4, ENTRY_HEADERS, [_entry_values(e) for e in entries], widths=ENTRY_WIDTHS,
           formats={1: "DD/MM/YYYY", 7: "0.00"}, status_col=9, statuses=[e.approval_status for e in entries])
    _page_setup(detail, 4)

    _info_sheet(wb, styles, exporter=exporter, workspace=workspace, now=now, filter_lines=filter_lines, extra=(
        ("Collaborateurs", len(people)), ("Feuilles hebdomadaires", len(weeks)), ("Saisies", len(entries)),
        ("Heures", round(sum(_hours(e.hours) for e in entries), 2)),
    ))
    return _save(wb)


# ---------------------------------------------------------------------------
# Feuille de temps d'une semaine
# ---------------------------------------------------------------------------
def week_workbook(*, employee, workspace, monday, entries, summary, history, exporter, now=None) -> bytes:
    from openpyxl import Workbook

    now = timezone.localtime(now or timezone.now())
    styles = _Styles()
    entries = list(entries)
    days = [monday + timedelta(days=i) for i in range(7)]
    grid: dict[tuple, dict] = {}
    for e in entries:
        key = ("task", e.task_id) if e.task_id else ("activity", e.project_id, (e.description or "Activité").strip().lower())
        row = grid.setdefault(key, {
            "project": e.project.name if e.project_id else "",
            "label": e.task.title if e.task_id else (e.description or "Activité").strip(),
            "kind": "Tâche" if e.task_id else "Activité",
            "cells": defaultdict(float),
        })
        row["cells"][e.entry_date] += _hours(e.hours)
    rows = sorted(grid.values(), key=lambda r: (r["project"].lower(), r["label"].lower()))
    day_totals = {d: sum(r["cells"].get(d, 0.0) for r in rows) for d in days}
    total = sum(day_totals.values())

    wb = Workbook()
    ws = wb.active
    ws.title = f"Semaine {week_label(monday)}"[:31]
    width = 4 + len(days)
    status_label = STATUS_LABELS.get(summary.status, "Aucune saisie") if summary else "Aucune saisie"
    lines = [
        f"Semaine {monday.isocalendar()[1]} · du {monday:%d/%m/%Y} au {days[-1]:%d/%m/%Y} — statut : {status_label}",
        log_text(history[0]) if history else "Aucune action de validation enregistrée.",
    ]
    if summary:
        lines.append(
            f"Saisi : {_hours(summary.total_hours):g} h · attendu : {_hours(summary.expected):g} h · "
            f"capacité : {_hours(summary.capacity):g} h · complétion : {summary.completion_percent} %"
        )
    lines.append(f"{GENERATED_MENTION} — le {now:%d/%m/%Y} à {now:%H:%M} — exporté par {_name(exporter) or 'DevFlow'}")
    _banner(ws, styles, f"Feuille de temps — {_name(employee)}", lines, width)
    headers = ["Projet", "Tâche / activité", "Type", *[f"{WEEKDAYS[i]} {d:%d/%m}" for i, d in enumerate(days)], "Total"]
    end = _table(
        ws, styles, 4, headers,
        [[r["project"], r["label"], r["kind"], *[round(r["cells"].get(d, 0.0), 2) or None for d in days],
          round(sum(r["cells"].values()), 2)] for r in rows],
        widths=[28, 44, 10, *([10] * len(days)), 10], formats={col: "0.00" for col in range(4, width + 1)},
        autofilter=False,
    )
    if rows:
        for col, value in enumerate(["Total jour", "", "", *[round(day_totals[d], 2) for d in days], round(total, 2)], start=1):
            cell = ws.cell(row=end, column=col, value=value)
            cell.font = styles.bold
            cell.fill = styles.total_fill
            cell.border = styles.border
            if col >= 4:
                cell.number_format = "0.00"
        end += 1
    if summary:
        styles.status(ws.cell(row=end + 1, column=1, value=status_label), summary.status)
    cursor = end + 3
    ws.cell(row=cursor, column=1, value="Historique de validation").font = styles.header_font
    cursor += 1
    for log in history:
        when = timezone.localtime(log.created_at)
        ws.cell(row=cursor, column=1, value=f"{when:%d/%m/%Y %H:%M}").font = styles.font
        ws.cell(row=cursor, column=2, value=f"{log.get_action_display()} par {_name(log.actor) or '—'}").font = styles.font
        comment = ws.cell(row=cursor, column=3, value=(getattr(log, "comment", "") or "").strip() or None)
        comment.font = styles.font
        cursor += 1
    if not history:
        ws.cell(row=cursor, column=1, value="Aucune action enregistrée.").font = styles.note
    _page_setup(ws, 4)

    detail = wb.create_sheet("Saisies")
    _banner(detail, styles, f"Saisies — {_name(employee)} — {week_label(monday)}", [lines[0]], len(ENTRY_HEADERS))
    ordered = sorted(entries, key=lambda e: (e.entry_date, e.pk))
    _table(detail, styles, 4, ENTRY_HEADERS, [_entry_values(e) for e in ordered], widths=ENTRY_WIDTHS,
           formats={1: "DD/MM/YYYY", 7: "0.00"}, status_col=9, statuses=[e.approval_status for e in ordered])
    _page_setup(detail, 4)

    _info_sheet(wb, styles, exporter=exporter, workspace=workspace, now=now, filter_lines=[
        f"Collaborateur : {_name(employee)}", f"Semaine : {week_label(monday)} ({monday:%d/%m/%Y} → {days[-1]:%d/%m/%Y})",
    ], extra=(("Statut de la semaine", status_label), ("Heures", round(total, 2)), ("Saisies", len(entries))))
    return _save(wb)


def filename(prefix: str, *parts: str) -> str:
    from django.utils.text import slugify

    slug = "_".join(slugify(p).replace("-", "_") for p in parts if p)
    return f"{prefix}{('_' + slug) if slug else ''}.xlsx"
