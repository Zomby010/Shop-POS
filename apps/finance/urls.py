from django.urls import path

from apps.core.stubs import coming_soon

app_name = "finance"
urlpatterns = [
    path("reports/", coming_soon("reports"), name="reports"),
    path("backup/", coming_soon("backup"), name="backup"),
]
