from django.urls import path

from .views import LoginView, LogoutView, PasswordView, UsersView


urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("password/", PasswordView.as_view(), name="password"),
    path("users/", UsersView.as_view(), name="users"),
]
