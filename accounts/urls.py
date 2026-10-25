from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.register, name="register"),
    path("login/", views.user_login, name="login"),
    # Django 6 logout requires POST — rendered as a form in the navbar
    path(
        "logout/",
        auth_views.LogoutView.as_view(),
        name="logout",
    ),
    path("profile/", views.profile, name="profile"),
]
