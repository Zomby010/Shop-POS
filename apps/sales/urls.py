from django.urls import path

from apps.core.stubs import coming_soon

app_name = "sales"
urlpatterns = [
    path("sell/", coming_soon("sell"), name="sell"),
    path("held/", coming_soon("held"), name="held"),
    path("test_print/", coming_soon("test_print"), name="test_print"),
]
