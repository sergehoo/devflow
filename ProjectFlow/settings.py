"""
Fichier conservé uniquement pour rétro-compatibilité.

Le projet utilise désormais le PACKAGE ``ProjectFlow.settings`` (le dossier
``ProjectFlow/settings/`` avec ses ``base.py``, ``dev.py``, ``prod.py``,
``test.py`` et son ``__init__.py``).

Comme Python privilégie le package au module .py homonyme, ce fichier
n'est jamais chargé. Il est conservé en place pour ne pas casser un
``DJANGO_SETTINGS_MODULE=ProjectFlow.settings`` historique éventuel et
pour lever une erreur explicite si quelqu'un l'importait directement.

Ne PAS y mettre de configuration ni de secret.
"""

raise ImportError(
    "ProjectFlow/settings.py est obsolete. Utilisez le package "
    "ProjectFlow.settings (dossier ProjectFlow/settings/) avec "
    "DJANGO_ENV=dev|prod|test."
)
