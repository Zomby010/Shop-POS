from django.urls import path

from apps.core.stubs import coming_soon

app_name = "inventory"
urlpatterns = [
    path("home/", coming_soon("home"), name="home"),
]
