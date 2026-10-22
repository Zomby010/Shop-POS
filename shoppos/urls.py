from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

urlpatterns = [
    path("admin/", admin.site.urls),
    path("products/", include("apps.catalog.urls")),
    path("sell/", include("apps.sales.urls")),
    path("stock/", include("apps.inventory.urls")),
    path("people/", include("apps.partners.urls")),
    path("documents/", include("apps.documents.urls")),
    path("money/", include("apps.finance.urls")),
    path("", include("apps.core.urls")),
    # The POS runs on one laptop, so Django serves the uploaded logo itself.
    re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
]
