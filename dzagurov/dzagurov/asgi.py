import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dzagurov.settings")

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from django.urls import path
from chat.consumers import ChatConsumer

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter([
            path("ws/chat/<uuid:thread_uuid>/", ChatConsumer.as_asgi()),
        ])
    ),
})
