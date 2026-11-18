"""
Worker gunicorn → Uvicorn de DevFlow :

    gunicorn ProjectFlow.asgi:application -k ProjectFlow.uvicorn_worker.UvicornWorker

Les poignées de main WebSocket (``/ws/me/``, ``/ws/channels/<id>/``) sont analysées par
la bibliothèque ``websockets``, qui limite chaque ligne d'en-tête à 8 Kio ; les requêtes
HTTP ordinaires n'ont pas cette limite. Un navigateur qui envoie plus de 8 Kio de cookies
(applications voisines sur le domaine parent, outils de mesure…) voyait donc toutes ses
connexions temps réel refusées (400, « WebSocket connection … failed » en boucle) alors
que le reste de l'application fonctionnait.

La limite est relevée à 32 Kio : c'est aussi le plafond de ligne du tampon de lecture de
``websockets`` (``read_limit // 2``), une valeur supérieure serait sans effet. Elle doit
être posée avant le premier import de ``websockets`` : gunicorn charge ce module dans le
processus maître, avant de créer les workers. Une valeur déjà définie dans
l'environnement (``WEBSOCKETS_MAX_LINE_LENGTH``) reste prioritaire.
"""

import os

WEBSOCKET_HEADER_LINE_LIMIT = 32 * 1024

os.environ.setdefault("WEBSOCKETS_MAX_LINE_LENGTH", str(WEBSOCKET_HEADER_LINE_LIMIT))

from uvicorn.workers import UvicornWorker as _UvicornWorker  # noqa: E402  (après la variable)


class UvicornWorker(_UvicornWorker):
    """Worker Uvicorn standard ; seule la limite d'en-tête WebSocket change (voir le module)."""
