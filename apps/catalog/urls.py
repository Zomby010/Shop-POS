from django.urls import path

from . import views

app_name = "catalog"
urlpatterns = [
    path("", views.product_list, name="product_list"),
    path("new/", views.product_edit, name="product_new"),
    path("<int:pk>/", views.product_edit, name="product_edit"),
    path("categories/", views.categories, name="categories"),
    path("quick-sale-categories/", views.quick_categories, name="quick_categories"),
    path("import/", views.import_products, name="import"),
    path("import/template.xlsx", views.import_template, name="import_template"),
    path("export.xlsx", views.export_products, name="export"),
]
