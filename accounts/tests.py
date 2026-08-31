from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class SignUpViewTests(TestCase):
    def test_signup_page_loads(self):
        response = self.client.get(reverse("signup"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "registration/auth.html")

    def test_signup_successful_creation_and_login(self):
        response = self.client.post(reverse("signup"), {
            "username": "newuser",
            "email": "newuser@example.com",
            "password1": "StrongPass123!",
            "password2": "StrongPass123!",
        })
        self.assertRedirects(response, reverse("home"))
        user = User.objects.get(username="newuser")
        self.assertEqual(user.email, "newuser@example.com")
        self.assertEqual(user.role, User.ROLE_USER)
        # Verify user is logged in
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_signup_password_mismatch(self):
        response = self.client.post(reverse("signup"), {
            "username": "mismatchuser",
            "email": "mismatch@example.com",
            "password1": "StrongPass123!",
            "password2": "DifferentPass456!",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="mismatchuser").exists())

    def test_signup_redirect_if_authenticated(self):
        user = User.objects.create_user(username="existing", password="Password123!")
        self.client.force_login(user)
        response = self.client.get(reverse("signup"))
        self.assertRedirects(response, reverse("home"))
