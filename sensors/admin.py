from django.contrib import admin

from .models import Sensor, SensorReading


@admin.register(Sensor)
class SensorAdmin(admin.ModelAdmin):
    list_display = ("sensor_code", "location", "status", "installed_at")
    list_filter = ("status",)
    search_fields = ("sensor_code", "location")
    ordering = ("sensor_code",)


@admin.register(SensorReading)
class SensorReadingAdmin(admin.ModelAdmin):
    list_display = ("sensor", "pm25", "pm10", "temperature", "humidity", "timestamp")
    list_filter = ("sensor",)
    search_fields = ("sensor__sensor_code",)
    ordering = ("-timestamp",)
    # Readings are created by the simulator — disable add/change in admin
    # to prevent accidental manual edits that could skew ML training data.
    def has_add_permission(self, request):
        return False
