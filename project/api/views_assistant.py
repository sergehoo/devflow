"""Assistant IA (chat) pour le frontend React : vues JSON existantes de ``views_ai_chat`` (quota IA sur l'envoi)."""

from __future__ import annotations

from rest_framework import permissions
from rest_framework.parsers import JSONParser
from rest_framework.views import APIView

from project.api.throttles import AIActionRateThrottle
from project.api.views_finance import _delegate


class AssistantWelcomeAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from project.views_ai_chat import AIChatWelcomeView

        return _delegate(AIChatWelcomeView, request)


class AssistantSendAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser]
    throttle_classes = [AIActionRateThrottle]

    def post(self, request):
        from project.views_ai_chat import AIChatSendView

        return _delegate(AIChatSendView, request)


class AssistantHistoryAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, session_id):
        from project.views_ai_chat import AIChatHistoryView

        return _delegate(AIChatHistoryView, request, session_id=session_id)


class AssistantCloseAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser]

    def post(self, request, session_id):
        from project.views_ai_chat import AIChatCloseSessionView

        return _delegate(AIChatCloseSessionView, request, session_id=session_id)
