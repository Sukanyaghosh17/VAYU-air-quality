from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    # ── Django admin ──────────────────────────────────────────────────────────
    path("admin/", admin.site.urls),

    # ── REST API v1 ───────────────────────────────────────────────────────────
    # sensors router: /api/v1/sensors/  /api/v1/readings/
    #   Custom actions auto-wired by router:
    #     GET /api/v1/readings/latest/
    #     GET /api/v1/readings/history/
    path("api/v1/", include("sensors.urls")),

    # alerts router: /api/v1/alerts/  /api/v1/thresholds/
    path("api/v1/", include("alerts.urls")),

    # analytics views: /api/v1/analytics/stats/
    #                  /api/v1/analytics/anomalies/
    #                  /api/v1/analytics/trends/
    path("api/v1/analytics/", include("analytics.urls")),

    # ── DRF browsable API session login ──────────────────────────────────────
    path("api-auth/", include("rest_framework.urls")),

    # ── Dashboard (stub — fully wired in Phase 6) ─────────────────────────────
    # Kept here so Phase 6 only needs to fill dashboard/urls.py, not touch this
    # file again.
    path("", include("dashboard.urls")),
]
