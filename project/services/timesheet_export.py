"""
Export Excel des timesheets (mise en forme commune : ``xlsx_export``).

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

from collections import defaultdict
from datetime import date, timedelta

from django.utils import timezone

from project import models as dm
from project.services import xlsx_export as xl
from project.services.xlsx_export import XLSX_MIME, filename  # noqa: F401 — API publique des vues

EMPTY_MENTION = "Aucune saisie pour le périmètre et les filtres appliqués."
SCOPE_TEXT = "vos saisies et celles de vos collaborateurs (N-1, N-2…)"
WEEKDAYS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
# Libellés de l'interface (Brouillon / Soumise / Validée / Rejetée), pas ceux du modèle (« Approuvé »…).
STATUS_LABELS = {"DRAFT": "Brouillon", "SUBMITTED": "Soumise", "APPROVED": "Validée", "REJECTED": "Rejetée"}
STATUS_TONES = {"APPROVED": "success", "SUBMITTED": "info", "REJECTED": "danger", "DRAFT": "muted"}
_name = xl.name


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


def _entry_values(e) -> list:
    monday = e.entry_date - timedelta(days=e.entry_date.weekday())
    return [
        e.entry_date, week_label(monday), _name(e.user), e.project.name if e.project_id else "",
        e.task.title if e.task_id else "", e.description or "", _hours(e.hours),
        "Oui" if e.is_billable else "Non", STATUS_LABELS.get(e.approval_status, e.approval_status),
    ]


ENTRY_HEADERS = ["Date", "Semaine", "Collaborateur", "Projet", "Tâche", "Description", "Heures", "Facturable", "Statut"]
ENTRY_WIDTHS = [12, 11, 24, 28, 36, 50, 9, 11, 13]


def _entries_table(ws, styles, entries):
    xl.table(ws, styles, 4, ENTRY_HEADERS, [_entry_values(e) for e in entries], widths=ENTRY_WIDTHS,
             formats={1: "DD/MM/YYYY", 7: "0.00"}, tones={9: [STATUS_TONES.get(e.approval_status) for e in entries]},
             empty=EMPTY_MENTION)
    xl.page_setup(ws, 4)


def _total_row(ws, styles, row, values, formats):
    for col, value in enumerate(values, start=1):
        cell = ws.cell(row=row, column=col, value=value)
        cell.font = styles.bold
        cell.fill = styles.total_fill
        cell.border = styles.border
        cell.number_format = formats.get(col, "General")


# ---------------------------------------------------------------------------
# Historique filtré
# ---------------------------------------------------------------------------
def entries_workbook(entries, *, exporter, workspace, filter_lines, now=None) -> bytes:
    from openpyxl import Workbook

    now = timezone.localtime(now or timezone.now())
    styles = xl.Styles()
    entries = list(entries)
    header_lines = [xl.stamp(exporter, now), f"Filtres : {' · '.join(filter_lines) if filter_lines else 'aucun'}"]

    weeks, people = {}, {}
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
    week_status = {key: consolidated(w["statuses"]) for key, w in weeks.items()}
    approved = defaultdict(int)
    for (user_id, _), status in week_status.items():
        approved[user_id] += status == dm.TimesheetEntry.ApprovalStatus.APPROVED

    wb = Workbook()
    summary = wb.active
    summary.title = "Synthèse"
    people_rows = sorted(people.values(), key=lambda p: _name(p["user"]).lower())
    pct = {2: "0.00", 3: "0.00", 4: "0.00", 5: "0%"}
    xl.banner(summary, styles, "Timesheets — synthèse par collaborateur", header_lines, 9)
    end = xl.table(
        summary, styles, 4,
        ["Collaborateur", "Heures", "Facturables", "Non facturables", "% facturable", "Semaines", "Validées", "En attente / brouillon", "Projets"],
        [[
            _name(p["user"]), round(p["hours"], 2), round(p["billable"], 2), round(p["hours"] - p["billable"], 2),
            (p["billable"] / p["hours"]) if p["hours"] else 0, len(p["weeks"]), approved[p["user"].pk],
            len(p["weeks"]) - approved[p["user"].pk], ", ".join(sorted(p["projects"])),
        ] for p in people_rows],
        widths=[28, 10, 12, 15, 12, 11, 10, 20, 60], formats=pct, empty=EMPTY_MENTION,
    )
    if people_rows:
        total = sum(p["hours"] for p in people_rows)
        billable = sum(p["billable"] for p in people_rows)
        _total_row(summary, styles, end, ["Total", round(total, 2), round(billable, 2), round(total - billable, 2),
                                          (billable / total) if total else 0, len({m for _, m in weeks})], pct)
    xl.page_setup(summary, 4)

    sheets = wb.create_sheet("Feuilles de temps")
    week_rows = sorted(weeks.values(), key=lambda w: (-w["monday"].toordinal(), _name(w["user"]).lower()))
    xl.banner(sheets, styles, "Feuilles de temps hebdomadaires", header_lines, 10)
    xl.table(
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
        tones={9: [STATUS_TONES.get(week_status[(w["user"].pk, w["monday"])]) for w in week_rows]}, empty=EMPTY_MENTION,
    )
    xl.page_setup(sheets, 4)

    detail = wb.create_sheet("Saisies")
    xl.banner(detail, styles, "Détail des saisies", header_lines, len(ENTRY_HEADERS))
    _entries_table(detail, styles, entries)

    xl.info_sheet(wb, styles, exporter=exporter, workspace=workspace, now=now, scope=SCOPE_TEXT, filter_lines=filter_lines, extra=(
        ("Collaborateurs", len(people)), ("Feuilles hebdomadaires", len(weeks)), ("Saisies", len(entries)),
        ("Heures", round(sum(_hours(e.hours) for e in entries), 2)),
    ))
    return xl.save(wb)


# ---------------------------------------------------------------------------
# Feuille de temps d'une semaine
# ---------------------------------------------------------------------------
def week_workbook(*, employee, workspace, monday, entries, summary, history, exporter, now=None) -> bytes:
    from openpyxl import Workbook

    now = timezone.localtime(now or timezone.now())
    styles = xl.Styles()
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
    lines.append(xl.stamp(exporter, now))
    xl.banner(ws, styles, f"Feuille de temps — {_name(employee)}", lines, width)
    headers = ["Projet", "Tâche / activité", "Type", *[f"{WEEKDAYS[i]} {d:%d/%m}" for i, d in enumerate(days)], "Total"]
    hour_formats = {col: "0.00" for col in range(4, width + 1)}
    end = xl.table(
        ws, styles, 4, headers,
        [[r["project"], r["label"], r["kind"], *[round(r["cells"].get(d, 0.0), 2) or None for d in days],
          round(sum(r["cells"].values()), 2)] for r in rows],
        widths=[28, 44, 10, *([10] * len(days)), 10], formats=hour_formats, autofilter=False, empty=EMPTY_MENTION,
    )
    if rows:
        _total_row(ws, styles, end, ["Total jour", "", "", *[round(day_totals[d], 2) for d in days], round(total, 2)], hour_formats)
        end += 1
    if summary:
        styles.tone(ws.cell(row=end + 1, column=1, value=status_label), STATUS_TONES.get(summary.status))
    cursor = end + 3
    ws.cell(row=cursor, column=1, value="Historique de validation").font = styles.header_font
    cursor += 1
    for log in history:
        when = timezone.localtime(log.created_at)
        ws.cell(row=cursor, column=1, value=f"{when:%d/%m/%Y %H:%M}").font = styles.font
        ws.cell(row=cursor, column=2, value=f"{log.get_action_display()} par {_name(log.actor) or '—'}").font = styles.font
        ws.cell(row=cursor, column=3, value=(getattr(log, "comment", "") or "").strip() or None).font = styles.font
        cursor += 1
    if not history:
        ws.cell(row=cursor, column=1, value="Aucune action enregistrée.").font = styles.note
    xl.page_setup(ws, 4)

    detail = wb.create_sheet("Saisies")
    xl.banner(detail, styles, f"Saisies — {_name(employee)} — {week_label(monday)}", [lines[0]], len(ENTRY_HEADERS))
    _entries_table(detail, styles, sorted(entries, key=lambda e: (e.entry_date, e.pk)))

    xl.info_sheet(wb, styles, exporter=exporter, workspace=workspace, now=now, scope=SCOPE_TEXT, filter_lines=[
        f"Collaborateur : {_name(employee)}", f"Semaine : {week_label(monday)} ({monday:%d/%m/%Y} → {days[-1]:%d/%m/%Y})",
    ], extra=(("Statut de la semaine", status_label), ("Heures", round(total, 2)), ("Saisies", len(entries))))
    return xl.save(wb)
