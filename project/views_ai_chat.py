"""
Endpoints du panneau DevFlow AI (chat conversationnel temps réel).

Routes :
- GET  /ai/chat/welcome/                → message d'accueil dynamique
- POST /ai/chat/                        → envoi message + récupération réponse
- GET  /ai/chat/sessions/<id>/messages/ → historique d'une session
- POST /ai/chat/sessions/<id>/close/    → ferme une session
"""

from __future__ import annotations

import json
import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_protect

from project import models as dm
from project.services.ai.services.chat import AIChatService

logger = logging.getLogger(__name__)


class AIChatWelcomeView(LoginRequiredMixin, View):
    """Construit le message d'accueil dynamique sans appel IA."""

    def get(self, request, *args, **kwargs):
        try:
            data = AIChatService.welcome_message(user=request.user)
            return JsonResponse(
                {
                    "ok": True,
                    "html": data["html"],
                    "context_summary": _summarize_context(data["context"]),
                    "suggestions": data["suggestions"],
                }
            )
        except Exception as exc:
            logger.exception("welcome failed")
            return JsonResponse({"ok": False, "error": str(exc)}, status=500)


@method_decorator(csrf_protect, name="dispatch")
class AIChatSendView(LoginRequiredMixin, View):
    """Reçoit un message utilisateur et renvoie la réponse de l'assistant."""

    def post(self, request, *args, **kwargs):
        try:
            payload = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            return HttpResponseBadRequest("Invalid JSON")

        message = (payload.get("message") or "").strip()
        if not message:
            return JsonResponse({"ok": False, "error": "message vide"}, status=400)

        session_id = payload.get("session_id")
        project_id = payload.get("project_id")

        project = None
        if project_id:
            project = dm.Project.objects.filter(pk=project_id).first()

        try:
            result = AIChatService.process_user_message(
                user=request.user,
                message=message,
                session_id=session_id,
                project=project,
            )
        except ValueError as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:
            logger.exception("chat send failed")
            return JsonResponse({"ok": False, "error": str(exc)}, status=500)

        return JsonResponse({
            "ok": True,
            "session_id": result.session.pk,
            "user_message": {
                "id": result.user_message.pk,
                "content": result.user_message.content,
                "intent": result.user_message.intent,
                "created_at": result.user_message.created_at.isoformat(),
            },
            "assistant_message": {
                "id": result.assistant_message.pk,
                "content": result.assistant_message.content,
                "used_provider": result.assistant_message.used_provider,
                "tokens_used": result.assistant_message.tokens_used,
                "created_at": result.assistant_message.created_at.isoformat(),
            },
        })


class AIChatHistoryView(LoginRequiredMixin, View):
    def get(self, request, session_id, *args, **kwargs):
        session = get_object_or_404(
            dm.AIChatSession.objects.prefetch_related("messages"),
            pk=session_id,
            user=request.user,
        )
        return JsonResponse({
            "ok": True,
            "session": {
                "id": session.pk,
                "title": session.title,
                "is_active": session.is_active,
                "created_at": session.created_at.isoformat(),
            },
            "messages": [
                {
                    "id": m.pk,
                    "role": m.role,
                    "content": m.content,
                    "intent": m.intent,
                    "used_provider": m.used_provider,
                    "created_at": m.created_at.isoformat(),
                }
                for m in session.messages.all()
            ],
        })


class AIChatCloseSessionView(LoginRequiredMixin, View):
    def post(self, request, session_id, *args, **kwargs):
        session = get_object_or_404(
            dm.AIChatSession, pk=session_id, user=request.user,
        )
        session.is_active = False
        from django.utils import timezone
        session.closed_at = timezone.now()
        session.save(update_fields=["is_active", "closed_at", "updated_at"])
        return JsonResponse({"ok": True})


def _summarize_context(ctx: dict) -> dict:
    """Version allégée du contexte pour le front (debug + UI)."""
    sprint = ctx.get("active_sprint") or {}
    ws = ctx.get("workspace") or {}
    return {
        "workspace_name": ws.get("name", ""),
        "active_sprint": sprint.get("name", ""),
        "velocity_percent": sprint.get("velocity_percent"),
        "days_remaining": sprint.get("days_remaining"),
        "at_risk_count": len(ctx.get("at_risk_projects") or []),
    }
