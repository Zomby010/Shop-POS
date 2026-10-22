from django.contrib import admin

from .models import CashUp, Payment, Refund, RefundLine, Sale, SaleLine


class SaleLineInline(admin.TabularInline):
    model = SaleLine
    extra = 0


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ["__str__", "status", "completed_at", "cashier", "total"]
    list_filter = ["status", "cashier"]
    search_fields = ["number", "label"]
    inlines = [SaleLineInline, PaymentInline]


class RefundLineInline(admin.TabularInline):
    model = RefundLine
    extra = 0


@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = ["created_at", "sale", "total", "user", "authorised_by", "reason"]
    inlines = [RefundLineInline]


@admin.register(CashUp)
class CashUpAdmin(admin.ModelAdmin):
    list_display = ["period_end", "cashier", "expected_cash", "counted_cash", "expected_mpesa", "counted_mpesa"]
