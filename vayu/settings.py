"""
VAYU – Django Settings
======================
Design decisions:
- django-environ reads all secrets from .env so nothing is hardcoded.
- AUTH_USER_MODEL points to our custom User early; changing this post-migration
  would be painful, so it must be set before the first `migrate`.
- USE_TZ=True + TIME_ZONE="UTC": sensor timestamps cross time-zones; storing in
  UTC and converting at display time is the only correct approach.
- DEFAULT_AUTO_FIELD=BigAutoField: SensorReading will accumulate millions of rows;
  a 32-bit int primary key (max ~2.1B) is a real risk for a production sensor platform.
- STATICFILES_DIRS wires the project-level static/ folder so Phase 6 CSS/JS is
  picked up by collectstatic without any per-app config.
"""

from pathlib import Path
import environ

# ── Path helpers ────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)
environ.Env.read_env(BASE_DIR / ".env")

# ── Core ────────────────────────────────────────────────────────────────────
SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["127.0.0.1", "localhost"])

# ── Applications ─────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "rest_framework.authtoken",
    # Project apps
    "accounts",
    "sensors",
    "alerts",
    "analytics",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "vayu.urls"

# ── Templates ────────────────────────────────────────────────────────────────
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # Project-level templates/ folder — shared base templates live here;
        # app-level templates go in <app>/templates/<app>/ per Django convention.
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "vayu.wsgi.application"

# ── Database ─────────────────────────────────────────────────────────────────
# MySQL is the primary target. mysqlclient is the recommended driver (C extension,
# faster than PyMySQL). If the DB doesn't exist yet, create it first:
#   CREATE DATABASE vayu_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
DATABASES = {
    "default": env.db("DATABASE_URL", default="mysql://root:@127.0.0.1:3306/vayu_db")
}

# ── Custom user model ────────────────────────────────────────────────────────
AUTH_USER_MODEL = "accounts.User"

# ── Password validation ───────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ── Internationalisation ──────────────────────────────────────────────────────
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ── Static files ─────────────────────────────────────────────────────────────
STATIC_URL = "/static/"
# Project-level static/ folder (CSS, JS, images shared across all apps)
STATICFILES_DIRS = [BASE_DIR / "static"]
# Where collectstatic writes files for production deployment
STATIC_ROOT = BASE_DIR / "staticfiles"

# ── Media files (future use) ──────────────────────────────────────────────────
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ── Primary key default ───────────────────────────────────────────────────────
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── Django REST Framework ─────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
}

# ── ML model storage ──────────────────────────────────────────────────────────
# joblib-serialised Isolation Forest models are stored here, keyed by sensor id.
# One file per sensor: ml_models/sensor_<id>.joblib
ML_MODELS_DIR = BASE_DIR / "ml_models"
# Minimum readings required before ML scoring is attempted (cold-start guard)
ML_MIN_READINGS = 100
# Rolling window size for feature engineering
ML_ROLLING_WINDOW = 6

# ── Alert cooldown ────────────────────────────────────────────────────────────
# Seconds to wait before creating a second threshold alert for the same sensor/param.
ALERT_COOLDOWN_SECONDS = 300

# ── Auth redirects (Phase 6 dashboard) ───────────────────────────────────────
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"
