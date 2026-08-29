from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AlertViewSet, ThresholdViewSet

router = DefaultRouter()
router.register(r"alerts", AlertViewSet, basename="alert")
router.register(r"thresholds", ThresholdViewSet, basename="threshold")

urlpatterns = [
    path("", include(router.urls)),
]
