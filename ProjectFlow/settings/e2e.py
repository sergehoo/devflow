"""
Settings des tests E2E Playwright (frontend/e2e) — environnement LOCAL uniquement.

Base SQLite jetable dans ``frontend/e2e/.state``, tâches Celery exécutées dans la
requête, couche Channels en mémoire, e-mails écrits dans des fichiers, IA désactivée
(heuristiques), destinations locales autorisées pour les webhooks et la messagerie.
``E2E_MODE`` autorise la commande ``e2e_fixtures`` (refusée avec tout autre settings).

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.e2e python manage.py e2e_fixtures seed …
"""
import os
from pathlib import Path

from .test import *  # noqa: F401,F403
from .test import BASE_DIR, CSRF_TRUSTED_ORIGINS

E2E_MODE = True
E2E_STATE = Path(os.getenv("E2E_STATE_DIR", Path(BASE_DIR) / "frontend" / "e2e" / ".state"))
E2E_STATE.mkdir(parents=True, exist_ok=True)

DEBUG = True
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
CSRF_TRUSTED_ORIGINS = [*CSRF_TRUSTED_ORIGINS, "http://127.0.0.1:5180", "http://localhost:5180"]
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(E2E_STATE / "e2e.sqlite3")}}
MEDIA_ROOT = str(E2E_STATE / "media")
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = False
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
EMAIL_BACKEND = "django.core.mail.backends.filebased.EmailBackend"
EMAIL_FILE_PATH = str(E2E_STATE / "mail")
DEFAULT_FROM_EMAIL = "support@devflow.test"

# Récepteur de webhooks et serveurs de messagerie de test sur 127.0.0.1.
TICKET_WEBHOOK_ALLOW_PRIVATE = True
TICKET_MAIL_ALLOW_PRIVATE_HOSTS = True
TICKETING_TRUSTED_PROXIES = 0
TICKETING_AUTH_FAILURE_LIMIT = 50
