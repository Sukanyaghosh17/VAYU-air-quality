"""
dashboard/views.py — Phase 6 frontend views
============================================
All data is fetched client-side by dashboard.js via the DRF API using
session cookies, so these views only render templates.

  HomeView  — requires login; renders dashboard/index.html
  CustomLoginView  — styled login page; redirects to "/" on success
  LogoutView — POST-only; clears session and redirects to /login/
"""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView
from django.views.generic import TemplateView
from django.urls import reverse_lazy


class HomeView(LoginRequiredMixin, TemplateView):
    """Main dashboard — served to any authenticated user."""
    template_name = "dashboard/index.html"
    login_url = "/login/"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Restore last-searched location from session so JS can pre-populate
        # the search bar and immediately re-run the search on page load.
        ctx["last_location"] = self.request.session.get("last_location", "")
        return ctx


class CustomLoginView(LoginView):
    """Login page with VAYU branding."""
    template_name = "registration/login.html"
    redirect_authenticated_user = True
    next_page = reverse_lazy("home")


class CustomLogoutView(LogoutView):
    next_page = reverse_lazy("login")
