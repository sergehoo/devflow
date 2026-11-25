"""
Flux temps réel par utilisateur (Django Channels, groupe ``user_<id>``).

Diffusion « best effort » : si la couche Channels (Redis) est indisponible,
aucune erreur n'est remontée — les clients retombent sur le polling REST.
Les événements ne transportent que des identifiants / données déjà visibles
par le destinataire ; ils servent à invalider les caches côté client.
"""

from __future__ import annotations

import logging
import threading

from django.db import transaction

logger = logging.getLogger(__name__)


def user_group(user_id: int) -> str:
    return f"user_{user_id}"


def push_to_users(user_ids, event: str, data: dict | None = None) -> None:
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        layer = get_channel_layer()
        if layer is None:
            return
        send = async_to_sync(layer.group_send)
        for uid in {int(u) for u in user_ids if u}:
            send(user_group(uid), {"type": "user.event", "event": event, "data": data or {}})
    except Exception:  # Redis indisponible : le polling prend le relais
        logger.debug("realtime push failed (%s)", event, exc_info=True)


# ---------------------------------------------------------------------------
# Tâches : un seul événement « task.changed » par transaction
# ---------------------------------------------------------------------------
TASKS_CHANGED = "task.changed"
_pending = threading.local()


def _pending_state() -> dict:
    state = getattr(_pending, "state", None)
    if state is None:
        state = _pending.state = {"tasks": set(), "projects": set(), "users": set()}
    return state


def tasks_changed(*, task_ids=(), project_ids=(), user_ids=()) -> None:
    """
    Une tâche, une affectation ou une saisie de temps a changé : les écrans qui la
    montrent (tâches, timesheet, fiche projet, Suivi Pôle Développement) doivent se
    recharger chez les personnes concernées — assigné(e)s, ancien assigné, auteur,
    responsable et chef de projet.

    Les identifiants sont cumulés jusqu'à la validation de la transaction : un import
    de plusieurs centaines de tâches n'envoie qu'un message par destinataire. Le
    message ne porte aucune donnée (le client relit l'API, qui applique les droits).
    """
    state = _pending_state()
    state["tasks"].update(int(pk) for pk in task_ids if pk)
    state["projects"].update(int(pk) for pk in project_ids if pk)
    state["users"].update(int(pk) for pk in user_ids if pk)
    transaction.on_commit(_flush_tasks_changed)


def task_audience(task_ids, project_ids=()) -> set[int]:
    from django.db.models import Q

    from project import models as dm

    users: set[int] = set()
    task_ids, project_ids = set(task_ids), set(project_ids)
    if task_ids:
        for row in dm.Task.objects.filter(pk__in=task_ids).values_list(
                "assignee_id", "reporter_id", "project_id"):
            users.update(row[:2])
            project_ids.add(row[2])
        users.update(dm.TaskAssignment.objects.filter(task_id__in=task_ids, is_active=True)
                     .values_list("user_id", flat=True))
    if project_ids:
        for owner_id, pm_id in dm.Project.objects.filter(
                Q(pk__in=project_ids)).values_list("owner_id", "product_manager_id"):
            users.update((owner_id, pm_id))
    return {u for u in users if u}


def _flush_tasks_changed() -> None:
    state = _pending_state()
    if not (state["tasks"] or state["projects"] or state["users"]):
        return  # déjà envoyé par un rappel précédent de la même transaction
    tasks, projects, users = set(state["tasks"]), set(state["projects"]), set(state["users"])
    for bucket in state.values():
        bucket.clear()
    try:
        push_to_users(users | task_audience(tasks, projects), TASKS_CHANGED, {})
    except Exception:  # jamais d'erreur visible après validation
        logger.debug("realtime task.changed failed", exc_info=True)


def own_notifications(user):
    """Notifications de ``user`` limitées aux workspaces auxquels il a encore accès."""
    from project import models as dm
    from project.utils.workspaces import get_user_workspace_ids

    return dm.Notification.objects.filter(recipient=user, workspace_id__in=get_user_workspace_ids(user))


def push_notification_count(user) -> None:
    """Badge de la cloche (tous les onglets) : nombre de notifications non lues."""
    push_to_users([user.pk], "notification.read", {"unread_count": own_notifications(user).filter(is_read=False).count()})


def serialize_notification(n) -> dict:
    return {
        "id": n.pk,
        "type": n.notification_type,
        "type_label": n.get_notification_type_display(),
        "title": n.title,
        "body": n.body,
        "url": n.url,
        "is_read": n.is_read,
        "read_at": n.read_at.isoformat() if n.read_at else None,
        "created_at": n.created_at.isoformat() if n.created_at else None,
        "workspace": {"id": n.workspace_id, "name": getattr(n.workspace, "name", "")} if n.workspace_id else None,
    }
