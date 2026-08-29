from django.urls import path
from accounts.views import SignUpView
from .views import HomeView, CustomLoginView, CustomLogoutView

urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path("login/", CustomLoginView.as_view(), name="login"),
    path("signup/", SignUpView.as_view(), name="signup"),
    path("logout/", CustomLogoutView.as_view(), name="logout"),
]

