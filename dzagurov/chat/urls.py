from django.urls import path
from . import views_api

app_name = "chat"

urlpatterns = [
    path("api/bootstrap/", views_api.chat_bootstrap, name="chat_api_bootstrap"),
    path("api/messages/", views_api.chat_messages, name="chat_api_messages"),
    path("api/send/",     views_api.chat_send,      name="chat_api_send"),
]
