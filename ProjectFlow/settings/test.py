"""
Settings de test rapides (SQLite en mémoire, sans GIS/Weasyprint).
À utiliser avec : DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test
"""
from .base import *  # noqa: F401,F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# On retire les apps qui requièrent des libs natives en environnement de test
INSTALLED_APPS = [a for a in INSTALLED_APPS if a not in {
    "django.contrib.gis",
    "weasyprint",
}]

# Désactiver l'IA externe par défaut en tests
AI_BACKEND = "none"
