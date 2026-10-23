from django.urls import path

from . import views

app_name = "inventory"
urlpatterns = [
    path("", views.home, name="home"),
    path("purchases/", views.purchase_list, name="purchase_list"),
    path("purchases/new/", views.purchase_new, name="purchase_new"),
    path("purchases/<int:pk>/", views.purchase_detail, name="purchase_detail"),
    path("recount/", views.recount, name="recount"),
    path("loss/", views.loss, name="loss"),
    path("stock-takes/", views.stocktake_list, name="stocktakes"),
    path("stock-takes/<int:pk>/", views.stocktake, name="stocktake"),
    path("stock-takes/<int:pk>/approve/", views.stocktake_approve, name="stocktake_approve"),
    path("stock-takes/<int:pk>/cancel/", views.stocktake_cancel, name="stocktake_cancel"),
    path("loss-report/", views.loss_report, name="loss_report"),
    path("movements/", views.movements, name="movements"),
]
