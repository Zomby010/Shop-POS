from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("products/", include("apps.catalog.urls")),
    path("sell/", include("apps.sales.urls")),
    path("stock/", include("apps.inventory.urls")),
    path("people/", include("apps.partners.urls")),
    path("documents/", include("apps.documents.urls")),
    path("money/", include("apps.finance.urls")),
    path("", include("apps.core.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
