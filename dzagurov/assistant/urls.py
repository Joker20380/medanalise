from django.urls import path
from .views import ask

urlpatterns = [
    path("ask/", ask, name="assistant_ask"),
]
