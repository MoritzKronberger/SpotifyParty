"""
ASGI config for website project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/3.1/howto/deployment/asgi/
"""

import os

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application
from channels.auth import AuthMiddlewareStack
from django.core.asgi import get_asgi_application
import spotifyParty.routing

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'website.settings')

application = get_asgi_application()

application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": AuthMiddlewareStack(
        URLRouter(
            # sub routing into spotifyParty.routing
            spotifyParty.routing.websocket_urlpatterns
        )
    ),
})
