from django.urls import path

from apps.core.stubs import coming_soon

app_name = "documents"
urlpatterns = [
    path("", coming_soon("Invoices and quotations"), name="list"),
    path("new/", coming_soon("New document"), name="new"),
    path("<int:pk>/", coming_soon("Document"), name="detail"),
]
