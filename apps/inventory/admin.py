from django.contrib import admin

from .models import Purchase, PurchaseLine, StockTake, StockTakeLine


class PurchaseLineInline(admin.TabularInline):
    model = PurchaseLine
    extra = 0


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ["__str__", "date", "supplier", "total", "user"]
    inlines = [PurchaseLineInline]


class StockTakeLineInline(admin.TabularInline):
    model = StockTakeLine
    extra = 0


@admin.register(StockTake)
class StockTakeAdmin(admin.ModelAdmin):
    list_display = ["__str__", "status", "started_at", "approved_at"]
    inlines = [StockTakeLineInline]
