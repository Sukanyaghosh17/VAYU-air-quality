"""
accounts/models.py – Custom User model
=======================================
We extend AbstractUser (not AbstractBaseUser) because:
  - AbstractUser keeps Django's full auth machinery intact (login views, admin,
    password reset) with zero extra wiring.
  - AbstractBaseUser gives more control but requires reimplementing username,
    email uniqueness, and the full manager — unnecessary complexity for a
    role-scoped internal tool.

The `role` field is a simple CharField rather than a complex Group/Permission
setup because VAYU has a focused three-role capability split:
  - Admin: manages system, sensors, thresholds, and alerts.
  - User: standard dashboard and monitoring access.
  - Service: automated ingest/simulator accounts with scoped permissions.

AUTH_USER_MODEL = "accounts.User" must be set in settings.py before the first
migration — Django bakes the user model reference into many system tables.
"""

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    ROLE_ADMIN = "admin"
    ROLE_USER = "user"
    ROLE_SERVICE = "service"
    ROLE_CHOICES = [
        (ROLE_ADMIN, "Admin"),
        (ROLE_USER, "User"),
        (ROLE_SERVICE, "Service"),
    ]

    role = models.CharField(
        max_length=10,
        choices=ROLE_CHOICES,
        default=ROLE_USER,
        help_text="Admins manage system, users view, service accounts ingest telemetry.",
    )

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"

    def is_admin(self) -> bool:
        """Convenience predicate used in DRF permission classes."""
        return self.role == self.ROLE_ADMIN

    def is_service(self) -> bool:
        """Predicate for automated service accounts (e.g. simulator)."""
        return self.role == self.ROLE_SERVICE

    @property
    def can_provision_sensors(self) -> bool:
        """Check if user has permission to register/create new sensors."""
        return self.is_admin() or self.is_service()

    def __str__(self) -> str:
        return f"{self.username} ({self.get_role_display()})"
