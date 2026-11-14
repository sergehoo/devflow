"""
Export Excel des tickets (mise en forme commune : ``xlsx_export``).

Reçoit le queryset déjà filtré par ``TicketViewSet`` (droits, workspace et
filtres actifs) : rien n'est élargi ici. Feuilles « Tickets » (une ligne par
ticket, SLA et délais), « Synthèse » (statuts, priorités, applications, SLA)
et « Informations » (date, exporteur, périmètre, filtres).
"""

from __future__ import annotations

from collections import Counter

from django.utils import timezone

from project import models as dm
from project.services import xlsx_export as xl

MAX_ROWS = 20_000
SCOPE_TEXT = "tickets visibles selon vos droits (workspace, équipes, affectations, tickets créés)"
T = dm.Ticket
STATUS_TONES = {
    T.Status.NEW: "info", T.Status.QUALIFIED: "info", T.Status.ASSIGNED: "info", T.Status.IN_PROGRESS: "info",
    T.Status.WAITING: "warning", T.Status.RESOLVED: "success", T.Status.CLOSED: "success", T.Status.CANCELLED: "muted",
}
SLA_TONES = {"Dépassé": "danger", "En pause": "warning", "Respecté": "success", "En cours": "info", "Sans SLA": "muted"}
HEADERS = [
    "Référence", "Titre", "Application", "Projet", "Déclarant", "Source", "Catégorie", "Gravité", "Priorité", "Statut",
    "Équipe", "Responsable", "Créé le", "Affecté le", "1re réponse le", "Résolu le", "Clôturé le",
    "Échéance 1re réponse", "Échéance résolution", "SLA", "Délai 1re réponse (h)", "Délai de résolution (h)",
    "Escalade", "Réouvertures", "Tâche liée",
]
WIDTHS = [12, 44, 22, 24, 22, 10, 14, 11, 9, 12, 20, 22, 16, 16, 16, 16, 16, 18, 18, 11, 12, 13, 9, 11, 10]
DATE_COLS = range(13, 20)


def _local(value):
    """openpyxl refuse les dates avec fuseau : heure locale DevFlow, sans tzinfo."""
    return timezone.localtime(value).replace(tzinfo=None) if value else None


def _hours_between(start, end):
    return round((end - start).total_seconds() / 3600, 2) if start and end else None


def sla_state(t) -> str:
    if t.first_response_breached or t.resolution_breached:
        return "Dépassé"
    if not (t.first_response_due or t.resolution_due):
        return "Sans SLA"
    if t.sla_paused_at is not None:
        return "En pause"
    return "En cours" if t.status in T.OPEN_STATUSES else "Respecté"


def row_values(t) -> list:
    return [
        t.reference, t.title, t.application.name if t.application_id else "", t.project.name if t.project_id else "",
        t.reporter_name or "", t.get_source_display(), t.get_category_display(), t.get_severity_display(),
        t.get_priority_display(), t.get_status_display(), t.team.name if t.team_id else "",
        xl.name(t.assignee) if t.assignee_id else "",
        _local(t.created_at), _local(t.assigned_at), _local(t.first_response_at), _local(t.resolved_at), _local(t.closed_at),
        _local(t.first_response_due), _local(t.resolution_due), sla_state(t),
        _hours_between(t.created_at, t.first_response_at), _hours_between(t.created_at, t.resolved_at),
        t.escalation_level or None, t.reopened_count or None, f"#{t.task_id}" if t.task_id else "",
    ]


def tickets_workbook(tickets, *, exporter, workspace_label, filter_lines, now=None) -> bytes:
    from openpyxl import Workbook

    now = timezone.localtime(now or timezone.now())
    styles = xl.Styles()
    tickets = list(tickets)
    header_lines = [xl.stamp(exporter, now), f"Filtres : {' · '.join(filter_lines) if filter_lines else 'aucun'}"]

    wb = Workbook()
    ws = wb.active
    ws.title = "Tickets"
    xl.banner(ws, styles, "Tickets", header_lines, len(HEADERS))
    formats = {col: "DD/MM/YYYY HH:MM" for col in DATE_COLS}
    formats.update({21: "0.00", 22: "0.00"})
    states = [sla_state(t) for t in tickets]
    xl.table(ws, styles, 4, HEADERS, [row_values(t) for t in tickets], widths=WIDTHS, formats=formats,
             tones={10: [STATUS_TONES.get(t.status) for t in tickets], 20: [SLA_TONES.get(s) for s in states]},
             empty="Aucun ticket pour le périmètre et les filtres appliqués.")
    xl.page_setup(ws, 4)

    summary = wb.create_sheet("Synthèse")
    xl.banner(summary, styles, "Tickets — synthèse", header_lines, 3)
    resolved = [h for h in (_hours_between(t.created_at, t.resolved_at) for t in tickets) if h is not None]
    first = [h for h in (_hours_between(t.created_at, t.first_response_at) for t in tickets) if h is not None]
    open_count = sum(t.status in T.OPEN_STATUSES for t in tickets)
    rows = [
        ["Tickets exportés", len(tickets), ""], ["Ouverts", open_count, ""], ["SLA dépassés", states.count("Dépassé"), ""],
        ["Délai moyen de 1re réponse (h)", round(sum(first) / len(first), 2) if first else None, f"{len(first)} ticket(s)"],
        ["Délai moyen de résolution (h)", round(sum(resolved) / len(resolved), 2) if resolved else None, f"{len(resolved)} ticket(s)"],
    ]
    for title, counter in (
        ("Statut", Counter(t.get_status_display() for t in tickets)),
        ("Priorité", Counter(t.get_priority_display() for t in tickets)),
        ("Application", Counter(t.application.name for t in tickets)),
        ("SLA", Counter(states)),
    ):
        rows += [[f"{title} : {label}", count, ""] for label, count in counter.most_common()]
    xl.table(summary, styles, 4, ["Indicateur", "Valeur", "Détail"], rows if tickets else [], widths=[42, 12, 20],
             formats={2: "0.##"}, autofilter=False, empty="Aucun ticket pour le périmètre et les filtres appliqués.")
    xl.page_setup(summary, 4)

    xl.info_sheet(wb, styles, exporter=exporter, workspace=workspace_label, now=now, scope=SCOPE_TEXT,
                  filter_lines=filter_lines, extra=(("Tickets", len(tickets)), ("Ouverts", open_count),
                                                    ("Délais", "Heures calendaires depuis la création ; l'état SLA suit le calendrier ouvré de la politique.")))
    return xl.save(wb)
