"""
WebSocket — garde d'origine (CSWSH, Cross-Site WebSocket Hijacking).

Une page d'un sous-domaine voisin (même site, cookies ``SameSite=Lax`` envoyés) ne doit
pas pouvoir ouvrir ``/ws/me/``, ``/ws/channels/<id>/`` ni ``/ws/chat/<id>/`` avec la
session de l'utilisateur. Les poignées de main passent par la pile ASGI complète
(``ProjectFlow.asgi.application``) avec un vrai cookie de session.

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_websocket_origin
"""

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from project import models as dm
from project.middleware_websocket import DENIED_CLOSE_CODE, origin_allowed
from ProjectFlow.asgi import application

User = get_user_model()

HOST = "flow.example.test"
SAME_ORIGIN = "https://flow.example.test"
SIBLING_ORIGIN = "https://storage-flow.example.test"
GUARD_LOGGER = "project.middleware_websocket"


@override_settings(CSRF_TRUSTED_ORIGINS=[])
class OriginAllowedTests(SimpleTestCase):
    def test_same_host_accepted(self):
        for origin, host in (
            (SAME_ORIGIN, HOST),
            ("https://FLOW.Example.test", HOST),
            (SAME_ORIGIN, "flow.example.test:443"),
            ("http://flow.example.test:8000", "flow.example.test:8000"),
            ("http://127.0.0.1:5180", "127.0.0.1:5180"),  # proxy Vite de dev (Host conservé)
            ("http://[::1]:8000", "[::1]:8000"),
        ):
            with self.subTest(origin=origin, host=host):
                self.assertTrue(origin_allowed(origin, host))

    def test_foreign_or_malformed_refused(self):
        for origin, host in (
            (SIBLING_ORIGIN, HOST),
            ("https://example.test", HOST),
            ("https://flow.example.test.evil.test", HOST),
            ("https://flow.example.test:8443", HOST),
            ("http://flow.example.test:443", HOST),
            ("http://127.0.0.1:5173", "127.0.0.1:5180"),
            ("null", HOST),
            ("", HOST),
            ("flow.example.test", HOST),
            ("chrome-extension://abcdef", HOST),
            ("https://user@flow.example.test", HOST),
            ("https://flow.example.test/path", HOST),
            ("https://flow.example.test:99999", HOST),
            (SAME_ORIGIN, None),
            (SAME_ORIGIN, ""),
            (SAME_ORIGIN, "flow.example.test/evil"),
            (SAME_ORIGIN, "user@flow.example.test"),
        ):
            with self.subTest(origin=origin, host=host):
                self.assertFalse(origin_allowed(origin, host))

    @override_settings(CSRF_TRUSTED_ORIGINS=["https://app.example.test", "http://localhost:5180"])
    def test_exact_csrf_trusted_origins_accepted(self):
        self.assertTrue(origin_allowed("https://app.example.test", HOST))
        self.assertTrue(origin_allowed("http://localhost:5180", HOST))
        self.assertFalse(origin_allowed("http://localhost:5181", HOST))
        self.assertFalse(origin_allowed("http://app.example.test", HOST))

    @override_settings(CSRF_TRUSTED_ORIGINS=["https://*.example.test"])
    def test_wildcard_csrf_trusted_origins_ignored(self):
        self.assertFalse(origin_allowed(SIBLING_ORIGIN, HOST))
        self.assertTrue(origin_allowed(SAME_ORIGIN, HOST))


@override_settings(
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
    CSRF_TRUSTED_ORIGINS=[],
)
class WebsocketOriginHandshakeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@a.test", "pw-12345678")
        cls.ws_a = dm.Workspace.objects.create(name="Tenant A", owner=cls.alice)
        dm.UserProfile.objects.create(user=cls.alice, workspace=cls.ws_a)
        dm.TeamMembership.objects.create(user=cls.alice, workspace=cls.ws_a)
        cls.channel = dm.DirectChannel.objects.create(workspace=cls.ws_a, name="general-a", is_private=True)
        dm.ChannelMembership.objects.create(channel=cls.channel, user=cls.alice)

    def setUp(self):
        self.client.force_login(self.alice)
        session_key = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        self.cookie = f"{settings.SESSION_COOKIE_NAME}={session_key}".encode()

    @property
    def chat_paths(self):
        return (f"/ws/channels/{self.channel.pk}/", f"/ws/chat/{self.channel.pk}/")

    def handshake(self, path, origins=(), hosts=(HOST,)):
        """Poignée de main via la pile ASGI complète ; renvoie (accepté, code, 1er message)."""
        headers = [(b"host", h.encode()) for h in hosts] + [(b"cookie", self.cookie)]
        headers += [(b"origin", o.encode()) for o in origins]

        async def run():
            ws = WebsocketCommunicator(application, path, headers=headers)
            connected, code = await ws.connect(timeout=3)
            first = None
            if connected:
                if path == "/ws/me/":
                    first = await ws.receive_json_from(timeout=3)
                await ws.disconnect()
            return connected, code, first

        return async_to_sync(run)()

    def assert_refused(self, path, **kw):
        with self.assertLogs(GUARD_LOGGER, "WARNING"):
            connected, code, _ = self.handshake(path, **kw)
        self.assertEqual((connected, code), (False, DENIED_CLOSE_CODE), path)

    def test_same_origin_accepted_with_session(self):
        connected, _, hello = self.handshake("/ws/me/", origins=(SAME_ORIGIN,))
        self.assertTrue(connected)
        self.assertEqual(hello, {"type": "hello", "user_id": self.alice.pk})
        for path in self.chat_paths:
            with self.subTest(path=path):
                self.assertTrue(self.handshake(path, origins=(SAME_ORIGIN,))[0])

    def test_sibling_subdomain_refused_despite_valid_session(self):
        for path in ("/ws/me/", *self.chat_paths):
            with self.subTest(path=path):
                self.assert_refused(path, origins=(SIBLING_ORIGIN,))

    def test_missing_origin_accepted(self):
        connected, _, hello = self.handshake("/ws/me/")
        self.assertTrue(connected)
        self.assertEqual(hello["user_id"], self.alice.pk)
        for path in self.chat_paths:
            with self.subTest(path=path):
                self.assertTrue(self.handshake(path)[0])

    def test_vite_dev_proxy_headers_accepted(self):
        connected, _, hello = self.handshake(
            "/ws/me/", origins=("http://127.0.0.1:5180",), hosts=("127.0.0.1:5180",),
        )
        self.assertTrue(connected)
        self.assertEqual(hello["user_id"], self.alice.pk)

    def test_null_duplicate_or_hostless_origin_refused(self):
        self.assert_refused("/ws/me/", origins=("null",))
        self.assert_refused("/ws/me/", origins=(SAME_ORIGIN, SIBLING_ORIGIN))
        self.assert_refused("/ws/me/", origins=(SAME_ORIGIN, SAME_ORIGIN))
        self.assert_refused("/ws/me/", origins=(SAME_ORIGIN,), hosts=())
        self.assert_refused("/ws/me/", origins=(SAME_ORIGIN,), hosts=(HOST, "evil.test"))

    @override_settings(CSRF_TRUSTED_ORIGINS=["https://app.example.test"])
    def test_csrf_trusted_origin_accepted(self):
        connected, _, hello = self.handshake("/ws/me/", origins=("https://app.example.test",))
        self.assertTrue(connected)
        self.assertEqual(hello["user_id"], self.alice.pk)
