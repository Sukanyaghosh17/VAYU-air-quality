from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import LocationSearchView, SensorMapView, SensorReadingViewSet, SensorViewSet

router = DefaultRouter()
router.register(r"sensors", SensorViewSet, basename="sensor")
router.register(r"readings", SensorReadingViewSet, basename="reading")

# IMPORTANT: manual views must be listed BEFORE include(router.urls).
# The DRF router registers sensors/<pk>/ and would incorrectly match
# "search" or "map" as a pk value if the router include comes first.

urlpatterns = [
    path("sensors/search/", LocationSearchView.as_view(), name="sensor-search"),
    path("sensors/map/", SensorMapView.as_view(), name="sensor-map"),
    path("", include(router.urls)),
]
