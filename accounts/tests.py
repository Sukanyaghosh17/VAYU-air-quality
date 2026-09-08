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
        self.assertFalse(admin_user.is_service())
        self.assertTrue(admin_user.can_provision_sensors)
        self.assertEqual(str(admin_user), "adminuser (Admin)")

    def test_service_role(self):
        service_user = User.objects.create_user(
            username="serviceuser",
            email="service@example.com",
            password="StrongPassword123!",
            role=User.ROLE_SERVICE,
        )
        self.assertFalse(service_user.is_admin())
        self.assertTrue(service_user.is_service())
        self.assertTrue(service_user.can_provision_sensors)
        self.assertEqual(str(service_user), "serviceuser (Service)")

    def test_can_provision_sensors_permissions(self):
        user = User.objects.create_user(username="u1", role=User.ROLE_USER)
        admin = User.objects.create_user(username="u2", role=User.ROLE_ADMIN)
        service = User.objects.create_user(username="u3", role=User.ROLE_SERVICE)

        self.assertFalse(user.can_provision_sensors)
        self.assertTrue(admin.can_provision_sensors)
        self.assertTrue(service.can_provision_sensors)
