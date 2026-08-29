"""
accounts/models.py – Custom User model
=======================================
We extend AbstractUser (not AbstractBaseUser) because:
  - AbstractUser keeps Django's full auth machinery intact (login views, admin,
    password reset) with zero extra wiring.
  - AbstractBaseUser gives more control but requires reimplementing username,
    email uniqueness, and the full manager — unnecessary complexity for a
    role-scoped internal tool.

The `role` field is a simple CharField rather than a separate Group/Permission
setup because VAYU has exactly two roles (admin / user) with a clear capability
split.  Full Django permissions would be correct for a product with many roles
or fine-grained object-level rules; here it would be over-engineering.

AUTH_USER_MODEL = "accounts.User" must be set in settings.py before the first
migration — Django bakes the user model reference into many system tables.
"""

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    ROLE_ADMIN = "admin"
    ROLE_USER = "user"
    ROLE_CHOICES = [
        (ROLE_ADMIN, "Admin"),
        (ROLE_USER, "User"),
    ]

    role = models.CharField(
        max_length=10,
        choices=ROLE_CHOICES,
        default=ROLE_USER,
        help_text="Admins can manage sensors, thresholds, and resolve alerts.",
    )

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"

    def is_admin(self) -> bool:
        """Convenience predicate used in DRF permission classes."""
        return self.role == self.ROLE_ADMIN

    def __str__(self) -> str:
        return f"{self.username} ({self.get_role_display()})"
