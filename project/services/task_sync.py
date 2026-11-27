"""
Règles d'état communes à tous les chemins d'écriture d'une tâche.

Une tâche n'existe qu'une fois (``dm.Task``) : le timesheet, la liste des tâches,
la fiche projet et le Suivi Pôle Développement la lisent directement, sans copie.
Pour que ces écrans restent d'accord entre eux, chaque chemin d'écriture (API,
vues Django, actions rapides, import du suivi, timesheet) applique les mêmes
règles, regroupées ici :

* ``apply_status``  : dates de démarrage / clôture et avancement selon le statut ;
* ``sync_assignee`` : l'affectation active (``TaskAssignment``) suit l'assigné
  (``Task.assignee``). Sans elle, l'ancien assigné gardait la tâche dans son
  timesheet et restait porteur dans le Suivi, et le nouveau n'avait pas
  d'affectation.
"""

from __future__ import annotations

from django.utils import timezone

from project import models as dm

Status = dm.Task.Status


def apply_status(task, new_status, *, now=None, complete_progress=True) -> list[str]:
    """
    Pose ``new_status`` sur ``task`` (sans enregistrer) avec ses effets :

    * passage en cours : date de démarrage si absente ;
    * terminée : date de clôture (conservée si déjà posée), démarrage, avancement à 100 %
      (sauf ``complete_progress=False`` : l'import conserve la valeur du classeur) ;
    * tout autre statut : la date de clôture est retirée (une tâche rouverte n'est plus
      « terminée le … » dans le Suivi ni masquée du timesheet).

    Renvoie les champs modifiés, à passer à ``save(update_fields=…)``.
    """
    if not new_status or new_status == task.status:
        return []
    now = now or timezone.now()
    task.status = new_status
    changed = ["status"]
    if new_status in (Status.IN_PROGRESS, Status.DONE) and not task.started_at:
        task.started_at = now
        changed.append("started_at")
    if new_status == Status.DONE:
        if not task.completed_at:
            task.completed_at = now
            changed.append("completed_at")
        if complete_progress and task.progress_percent != 100:
            task.progress_percent = 100
            changed.append("progress_percent")
    elif task.completed_at:
        task.completed_at = None
        changed.append("completed_at")
    return changed


def sync_assignee(task, previous_assignee_id, *, actor=None) -> None:
    """
    Aligne les affectations après un changement de ``Task.assignee`` fait hors de
    ``Task.assign()`` (formulaire, API, import, création) : l'ancien assigné perd son
    affectation active, le nouveau en reçoit une. Les co-affectations explicites
    (plusieurs porteurs d'une activité) sont conservées.

    Création en ``bulk_create`` : la notification « tâche assignée » part déjà du
    changement d'assigné, une seconde serait un doublon.
    """
    current = task.assignee_id
    if current == previous_assignee_id:
        return
    if previous_assignee_id:
        dm.TaskAssignment.objects.filter(task=task, user_id=previous_assignee_id, is_active=True).update(
            is_active=False, updated_at=timezone.now())
    if current:
        reactivated = dm.TaskAssignment.objects.filter(task=task, user_id=current).update(
            is_active=True, updated_at=timezone.now())
        if not reactivated:
            dm.TaskAssignment.objects.bulk_create([dm.TaskAssignment(
                task=task, user_id=current, assigned_by=actor if getattr(actor, "pk", None) else None,
                allocation_percent=100,
            )])
