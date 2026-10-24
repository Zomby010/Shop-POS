from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.generic import RedirectView

from . import quick_add, views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("login/", auth_views.LoginView.as_view(redirect_authenticated_user=True), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("settings/", views.settings_view, name="settings"),
    path("people/users/", views.user_list, name="user_list"),
    path("people/users/new/", views.user_edit, name="user_new"),
    path("people/users/<int:pk>/", views.user_edit, name="user_edit"),
    path("people/roles/", views.roles_view, name="roles"),
    path("settings/users/", RedirectView.as_view(pattern_name="user_list")),
    path("settings/audit-log/", views.audit_log, name="audit_log"),
    path("quick-add/<str:kind>/", quick_add.quick_add, name="quick_add"),
]
