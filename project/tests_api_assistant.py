"""Assistant IA React : vues JSON existantes, sessions privées, quota IA sur l'envoi (aucun appel payant)."""

from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from project import models as dm


@override_settings(AI_BACKEND="none", DEVFLOW_AI_RATE_LIMIT="1/min")
class AssistantApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        U = get_user_model()
        cls.alice, cls.bob = U.objects.create_user("alice", "a@x.test", "pw"), U.objects.create_user("bob", "b@x.test", "pw")
        for u in (cls.alice, cls.bob):
            ws = dm.Workspace.objects.create(name=f"WS {u.username}", owner=u)
            dm.UserProfile.objects.update_or_create(user=u, defaults={"workspace": ws})
            dm.TeamMembership.objects.create(user=u, workspace=ws)

    def setUp(self):
        cache.clear()

    def test_send_is_throttled_and_sessions_are_private(self):
        self.client.force_login(self.alice)
        now = timezone.now()
        session = dm.AIChatSession.objects.create(user=self.alice) if hasattr(dm, "AIChatSession") else None
        fake = SimpleNamespace(session=SimpleNamespace(pk=session.pk if session else 1),
                               user_message=SimpleNamespace(pk=1, content="Bonjour", intent="", created_at=now),
                               assistant_message=SimpleNamespace(pk=2, content="Réponse", used_provider="heuristic", tokens_used=0, created_at=now))
        with mock.patch("project.views_ai_chat.AIChatService.process_user_message", return_value=fake):
            first = self.client.post("/api/v1/assistant/send/", {"message": "Bonjour"}, content_type="application/json")
            second = self.client.post("/api/v1/assistant/send/", {"message": "Encore"}, content_type="application/json")
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(first.json()["assistant_message"]["content"], "Réponse")
        self.assertEqual(second.status_code, 429)
        if session:
            self.client.force_login(self.bob)
            self.assertEqual(self.client.get(f"/api/v1/assistant/sessions/{session.pk}/messages/").status_code, 404)
