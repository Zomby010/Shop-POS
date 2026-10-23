from django.contrib import admin

from .models import Document, DocumentLine


class DocumentLineInline(admin.TabularInline):
    model = DocumentLine
    extra = 0


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ["code", "kind", "party_display", "date", "status"]
    list_filter = ["kind", "status", "party_type"]
    inlines = [DocumentLineInline]
