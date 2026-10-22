from django.urls import path

from apps.core.stubs import coming_soon

app_name = "documents"
urlpatterns = [
    path("list/", coming_soon("list"), name="list"),
]
