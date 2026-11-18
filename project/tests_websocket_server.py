"""
Serveur WebSocket de production (gunicorn + worker Uvicorn DevFlow).

Un navigateur qui envoie plus de 8 Kio de cookies voyait ``/ws/me/`` refusé en 400
(« WebSocket connection … failed » en boucle) alors que les pages HTTP fonctionnaient :
la bibliothèque ``websockets`` limite chaque ligne d'en-tête à 8 Kio par défaut.

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_websocket_server
"""

import base64
import os
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

BASE_DIR = Path(settings.BASE_DIR)
WORKER = "ProjectFlow.uvicorn_worker.UvicornWorker"

# Application ASGI minimale : accepte toute connexion WebSocket puis la ferme.
ASGI_APP = textwrap.dedent('''
    async def app(scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        elif scope["type"] == "websocket":
            await receive()
            await send({"type": "websocket.accept"})
            await send({"type": "websocket.close", "code": 1000})
        else:
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})
''')


def clean_env(**extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("WEBSOCKETS_")}
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(BASE_DIR), env.get("PYTHONPATH", "")]))
    env.update(extra)
    return env


def header_limits(**env) -> list[str]:
    code = (
        "import warnings; warnings.simplefilter('ignore')\n"
        "import ProjectFlow.uvicorn_worker as w, uvicorn.workers\n"  # même ordre que gunicorn (-k d'abord)
        "import websockets.http11 as sansio, websockets.legacy.http as legacy\n"
        "print(sansio.MAX_LINE_LENGTH, legacy.MAX_LINE_LENGTH, issubclass(w.UvicornWorker, uvicorn.workers.UvicornWorker))"
    )
    out = subprocess.run([sys.executable, "-c", code], env=clean_env(**env), capture_output=True, text=True,
                         cwd=BASE_DIR, timeout=60)
    assert out.returncode == 0, out.stderr
    return out.stdout.split()


class DevflowWorkerConfigTests(SimpleTestCase):
    def test_worker_raises_the_websocket_header_limit(self):
        self.assertEqual(header_limits(), ["32768", "32768", "True"])

    def test_explicit_environment_value_wins(self):
        self.assertEqual(header_limits(WEBSOCKETS_MAX_LINE_LENGTH="16384")[:2], ["16384", "16384"])

    def test_production_compose_uses_the_devflow_worker(self):
        active = [line for line in (BASE_DIR / "docker-compose.yml").read_text().splitlines()
                  if not line.lstrip().startswith("#")]
        workers = [line.split("-k", 1)[1].strip() for line in active if line.strip().startswith("-k ")]
        self.assertEqual(workers, [WORKER])


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def handshake_status(port: int, cookie_bytes: int) -> str:
    """Première ligne de réponse à une poignée de main WebSocket portant ``cookie_bytes`` de cookies."""
    key = base64.b64encode(os.urandom(16)).decode()
    request = (
        f"GET /ws/me/ HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
        f"Cookie: sessionid=x; analytics={'a' * cookie_bytes}\r\n\r\n"
    )
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        sock.sendall(request.encode())
        return sock.recv(64).decode("latin-1").split("\r\n", 1)[0]


class WebsocketHandshakeTests(SimpleTestCase):
    """Vrai serveur gunicorn + Uvicorn (sous-processus) : pas de simulation de la poignée de main."""

    def serve(self, worker: str) -> int:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        Path(tmp.name, "probe_app.py").write_text(ASGI_APP)
        port = free_port()
        env = clean_env(PYTHONPATH=os.pathsep.join([tmp.name, str(BASE_DIR)]))
        proc = subprocess.Popen(
            [sys.executable, "-m", "gunicorn", "probe_app:app", "-k", worker, "--workers", "1",
             "--bind", f"127.0.0.1:{port}", "--log-level", "warning"],
            cwd=tmp.name, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )

        def stop():
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            proc.stderr.close()

        self.addCleanup(stop)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                self.fail(f"gunicorn arrêté : {proc.stderr.read().decode(errors='replace')[-2000:]}")
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
                return port
            except OSError:
                time.sleep(0.1)
        self.fail("gunicorn n'a pas démarré en 30 s")

    def test_devflow_worker_accepts_large_cookies(self):
        port = self.serve(WORKER)
        for size in (100, 9_000, 30_000):
            with self.subTest(cookie_bytes=size):
                self.assertIn(" 101 ", handshake_status(port, size))

    def test_standard_worker_refuses_them(self):
        """Témoin : le défaut corrigé existe bien avec le worker Uvicorn d'origine."""
        port = self.serve("uvicorn.workers.UvicornWorker")
        self.assertIn(" 101 ", handshake_status(port, 100))
        self.assertIn(" 400 ", handshake_status(port, 9_000))
