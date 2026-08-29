from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import LocationSearchView, SensorReadingViewSet, SensorViewSet

router = DefaultRouter()
router.register(r"sensors", SensorViewSet, basename="sensor")
router.register(r"readings", SensorReadingViewSet, basename="reading")

# IMPORTANT: sensors/search/ must be listed BEFORE include(router.urls).
# The DRF router registers sensors/<pk>/ and would incorrectly match
# "search" as a pk value if the router include comes first.
#
# Manual URL (plain APIView, not a ViewSet):
#   /sensors/search/?location=<q>   (LocationSearchView)

urlpatterns = [
    path("sensors/search/", LocationSearchView.as_view(), name="sensor-search"),
    path("", include(router.urls)),
]
