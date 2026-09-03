from django.test import TestCase
from django.urls import reverse


class DashboardPublicViewTests(TestCase):
    def test_dashboard_home_is_public(self):
        """Dashboard home page loads with 200 OK without requiring login."""
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard/index.html")
        # Ensure logout button and user chip are not present
        self.assertNotContains(response, "logout-btn")
        self.assertNotContains(response, "user-chip")

    def test_login_url_removed(self):
        """Login page has been permanently removed (returns 404)."""
        response = self.client.get("/login/")
        self.assertEqual(response.status_code, 404)

    def test_signup_url_removed(self):
        """Signup page has been permanently removed (returns 404)."""
        response = self.client.get("/signup/")
        self.assertEqual(response.status_code, 404)

    def test_logout_url_removed(self):
        """Logout endpoint has been permanently removed (returns 404)."""
        response = self.client.get("/logout/")
        self.assertEqual(response.status_code, 404)

