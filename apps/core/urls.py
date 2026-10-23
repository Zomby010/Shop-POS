from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("login/", auth_views.LoginView.as_view(redirect_authenticated_user=True), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("settings/", views.settings_view, name="settings"),
    path("settings/users/", views.user_list, name="user_list"),
    path("settings/users/new/", views.user_edit, name="user_new"),
    path("settings/users/<int:pk>/", views.user_edit, name="user_edit"),
    path("settings/audit-log/", views.audit_log, name="audit_log"),
]
