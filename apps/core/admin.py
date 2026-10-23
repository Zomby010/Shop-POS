from django.contrib import admin

from .models import AuditLog, Sequence, ShopSettings, UserProfile


@admin.register(ShopSettings)
class ShopSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not ShopSettings.objects.exists()


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["created_at", "action", "object_repr", "user", "authorised_by", "reason"]
    list_filter = ["action"]
    search_fields = ["object_repr", "reason"]

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(UserProfile)
admin.site.register(Sequence)
admin.site.site_header = "Shop POS admin"
