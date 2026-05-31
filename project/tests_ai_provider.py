"""
Tests Phase 4 — Provider IA DeepSeek + factory (PR17).

Pas d'appel API réel : on teste juste l'aiguillage du factory et les
attributs de configuration. L'usage réel est testé manuellement avec une
vraie clé DEEPSEEK_API_KEY en staging.

Lance avec :
    python manage.py test project.tests_ai_provider
"""

from __future__ import annotations

from django.test import TestCase, override_settings

from project.services.ai.deepseek_provider import DeepSeekProvider
from project.services.ai.factory import _NullProvider, get_ai_provider
from project.services.ai.local_provider import LocalProvider
from project.services.ai.openai_provider import OpenAIProvider


class DeepSeekProviderConfigTests(TestCase):
    """Vérifie la configuration et les flags du DeepSeekProvider."""

    @override_settings(
        DEEPSEEK_API_KEY="sk-fake-deepseek-test",
        AI_DEEPSEEK_MODEL="deepseek-chat",
        AI_DEEPSEEK_BASE_URL="https://api.deepseek.com/v1",
    )
    def test_provider_init_picks_up_settings(self):
        provider = DeepSeekProvider()
        self.assertEqual(provider.name, "deepseek")
        self.assertEqual(provider.api_key, "sk-fake-deepseek-test")
        self.assertEqual(provider.model, "deepseek-chat")
        self.assertEqual(provider.base_url, "https://api.deepseek.com/v1")

    @override_settings(DEEPSEEK_API_KEY="sk-fake-deepseek-test")
    def test_provider_is_available_when_api_key_set(self):
        self.assertTrue(DeepSeekProvider().is_available())

    @override_settings(DEEPSEEK_API_KEY="")
    def test_provider_unavailable_without_key(self):
        self.assertFalse(DeepSeekProvider().is_available())

    def test_provider_supports_json_mode(self):
        # DeepSeek v3 supporte response_format=json_object
        self.assertTrue(DeepSeekProvider().supports_json_mode())

    def test_provider_init_allows_override(self):
        provider = DeepSeekProvider(
            api_key="other-key", model="deepseek-reasoner",
            base_url="https://custom.example.com/v1",
        )
        self.assertEqual(provider.api_key, "other-key")
        self.assertEqual(provider.model, "deepseek-reasoner")
        self.assertEqual(provider.base_url, "https://custom.example.com/v1")


class FactoryRoutingTests(TestCase):
    """Vérifie le dispatcher get_ai_provider selon settings.AI_BACKEND."""

    @override_settings(AI_BACKEND="deepseek")
    def test_force_deepseek_returns_deepseek_provider(self):
        self.assertIsInstance(get_ai_provider(), DeepSeekProvider)

    @override_settings(AI_BACKEND="openai")
    def test_force_openai_returns_openai_provider(self):
        self.assertIsInstance(get_ai_provider(), OpenAIProvider)

    @override_settings(AI_BACKEND="local")
    def test_force_local_returns_local_provider(self):
        self.assertIsInstance(get_ai_provider(), LocalProvider)

    @override_settings(AI_BACKEND="none")
    def test_force_none_returns_null_provider(self):
        provider = get_ai_provider()
        self.assertIsInstance(provider, _NullProvider)
        self.assertFalse(provider.is_available())

    @override_settings(
        AI_BACKEND="auto",
        DEEPSEEK_API_KEY="sk-fake-deepseek-test",
        OPENAI_API_KEY="",
        AI_LOCAL_BASE_URL="",
    )
    def test_auto_prefers_deepseek_when_key_available(self):
        """En mode auto, DeepSeek est prioritaire si la clé est configurée."""
        self.assertIsInstance(get_ai_provider(), DeepSeekProvider)

    @override_settings(
        AI_BACKEND="auto",
        DEEPSEEK_API_KEY="",
        OPENAI_API_KEY="sk-fake-openai-test",
    )
    def test_auto_falls_back_to_openai_without_deepseek(self):
        """Si pas de clé DeepSeek mais OpenAI dispo, on prend OpenAI."""
        self.assertIsInstance(get_ai_provider(), OpenAIProvider)

    @override_settings(
        AI_BACKEND="auto",
        DEEPSEEK_API_KEY="",
        OPENAI_API_KEY="",
        AI_LOCAL_BASE_URL="http://localhost:11434/v1",
    )
    def test_auto_falls_back_to_local_without_remote_keys(self):
        self.assertIsInstance(get_ai_provider(), LocalProvider)

    @override_settings(
        AI_BACKEND="auto",
        DEEPSEEK_API_KEY="",
        OPENAI_API_KEY="",
        AI_LOCAL_BASE_URL="",
    )
    def test_auto_falls_back_to_null_when_nothing_configured(self):
        provider = get_ai_provider()
        self.assertIsInstance(provider, _NullProvider)

    def test_prefer_argument_overrides_settings(self):
        """get_ai_provider(prefer='deepseek') doit gagner sur AI_BACKEND."""
        with override_settings(
            AI_BACKEND="openai", DEEPSEEK_API_KEY="sk-x",
        ):
            self.assertIsInstance(
                get_ai_provider(prefer="deepseek"), DeepSeekProvider,
            )
