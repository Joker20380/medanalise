from django.urls import re_path
from .consumers import ThreadConsumer

websocket_urlpatterns = [
    re_path(r"^ws/chat/(?P<thread_uuid>[0-9a-f-]+)/$", ThreadConsumer.as_asgi()),
]
