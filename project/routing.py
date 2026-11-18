from channels.security.websocket import WebsocketDenier
from django.urls import re_path

from project.consumers import ChatConsumer, ChannelChatConsumer, UserEventsConsumer

websocket_urlpatterns = [
    re_path(r"ws/channels/(?P<channel_id>\d+)/$", ChannelChatConsumer.as_asgi()),
    re_path(r"ws/chat/(?P<channel_id>\d+)/$", ChatConsumer.as_asgi()),
    re_path(r"ws/me/$", UserEventsConsumer.as_asgi()),
    # Chemin inconnu : refus propre (403) au lieu d'une erreur 500 « No route found ».
    re_path(r"", WebsocketDenier.as_asgi()),
]