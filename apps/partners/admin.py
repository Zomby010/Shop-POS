from django.contrib import admin

from .models import CreditEntry, Customer, Supplier


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ["name", "contact_person", "phone", "active"]
    search_fields = ["name", "contact_person", "phone"]


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ["name", "phone", "balance", "credit_limit", "active"]
    search_fields = ["name", "phone"]
    readonly_fields = ["balance"]


@admin.register(CreditEntry)
class CreditEntryAdmin(admin.ModelAdmin):
    list_display = ["created_at", "customer", "kind", "amount", "method", "sale"]
    list_filter = ["kind"]
