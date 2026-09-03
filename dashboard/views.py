"""
dashboard/views.py — Frontend views
====================================
All data is fetched client-side by dashboard.js via the REST API,
so this view only renders the dashboard template.

  HomeView — renders dashboard/index.html (publicly accessible)
"""
from django.views.generic import TemplateView


class HomeView(TemplateView):
    """Main dashboard — served to all visitors without requiring authentication."""
    template_name = "dashboard/index.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Restore last-searched location from session so JS can pre-populate
        # the search bar and immediately re-run the search on page load.
        ctx["last_location"] = self.request.session.get("last_location", "")
        return ctx

