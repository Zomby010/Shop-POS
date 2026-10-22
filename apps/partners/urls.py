from django.urls import path

from apps.core.stubs import coming_soon

app_name = "partners"
urlpatterns = [
    path("customer_list/", coming_soon("customer_list"), name="customer_list"),
]
