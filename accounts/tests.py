from django.contrib.auth import get_user_model
from django.test import TestCase

User = get_user_model()


class UserModelTests(TestCase):
    def test_user_creation_and_roles(self):
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="StrongPassword123!",
            role=User.ROLE_USER,
        )
        self.assertEqual(user.username, "testuser")
        self.assertEqual(user.email, "test@example.com")
        self.assertFalse(user.is_admin())
        self.assertEqual(str(user), "testuser (User)")

    def test_admin_role(self):
        admin_user = User.objects.create_user(
            username="adminuser",
            email="admin@example.com",
            password="StrongPassword123!",
            role=User.ROLE_ADMIN,
        )
        self.assertTrue(admin_user.is_admin())
        self.assertEqual(str(admin_user), "adminuser (Admin)")

