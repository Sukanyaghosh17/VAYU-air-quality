from django.contrib import admin

from .models import Alert, Threshold


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ("sensor", "alert_type", "parameter", "value", "severity", "status", "created_at")
    list_filter = ("alert_type", "severity", "status", "sensor")
    search_fields = ("sensor__sensor_code", "parameter")
    ordering = ("-created_at",)
    readonly_fields = ("created_at", "resolved_at")
    actions = ["mark_resolved"]

    @admin.action(description="Mark selected alerts as resolved")
    def mark_resolved(self, request, queryset):
        for alert in queryset.filter(status__in=["open", "investigating"]):
            alert.resolve()
        self.message_user(request, f"{queryset.count()} alert(s) resolved.")


@admin.register(Threshold)
class ThresholdAdmin(admin.ModelAdmin):
    list_display = ("parameter", "warning_limit", "critical_limit")
    ordering = ("parameter",)
