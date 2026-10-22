from django.urls import path

from apps.core.stubs import coming_soon

app_name = "inventory"
urlpatterns = [
    path("", coming_soon("Stock"), name="home"),
    path("purchases/new/", coming_soon("Receive stock"), name="purchase_new"),
    path("purchases/<int:pk>/", coming_soon("Purchase"), name="purchase_detail"),
]
