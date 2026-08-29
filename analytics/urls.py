from django.urls import path

from .views import AnomalyFeedView, SensorStatsView, TrendView

urlpatterns = [
    path("stats/", SensorStatsView.as_view(), name="analytics-stats"),
    path("anomalies/", AnomalyFeedView.as_view(), name="analytics-anomalies"),
    path("trends/", TrendView.as_view(), name="analytics-trends"),
]
