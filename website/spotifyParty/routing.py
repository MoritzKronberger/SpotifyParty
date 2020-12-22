# chat/routing.py
from django.urls import re_path
from django.conf.urls import url

from . import consumers

websocket_urlpatterns = [
    re_path(r'(?P<room_name>\w+)/$', consumers.ChatConsumer.as_asgi()),
]
