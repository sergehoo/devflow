"""
DevFlow REST API — Endpoints quick-actions tâches (Phase 1 — PR7).

Tous ces endpoints sont des actions JSON appelées par l'UI Tailwind/Alpine
(toggle complete, change status, snooze, assign, kanban move, my day).

Sécurité :
  * IsAuthenticated obligatoire
  * Toutes les tâches sont chargées via _get_task_or_404 qui filtre par
    workspace de l'utilisateur — toute action cross-tenant retourne 404.
"""

from __future__ import annotations

from datetime import datetime

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from project import models as dm
from project.services.my_day import MyDayService
from project.utils.workspaces import get_user_workspace_ids


User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_task_or_404(request, task_pk: int) -> dm.Task:
    """Charge la tâche en filtrant par workspace user. 404 si cross-tenant."""
    workspace_ids = get_user_workspace_ids(request.user)
    return get_object_or_404(
        dm.Task.objects.select_related("project", "workspace", "assignee"),
        pk=task_pk,
        workspace_id__in=workspace_ids,
        is_archived=False,
    )


def _task_payload(task: dm.Task) -> dict:
    return {
        "id": task.pk,
        "title": task.title,
        "status": task.status,
        "status_label": task.get_status_display(),
        "priority": task.priority,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": (
            task.completed_at.isoformat() if task.completed_at else None
        ),
        "snoozed_until": (
            task.snoozed_until.isoformat() if task.snoozed_until else None
        ),
        "assignee_id": task.assignee_id,
        "project_id": task.project_id,
        "position": task.position,
        "spent_hours": str(task.spent_hours or 0),
        "is_flagged": bool(task.is_flagged),
    }


def _maybe_log(task: dm.Task, actor, activity_type, title, description=""):
    """Création best-effort d'un ActivityLog — n'échoue pas la réponse."""
    try:
        dm.ActivityLog.objects.create(
            workspace=task.workspace,
            actor=actor,
            project=task.project,
            task=task,
            activity_type=activity_type,
            title=title,
            description=description,
        )
    except Exception:
        pass


def _assignee_required(task: dm.Task, user):
    """Empêche toute action opérationnelle sur la tâche d'un collègue."""
    if task.assignee_id == user.id:
        return None
    return Response(
        {"detail": "Cette tâche est assignée à un autre collaborateur."},
        status=status.HTTP_403_FORBIDDEN,
    )


def _record_optional_time(task: dm.Task, user, data):
    """Enregistre la durée éventuellement fournie par les interfaces rapides."""
    raw_hours = (data or {}).get("spent_hours")
    if raw_hours in (None, "", 0, "0", "0.0", "0.00"):
        return None

    from project.services.task_time import TaskTimeError, record_task_time

    try:
        return record_task_time(task=task, user=user, hours=raw_hours)
    except TaskTimeError as exc:
        raise ValueError(str(exc)) from exc


# ---------------------------------------------------------------------------
# 1) Toggle complete — bascule DONE ↔ TODO selon l'état courant
# ---------------------------------------------------------------------------
class TaskToggleCompleteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        task = _get_task_or_404(request, pk)
        denied = _assignee_required(task, request.user)
        if denied:
            return denied
        try:
            _record_optional_time(task, request.user, request.data)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        now = timezone.now()

        if task.status == dm.Task.Status.DONE:
            task.status = dm.Task.Status.TODO
            task.completed_at = None
        else:
            task.status = dm.Task.Status.DONE
            task.completed_at = now
            if not task.started_at:
                task.started_at = now

        task.save(update_fields=["status", "completed_at", "started_at",
                                 "updated_at"])
        _maybe_log(
            task, request.user, dm.ActivityLog.ActivityType.TASK_MOVED,
            f"Tâche basculée → {task.get_status_display()}",
        )
        return Response(_task_payload(task))


# ---------------------------------------------------------------------------
# 2) Update status — body: {status}
# ---------------------------------------------------------------------------
class TaskUpdateStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        task = _get_task_or_404(request, pk)
        new_status = (request.data or {}).get("status")

        allowed = {choice[0] for choice in dm.Task.Status.choices}
        if new_status not in allowed:
            return Response(
                {"detail": "Statut invalide.",
                 "allowed": sorted(allowed)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        denied = _assignee_required(task, request.user)
        if denied:
            return denied
        try:
            _record_optional_time(task, request.user, request.data)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        previous = task.status
        task.status = new_status
        now = timezone.now()

        if new_status == dm.Task.Status.IN_PROGRESS and not task.started_at:
            task.started_at = now
        if new_status == dm.Task.Status.DONE and not task.completed_at:
            task.completed_at = now
        if new_status != dm.Task.Status.DONE:
            task.completed_at = None

        task.save(update_fields=["status", "started_at", "completed_at",
                                 "updated_at"])
        _maybe_log(
            task, request.user, dm.ActivityLog.ActivityType.TASK_MOVED,
            f"Statut {previous} → {new_status}",
        )
        return Response(_task_payload(task))


# ---------------------------------------------------------------------------
# 3) Snooze — body: {until: ISO datetime} ou {until: null} pour annuler
# ---------------------------------------------------------------------------
class TaskSnoozeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        task = _get_task_or_404(request, pk)
        denied = _assignee_required(task, request.user)
        if denied:
            return denied
        raw = (request.data or {}).get("until")

        if raw in (None, "", "null"):
            task.snoozed_until = None
        else:
            try:
                value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            except Exception:
                return Response(
                    {"detail": "Format 'until' invalide (attendu ISO 8601)."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if timezone.is_naive(value):
                value = timezone.make_aware(value, timezone.get_current_timezone())
            task.snoozed_until = value

        task.save(update_fields=["snoozed_until", "updated_at"])
        return Response(_task_payload(task))


# ---------------------------------------------------------------------------
# 4) Quick assign — body: {user_id?: int}, null/absent = unassign
# ---------------------------------------------------------------------------
class TaskQuickUpdateView(APIView):
    """
    GET  — état courant pour le panneau « Mise à jour rapide ».
    POST {status?, progress_percent?, spent_hours?, comment?} — mise à jour atomique (assigné uniquement).
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        from project.services.task_quick_update import task_state

        return Response(task_state(_get_task_or_404(request, pk), request.user))

    def post(self, request, pk):
        from project.services.task_quick_update import QuickUpdateError, apply_quick_update

        task = _get_task_or_404(request, pk)
        try:
            return Response(apply_quick_update(task, request.user, request.data))
        except QuickUpdateError as exc:
            code = status.HTTP_403_FORBIDDEN if "assigné" in str(exc) else status.HTTP_400_BAD_REQUEST
            return Response({"detail": str(exc)}, status=code)


class TaskQuickAssignJSONView(APIView):
    """POST {user_id?: int, note?: str} — réaffecte (null/absent = retirer l'assignation)."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        from project.services.task_assignment import ReassignError, reassign

        task = _get_task_or_404(request, pk)
        data = request.data or {}
        try:
            new_user = reassign(task, data.get("user_id"), actor=request.user, note=data.get("note", ""))
        except ReassignError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN
                            if "droit" in str(exc) else status.HTTP_400_BAD_REQUEST)
        task.refresh_from_db()
        payload = _task_payload(task)
        payload["assignee_name"] = (new_user.get_full_name() or new_user.get_username()) if new_user else ""
        return Response(payload)


class TaskAssigneesJSONView(APIView):
    """GET ?q= — candidats à la réaffectation (membres du workspace de la tâche)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        from project.services.task_assignment import assignable_users, can_reassign

        task = _get_task_or_404(request, pk)
        return Response({
            "task": {"id": task.pk, "title": task.title, "assignee_id": task.assignee_id},
            "can_reassign": can_reassign(request.user, task),
            "users": assignable_users(task, query=request.GET.get("q", "")),
        })


# ---------------------------------------------------------------------------
# 5) Move kanban — body: {column_id: int, position?: int} ou {status, position}
# ---------------------------------------------------------------------------
class TaskMoveKanbanJSONView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        task = _get_task_or_404(request, pk)
        data = request.data or {}

        new_status = data.get("status")
        column_id = data.get("column_id")

        # Si on reçoit un column_id, on déduit le mapped_status. La colonne
        # doit appartenir au même projet — vérification cross-tenant.
        if column_id and not new_status:
            try:
                column = dm.BoardColumn.objects.get(
                    pk=column_id, project_id=task.project_id,
                )
            except dm.BoardColumn.DoesNotExist:
                return Response(
                    {"detail": "Colonne introuvable pour ce projet."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            new_status = column.mapped_status or task.status

        allowed = {choice[0] for choice in dm.Task.Status.choices}
        if new_status and new_status not in allowed:
            return Response(
                {"detail": "Statut invalide.", "allowed": sorted(allowed)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        denied = _assignee_required(task, request.user)
        if denied:
            return denied
        try:
            _record_optional_time(task, request.user, data)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if new_status:
            task.status = new_status
            now = timezone.now()
            if new_status == dm.Task.Status.IN_PROGRESS and not task.started_at:
                task.started_at = now
            if new_status == dm.Task.Status.DONE and not task.completed_at:
                task.completed_at = now

        try:
            new_position = int(data.get("position", task.position))
        except (TypeError, ValueError):
            new_position = task.position
        task.position = max(new_position, 0)

        task.save(update_fields=["status", "position", "started_at",
                                 "completed_at", "updated_at"])
        return Response(_task_payload(task))


# ---------------------------------------------------------------------------
# 6) My today — agrégat "Mes actions du jour"
# ---------------------------------------------------------------------------
class MyTodayView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        payload = MyDayService.build(request.user)
        return Response(payload.to_dict())


# ---------------------------------------------------------------------------
# 7) Phase 4 (PR20) — Streaming SSE pour le chat IA
# ---------------------------------------------------------------------------
class AIChatStreamView(APIView):
    """
    Endpoint SSE qui streame la réponse IA token par token.

    GET /api/v1/ai/chat/stream/?prompt=... [&project_id=...]

    Format SSE :
        data: {"type": "chunk", "text": "..."}
        data: {"type": "done", "tokens_used": 123}

    Le quota IA workspace est vérifié AVANT d'ouvrir le stream — si dépassé,
    on retourne un 429 + un event SSE explicatif.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from django.http import StreamingHttpResponse
        from project.services.ai.base import AIMessage
        from project.services.ai.factory import get_ai_provider
        from project.services.ai.quota import AIQuotaService
        from project.utils.workspaces import get_user_workspace_ids

        prompt = (request.GET.get("prompt") or "").strip()
        if not prompt:
            return Response(
                {"detail": "Paramètre 'prompt' requis."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Optionnel : scoper sur un projet précis
        project = None
        project_id = request.GET.get("project_id")
        if project_id:
            workspace_ids = get_user_workspace_ids(request.user)
            project = dm.Project.objects.filter(
                pk=project_id, workspace_id__in=workspace_ids,
            ).first()

        # Récupère le workspace pour le quota check
        workspace = project.workspace if project else None
        if workspace is None:
            from project.utils.workspaces import get_default_workspace_for_user
            workspace = get_default_workspace_for_user(request.user)

        if workspace is not None:
            quota_check = AIQuotaService.can_consume(
                workspace, estimated_tokens=500,
            )
            if not quota_check.allowed:
                return Response(
                    {"detail": quota_check.reason, "quota": quota_check.to_dict()},
                    status=429,
                )

        provider = get_ai_provider()
        if not provider.is_available() or not hasattr(provider, "generate_stream"):
            return Response(
                {"detail": "Provider IA streaming indisponible."},
                status=503,
            )

        def event_stream():
            import json as _json
            total_chars = 0
            try:
                messages = [
                    AIMessage(role="system",
                              content="Tu es DevFlow AI, assistant pilotage projet."),
                ]
                if project:
                    ctx = (
                        f"Contexte projet : {project.name} · "
                        f"{project.get_status_display()} · "
                        f"progression {project.progress_percent}%."
                    )
                    messages.append(AIMessage(role="system", content=ctx))
                messages.append(AIMessage(role="user", content=prompt))

                for chunk in provider.generate_stream(
                    messages, temperature=0.3, max_tokens=800,
                ):
                    total_chars += len(chunk)
                    yield f"data: {_json.dumps({'type': 'chunk', 'text': chunk})}\n\n"

                # On enregistre une estimation de tokens (≈ chars/4)
                estimated_tokens = max(1, total_chars // 4)
                if workspace is not None:
                    try:
                        AIQuotaService.record_usage(workspace, estimated_tokens)
                    except Exception:
                        pass

                yield (
                    f"data: {_json.dumps({'type': 'done', 'tokens_used': estimated_tokens})}\n\n"
                )
            except Exception as exc:
                yield f"data: {_json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

        response = StreamingHttpResponse(
            event_stream(), content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"  # nginx : pas de buffering
        return response
