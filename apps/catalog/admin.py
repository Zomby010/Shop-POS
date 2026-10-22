from django.contrib import admin

from .models import Category, PriceTier, Product, QuickPreset, QuickSaleCategory, StockMovement


class PriceTierInline(admin.TabularInline):
    model = PriceTier
    extra = 0


class QuickPresetInline(admin.TabularInline):
    model = QuickPreset
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["name", "barcode", "category", "sold_by", "selling_price", "cost_price", "stock_qty", "active"]
    list_filter = ["sold_by", "category", "quick_category", "active"]
    search_fields = ["name", "barcode"]
    readonly_fields = ["stock_qty"]
    inlines = [PriceTierInline, QuickPresetInline]


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ["created_at", "product", "kind", "quantity", "unit_cost", "user", "reference"]
    list_filter = ["kind"]
    search_fields = ["product__name", "reference"]

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False


admin.site.register(Category)
admin.site.register(QuickSaleCategory)
