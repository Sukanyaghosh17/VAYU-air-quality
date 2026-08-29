from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import SensorReadingViewSet, SensorViewSet

router = DefaultRouter()
router.register(r"sensors", SensorViewSet, basename="sensor")
router.register(r"readings", SensorReadingViewSet, basename="reading")

# The router auto-generates URLs for:
#   /sensors/           /sensors/<pk>/
#   /readings/          /readings/<pk>/
#   /readings/latest/   (custom @action)
#   /readings/history/  (custom @action)

urlpatterns = [
    path("", include(router.urls)),
]
