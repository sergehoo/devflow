from django.urls import re_path

from project.consumers import ChatConsumer, ChannelChatConsumer

websocket_urlpatterns = [
    re_path(r"ws/channels/(?P<channel_id>\d+)/$", ChannelChatConsumer.as_asgi()),
    re_path(r"ws/channels/(?P<channel_id>\d+)/$", ChatConsumer.as_asgi()),

]