"""
Tests Phase 4 — Provider IA DeepSeek + factory (PR17).

Pas d'appel API réel : on teste l'aiguillage du factory, la configuration de
``AI_FALLBACK_CHAIN`` et la bascule entre fournisseurs avec des providers
factices. L'usage réel est testé manuellement avec une vraie clé en staging.

Lance avec :
    python manage.py test project.tests_ai_provider
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import httpx
import openai
from django.test import SimpleTestCase, TestCase, override_settings

from project.services.ai.anthropic_provider import AnthropicProvider
from project.services.ai.base import AIMessage, AIProvider, AIResponse, ProviderUnavailableError
from project.services.ai.deepseek_provider import DeepSeekProvider
from project.services.ai.factory import (
    DEFAULT_FALLBACK_CHAIN,
    _NullProvider,
    configured_providers,
    fallback_chain_names,
    get_ai_provider,
)
from project.services.ai.fallback import FallbackChainProvider, is_fallback_eligible
from project.services.ai.local_provider import LocalProvider
from project.services.ai.openai_provider import OpenAIProvider

# Configuration neutre : aucune clé ni URL héritée de l'environnement du poste
# ou de la CI ne doit influencer l'aiguillage testé.
NO_PROVIDER = dict(
    DEEPSEEK_API_KEY="", OPENAI_API_KEY="", ANTHROPIC_API_KEY="", AI_LOCAL_BASE_URL="",
    AI_FALLBACK_CHAIN="deepseek,openai,anthropic,local",
)
ALL_PROVIDERS = dict(
    DEEPSEEK_API_KEY="sk-fake-deepseek", OPENAI_API_KEY="sk-fake-openai",
    ANTHROPIC_API_KEY="sk-fake-anthropic", AI_LOCAL_BASE_URL="http://localhost:11434/v1",
)


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


@override_settings(**NO_PROVIDER)
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


# ---------------------------------------------------------------------------
# AI_FALLBACK_CHAIN — configuration
# ---------------------------------------------------------------------------
def _names(provider) -> list[str]:
    return [p.name for p in provider.providers]


@override_settings(AI_BACKEND="auto", **NO_PROVIDER)
class FallbackChainConfigTests(SimpleTestCase):
    def test_default_chain_is_deepseek_openai_anthropic_local(self):
        self.assertEqual(DEFAULT_FALLBACK_CHAIN, ("deepseek", "openai", "anthropic", "local"))
        with override_settings(AI_FALLBACK_CHAIN=""):
            self.assertEqual(fallback_chain_names(), ["deepseek", "openai", "anthropic", "local"])

    @override_settings(**ALL_PROVIDERS)
    def test_all_configured_providers_are_chained_in_order(self):
        provider = get_ai_provider()
        self.assertIsInstance(provider, FallbackChainProvider)
        self.assertEqual(_names(provider), ["deepseek", "openai", "anthropic", "local"])

    @override_settings(**ALL_PROVIDERS, AI_FALLBACK_CHAIN=" Local , anthropic,deepseek ")
    def test_custom_order_is_respected(self):
        self.assertEqual(_names(get_ai_provider()), ["local", "anthropic", "deepseek"])

    @override_settings(**ALL_PROVIDERS, AI_FALLBACK_CHAIN=["openai", "deepseek"])
    def test_chain_accepts_a_list(self):
        self.assertEqual(_names(get_ai_provider()), ["openai", "deepseek"])

    @override_settings(DEEPSEEK_API_KEY="sk-fake-deepseek", ANTHROPIC_API_KEY="sk-fake-anthropic")
    def test_unconfigured_providers_are_ignored(self):
        """OpenAI (pas de clé) et Local (pas d'URL) sont écartés de la chaîne."""
        self.assertEqual(_names(get_ai_provider()), ["deepseek", "anthropic"])

    @override_settings(ANTHROPIC_API_KEY="sk-fake-anthropic")
    def test_single_configured_provider_is_returned_unwrapped(self):
        self.assertIsInstance(get_ai_provider(), AnthropicProvider)

    @override_settings(**ALL_PROVIDERS, AI_FALLBACK_CHAIN="deepseek,mistral,openai")
    def test_unknown_names_are_ignored_with_a_warning(self):
        with self.assertLogs("project.services.ai.factory", level="WARNING") as logs:
            provider = get_ai_provider()
        self.assertEqual(_names(provider), ["deepseek", "openai"])
        self.assertIn("mistral", "".join(logs.output))

    @override_settings(**ALL_PROVIDERS, AI_FALLBACK_CHAIN="claude,anthropic,ollama,local,claude")
    def test_aliases_and_duplicates_are_deduplicated(self):
        self.assertEqual(_names(get_ai_provider()), ["anthropic", "local"])

    @override_settings(OPENAI_API_KEY="sk-fake-openai", AI_FALLBACK_CHAIN="deepseek,local")
    def test_provider_outside_the_chain_is_never_used(self):
        """Une clé OpenAI présente mais absente de la chaîne ne doit pas être utilisée."""
        self.assertIsInstance(get_ai_provider(), _NullProvider)

    @override_settings(AI_FALLBACK_CHAIN="mistral,gemini")
    def test_chain_with_only_unknown_names_gives_null_provider(self):
        with self.assertLogs("project.services.ai.factory", level="WARNING"):
            self.assertEqual(configured_providers(), [])
            self.assertIsInstance(get_ai_provider(), _NullProvider)

    def test_explicit_backends_bypass_the_chain(self):
        for backend, cls in (("anthropic", AnthropicProvider), ("claude", AnthropicProvider),
                             ("ollama", LocalProvider), ("OpenAI", OpenAIProvider)):
            with override_settings(AI_BACKEND=backend):
                self.assertIsInstance(get_ai_provider(), cls, backend)

    @override_settings(AI_BACKEND="mistral", DEEPSEEK_API_KEY="sk-fake-deepseek")
    def test_unknown_backend_falls_back_to_auto(self):
        with self.assertLogs("project.services.ai.factory", level="WARNING"):
            self.assertIsInstance(get_ai_provider(), DeepSeekProvider)

    def test_null_provider_raises_an_eligible_error(self):
        with self.assertRaises(ProviderUnavailableError):
            _NullProvider().generate([AIMessage("user", "x")])


# ---------------------------------------------------------------------------
# Erreurs éligibles à la bascule
# ---------------------------------------------------------------------------
_REQUEST = httpx.Request("POST", "https://api.example.test/v1/chat/completions")


def _status_error(cls, status):
    return cls("erreur simulée", response=httpx.Response(status, request=_REQUEST), body=None)


class FallbackEligibilityTests(SimpleTestCase):
    def test_provider_side_errors_are_eligible(self):
        eligible = [
            _status_error(openai.AuthenticationError, 401),
            _status_error(openai.APIStatusError, 402),          # solde épuisé (DeepSeek)
            _status_error(openai.PermissionDeniedError, 403),
            _status_error(openai.NotFoundError, 404),           # modèle introuvable
            _status_error(openai.RateLimitError, 429),
            _status_error(openai.InternalServerError, 500),
            _status_error(openai.InternalServerError, 503),
            openai.APIConnectionError(request=_REQUEST),
            openai.APITimeoutError(request=_REQUEST),
            httpx.ConnectError("refusé"),
            httpx.ReadTimeout("trop long"),
            TimeoutError("timeout"),
            ConnectionResetError("reset"),
            ProviderUnavailableError("client non initialisé"),
        ]
        for exc in eligible:
            self.assertTrue(is_fallback_eligible(exc), repr(exc))

    def test_request_and_programming_errors_are_not_eligible(self):
        not_eligible = [
            _status_error(openai.BadRequestError, 400),              # prompt refusé / trop long
            _status_error(openai.APIStatusError, 413),
            _status_error(openai.UnprocessableEntityError, 422),
            ValueError("json invalide"),
            TypeError("argument inattendu"),
            KeyError("choices"),
            RuntimeError("erreur inconnue"),
        ]
        for exc in not_eligible:
            self.assertFalse(is_fallback_eligible(exc), repr(exc))

    def test_status_code_is_read_from_the_response_when_absent_on_the_error(self):
        exc = RuntimeError("HTTP error")
        exc.response = SimpleNamespace(status_code=503)
        self.assertTrue(is_fallback_eligible(exc))
        exc.response = SimpleNamespace(status_code=400)
        self.assertFalse(is_fallback_eligible(exc))


# ---------------------------------------------------------------------------
# Bascule à l'exécution
# ---------------------------------------------------------------------------
class _StubProvider(AIProvider):
    """Provider factice : rejoue une erreur ou une réponse, sans aucun appel réseau."""

    def __init__(self, name, *, error=None, text="ok", available=True, json=True, chunks=None, stream_error=None):
        self.name = name
        self.error, self.text, self.available, self.json = error, text, available, json
        self.chunks, self.stream_error = chunks, stream_error
        self.calls: list[dict] = []
        self.stream_calls = 0

    def is_available(self):
        return self.available

    def supports_json_mode(self):
        return self.json

    def generate(self, messages, *, temperature=0.2, max_tokens=None, json_mode=False, **kwargs):
        self.calls.append({"json_mode": json_mode})
        if self.error is not None:
            raise self.error
        return AIResponse(text=self.text, provider=self.name)

    def generate_stream(self, messages, *, temperature=0.2, max_tokens=None, **kwargs):
        self.stream_calls += 1
        if self.error is not None:
            raise self.error
        for chunk in self.chunks or []:
            yield chunk
        if self.stream_error is not None:
            raise self.stream_error


MESSAGES = [AIMessage("user", "Bonjour")]


class FallbackChainRuntimeTests(SimpleTestCase):
    def setUp(self):
        # Les bascules sont logguées en WARNING : on garde la sortie des tests propre.
        patcher = mock.patch("project.services.ai.fallback.logger")
        self.logger = patcher.start()
        self.addCleanup(patcher.stop)

    def test_primary_answers_without_fallback(self):
        first, second = _StubProvider("deepseek", text="A"), _StubProvider("openai", text="B")
        response = FallbackChainProvider([first, second]).generate(MESSAGES)
        self.assertEqual((response.text, response.provider), ("A", "deepseek"))
        self.assertEqual(response.metadata["fallback_level"], 0)
        self.assertEqual(second.calls, [])

    def test_eligible_error_switches_to_the_next_provider(self):
        first = _StubProvider("deepseek", error=_status_error(openai.RateLimitError, 429))
        second = _StubProvider("openai", text="B")
        response = FallbackChainProvider([first, second]).generate(MESSAGES)
        self.assertEqual((response.text, response.provider), ("B", "openai"))
        self.assertEqual(response.metadata["fallback_level"], 1)
        self.assertEqual(len(first.calls), 1)

    def test_chain_walks_through_several_failing_providers(self):
        chain = FallbackChainProvider([
            _StubProvider("deepseek", error=openai.APITimeoutError(request=_REQUEST)),
            _StubProvider("openai", error=_status_error(openai.AuthenticationError, 401)),
            _StubProvider("anthropic", error=ProviderUnavailableError("SDK absent")),
            _StubProvider("local", text="D"),
        ])
        response = chain.generate(MESSAGES)
        self.assertEqual((response.provider, response.metadata["fallback_level"]), ("local", 3))

    def test_non_eligible_error_is_raised_without_trying_the_next_provider(self):
        error = _status_error(openai.BadRequestError, 400)
        first, second = _StubProvider("deepseek", error=error), _StubProvider("openai", text="B")
        with self.assertRaises(openai.BadRequestError) as ctx:
            FallbackChainProvider([first, second]).generate(MESSAGES)
        self.assertIs(ctx.exception, error)
        self.assertEqual(second.calls, [])

    def test_programming_error_is_not_masked_by_a_fallback(self):
        first, second = _StubProvider("deepseek", error=TypeError("bug")), _StubProvider("openai")
        with self.assertRaises(TypeError):
            FallbackChainProvider([first, second]).generate(MESSAGES)
        self.assertEqual(second.calls, [])

    def test_last_error_is_raised_when_every_provider_fails(self):
        last = _status_error(openai.InternalServerError, 502)
        chain = FallbackChainProvider([
            _StubProvider("deepseek", error=_status_error(openai.RateLimitError, 429)),
            _StubProvider("openai", error=last),
        ])
        with self.assertRaises(openai.InternalServerError) as ctx:
            chain.generate(MESSAGES)
        self.assertIs(ctx.exception, last)

    def test_unavailable_provider_is_skipped(self):
        first, second = _StubProvider("deepseek", available=False), _StubProvider("openai", text="B")
        response = FallbackChainProvider([first, second]).generate(MESSAGES)
        self.assertEqual(response.provider, "openai")
        self.assertEqual(first.calls, [])

    def test_no_available_provider_raises_provider_unavailable(self):
        chain = FallbackChainProvider([_StubProvider("deepseek", available=False)])
        self.assertFalse(chain.is_available())
        with self.assertRaises(ProviderUnavailableError):
            chain.generate(MESSAGES)

    def test_json_mode_is_only_requested_from_providers_that_support_it(self):
        first = _StubProvider("deepseek", error=TimeoutError("timeout"))
        second = _StubProvider("local", json=False)
        response = FallbackChainProvider([first, second]).generate(MESSAGES, json_mode=True)
        self.assertEqual(first.calls, [{"json_mode": True}])
        self.assertEqual(second.calls, [{"json_mode": False}])
        self.assertTrue(response.metadata["requested_json_mode"])

    # -- streaming -------------------------------------------------------
    def test_stream_falls_back_before_the_first_chunk(self):
        first = _StubProvider("deepseek", error=openai.APIConnectionError(request=_REQUEST))
        second = _StubProvider("openai", chunks=["Bon", "jour"])
        self.assertEqual(list(FallbackChainProvider([first, second]).generate_stream(MESSAGES)), ["Bon", "jour"])

    def test_stream_falls_back_on_an_empty_stream(self):
        first, second = _StubProvider("deepseek", chunks=[]), _StubProvider("openai", chunks=["ok"])
        self.assertEqual(list(FallbackChainProvider([first, second]).generate_stream(MESSAGES)), ["ok"])

    def test_stream_error_after_the_first_chunk_is_raised_without_replay(self):
        first = _StubProvider("deepseek", chunks=["Bon"], stream_error=_status_error(openai.InternalServerError, 500))
        second = _StubProvider("openai", chunks=["Bonjour"])
        received = []
        with self.assertRaises(openai.InternalServerError):
            for chunk in FallbackChainProvider([first, second]).generate_stream(MESSAGES):
                received.append(chunk)
        self.assertEqual(received, ["Bon"])       # rien n'est réémis par le second provider
        self.assertEqual(second.stream_calls, 0)

    def test_stream_non_eligible_error_is_raised_without_fallback(self):
        first = _StubProvider("deepseek", error=_status_error(openai.BadRequestError, 400))
        second = _StubProvider("openai", chunks=["ok"])
        with self.assertRaises(openai.BadRequestError):
            list(FallbackChainProvider([first, second]).generate_stream(MESSAGES))
        self.assertEqual(second.stream_calls, 0)


# ---------------------------------------------------------------------------
# Règle métier préservée : un service retombe toujours sur son heuristique
# ---------------------------------------------------------------------------
class HeuristicPreservedTests(SimpleTestCase):
    def _estimate(self, provider):
        from project.services.ai.services.effort_estimation import EffortEstimationService

        task = SimpleNamespace(pk=1, title="Corriger l'export", description="", task_type="BUG", priority="HIGH",
                               story_points=None, project_id=None, project=None)
        with mock.patch("project.services.ai.services.effort_estimation.get_ai_provider", return_value=provider), \
                mock.patch("project.services.ai.fallback.logger"), \
                mock.patch("project.services.ai.services.effort_estimation.logger"):
            return EffortEstimationService.estimate_task(task), EffortEstimationService._heuristic(task)

    def test_service_uses_heuristic_when_every_provider_is_down(self):
        chain = FallbackChainProvider([
            _StubProvider("deepseek", error=_status_error(openai.InternalServerError, 503)),
            _StubProvider("openai", error=TimeoutError("timeout")),
        ])
        estimate, baseline = self._estimate(chain)
        self.assertEqual(estimate, baseline)

    def test_service_uses_heuristic_on_a_non_eligible_error(self):
        second = _StubProvider("openai", text='{"estimate_hours": 99}')
        chain = FallbackChainProvider([_StubProvider("deepseek", error=_status_error(openai.BadRequestError, 400)), second])
        estimate, baseline = self._estimate(chain)
        self.assertEqual(estimate, baseline)
        self.assertEqual(second.calls, [])

    def test_service_uses_the_fallback_provider_answer(self):
        second = _StubProvider("openai", text='{"estimate_hours": 12, "optimistic_hours": 9, "pessimistic_hours": 20, '
                                              '"confidence": "high", "rationale": "Analyse IA"}')
        chain = FallbackChainProvider([_StubProvider("deepseek", error=_status_error(openai.RateLimitError, 429)), second])
        estimate, _ = self._estimate(chain)
        self.assertEqual((estimate.estimate_hours, estimate.confidence), (12.0, "high"))
