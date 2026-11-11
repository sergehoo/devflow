"""
Notifications du Suivi Pôle Développement.

Complète l'existant sans le doubler : les relances de tâches (échéance, retard,
inactivité) restent assurées par ``TaskReminderService``. Ce module couvre le
niveau projet / activité : échéance proche, retard, progression inactive,
décision attendue, élément bloqué.

Les notifications passent par ``create_in_app_notification`` (temps réel assuré
par le signal ``push_notification_realtime``). Une même alerte n'est pas
répétée avant ``REPEAT_DAYS`` : la clé de dédoublonnage est stockée dans
``Notification.metadata``.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from project import models as dm
from project.services.notifications import create_in_app_notification
from project.services.tracking_board import CLOSED, STALE_DAYS, all_workspaces_scope, build_rows

SOURCE = "tracking"
BOARD_URL = "/pilotage/suivi/"
DEADLINE_DAYS = 3
REPEAT_DAYS = 7
MAX_PER_RUN = 500
Kind = dm.Notification.NotificationType


def _url(row) -> str:
    return f"/projects/{row['pk']}/" if row["kind"] == "project" else f"/tasks/{row['pk']}/"


def notify(*, recipient, workspace, kind, ref, title, body="", url=BOARD_URL,
           notification_type=Kind.PROJECT, dedupe="", sent=None) -> bool:
    """Crée la notification sauf si la même (destinataire, clé) existe déjà."""
    if recipient is None or not getattr(recipient, "is_active", True):
        return False
    token = f"{kind}:{ref}:{dedupe}"
    if sent is not None:
        if (recipient.pk, token) in sent:
            return False
        sent.add((recipient.pk, token))
    create_in_app_notification(
        recipient=recipient, workspace=workspace, notification_type=notification_type,
        title=title[:180], body=body, url=url,
        metadata={"source": SOURCE, "kind": kind, "ref": ref, "dedupe": token},
    )
    return True


def run_sweep(today=None) -> dict:
    """Balayage quotidien : une notification par porteur et par situation."""
    today = today or timezone.localdate()
    rows = [r for r in build_rows(all_workspaces_scope(), today=today) if r["status_key"] not in CLOSED]
    since = timezone.now() - timedelta(days=REPEAT_DAYS)
    sent = set()
    for recipient_id, token in (dm.Notification.objects
                                .filter(metadata__source=SOURCE, created_at__gte=since)
                                .values_list("recipient_id", "metadata__dedupe")):
        sent.add((recipient_id, token))
    user_ids = {o["user_id"] for r in rows for o in r["owners"] if o["user_id"]}
    users = {u.pk: u for u in get_user_model().objects.filter(pk__in=user_ids, is_active=True)} if user_ids else {}
    workspaces = dm.Workspace.objects.in_bulk({r["workspace"]["id"] for r in rows})

    counts = {"deadline": 0, "late": 0, "stale": 0, "decision": 0, "blocked": 0}
    total = 0
    for row in rows:
        label = "Projet" if row["kind"] == "project" else "Activité"
        kind_type = Kind.PROJECT if row["kind"] == "project" else Kind.TASK
        events = []
        end = date.fromisoformat(row["end"]) if row["end"] else None
        if end and today <= end <= today + timedelta(days=DEADLINE_DAYS):
            days = (end - today).days
            when = "aujourd'hui" if days == 0 else f"dans {days} jour{'s' if days > 1 else ''}"
            events.append(("deadline", row["end"], f"Échéance {when} : {row['title']}",
                           f"{label} à {row['progress']} % d'avancement, échéance le {end:%d/%m/%Y}.", kind_type))
        if row["late"]:
            events.append(("late", "", f"En retard de {row['days_late']} j : {row['title']}",
                           f"Échéance dépassée depuis le {end:%d/%m/%Y} ({row['progress']} % d'avancement).",
                           kind_type))
        if row["stale"] and row["kind"] == "project":
            events.append(("stale", "", f"Aucune mise à jour depuis {STALE_DAYS} jours : {row['title']}",
                           "Mettez à jour l'avancement, les actions ou le statut du projet.", kind_type))
        if row["pending_decisions"]:
            texts = [a["text"] for a in row["alerts"] if a["type"] == "decision"]
            events.append(("decision", "", f"Décision attendue : {row['title']}", "\n".join(texts[:5]), kind_type))
        if row["blocked"]:
            cause = next((a["text"] for a in row["alerts"] if a["kind"] in ("BLOCKER", "DEPENDENCY")), "")
            events.append(("blocked", "", f"{label} bloqué{'e' if row['kind'] == 'task' else ''} : {row['title']}",
                           cause, Kind.RISK))
        for kind, dedupe, title, body, notification_type in events:
            for owner in row["owners"]:
                recipient = users.get(owner["user_id"])
                if total >= MAX_PER_RUN:
                    return {**counts, "total": total, "truncated": True}
                if notify(recipient=recipient, workspace=workspaces[row["workspace"]["id"]], kind=kind, ref=row["id"],
                          title=title, body=body, url=_url(row), notification_type=notification_type,
                          dedupe=dedupe, sent=sent):
                    counts[kind] += 1
                    total += 1
    return {**counts, "total": total, "truncated": False}


# ---------------------------------------------------------------------------
# Événements immédiats (appelés par les signaux)
# ---------------------------------------------------------------------------
def notify_new_risk(risk) -> None:
    project = risk.project
    if project is None or project.owner_id is None:
        return
    notify(recipient=project.owner, workspace=risk.workspace, kind="new_alert", ref=f"R{risk.pk}",
           title=f"Nouvelle alerte sur {project.name}", body=risk.title,
           url=f"/projects/{project.pk}/", notification_type=Kind.RISK)


def notify_pending_decision(decision, project_ids) -> None:
    for project in (dm.Project.objects.filter(pk__in=project_ids, owner__isnull=False)
                    .select_related("owner", "workspace")):
        notify(recipient=project.owner, workspace=project.workspace, kind="decision_created",
               ref=f"D{decision.pk}", title=f"Décision attendue sur {project.name}", body=decision.title,
               url=f"/projects/{project.pk}/", notification_type=Kind.PROJECT)


def notify_owner_change(project, previous_owner_id) -> None:
    if project.owner_id is None or project.owner_id == previous_owner_id:
        return
    notify(recipient=project.owner, workspace=project.workspace, kind="owner_changed", ref=f"P{project.pk}",
           title=f"Vous êtes désormais porteur du projet {project.name}",
           body="Le suivi du projet (avancement, actions, alertes) vous est rattaché.",
           url=f"/projects/{project.pk}/", notification_type=Kind.PROJECT)
