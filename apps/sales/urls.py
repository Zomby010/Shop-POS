from django.urls import path

from . import views

app_name = "sales"
urlpatterns = [
    path("", views.sell, name="sell"),
    path("cart/", views.cart_view, name="cart"),
    path("cart/scan/", views.scan, name="scan"),
    path("cart/add/", views.add, name="add"),
    path("cart/line/<int:pk>/", views.line_update, name="line_update"),
    path("cart/hold/", views.hold, name="hold"),
    path("cart/pay/", views.pay, name="pay"),
    path("held/", views.held_list, name="held"),
    path("held/<int:pk>/resume/", views.resume, name="resume"),
    path("receipt/<int:pk>/", views.receipt_view, name="receipt"),
    path("receipt/<int:pk>/print/", views.reprint, name="reprint"),
    path("history/", views.history, name="history"),
    path("sale/<int:pk>/", views.sale_detail, name="sale_detail"),
    path("cash-up/", views.cashup, name="cashup"),
    path("cash-up/<int:pk>/", views.cashup_detail, name="cashup_detail"),
    path("cash-ups/", views.cashup_list, name="cashup_list"),
    path("test-print/", views.test_print, name="test_print"),
]
