from django.urls import path

from . import views

app_name = "finance"
urlpatterns = [
    path("", views.summary_view, name="reports"),
    path("profit/", views.profit_view, name="profit"),
    path("sales/", views.sales_view, name="sales"),
    path("products/", views.products_view, name="products"),
    path("movers/", views.movers_view, name="movers"),
    path("stock-movement/", views.stock_movement_view, name="stock_movement"),
    path("purchased/", views.purchased_view, name="purchased"),
    path("stock-value/", views.stock_value_view, name="stock_value"),
    path("expenses/", views.expenses, name="expenses"),
    path("expenses/<int:pk>/delete/", views.expense_delete, name="expense_delete"),
    path("backup/", views.backup_view, name="backup"),
    path("backup/<str:name>", views.backup_download, name="backup_download"),
]
