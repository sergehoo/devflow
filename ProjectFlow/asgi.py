import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ProjectFlow.settings")

from django.core.asgi import get_asgi_application

django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from project.middleware_websocket import WebsocketOriginMiddleware
from project.routing import websocket_urlpatterns

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    # Origine vérifiée AVANT la session : une page d'un sous-domaine voisin ne peut pas
    # ouvrir un WebSocket avec les cookies de l'utilisateur (CSWSH).
    "websocket": WebsocketOriginMiddleware(
        AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
    ),
})
