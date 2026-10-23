from django.urls import path

from . import views

app_name = "documents"
urlpatterns = [
    path("", views.document_list, name="list"),
    path("new/", views.document_edit, name="new"),
    path("<int:pk>/", views.document_detail, name="detail"),
    path("<int:pk>/edit/", views.document_edit, name="edit"),
    path("<int:pk>/pdf/", views.document_pdf, name="pdf"),
    path("<int:pk>/convert/", views.convert, name="convert"),
    path("<int:pk>/status/", views.set_status, name="status"),
]
