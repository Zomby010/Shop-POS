from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.utils import timezone

from apps.core.money import ZERO


class Document(models.Model):
    """An invoice or quotation for a supplier, a customer or a one-off party."""

    class Kind(models.TextChoices):
        INVOICE = "invoice", "Invoice"
        QUOTATION = "quotation", "Quotation"

    class PartyType(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        SUPPLIER = "supplier", "Supplier"
        OTHER = "other", "Other (one-off)"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent"
        PARTLY_PAID = "partly_paid", "Partly paid"
        PAID = "paid", "Paid"
        ACCEPTED = "accepted", "Accepted"
        CONVERTED = "converted", "Converted to invoice"

    PREFIX = {Kind.INVOICE: "INV", Kind.QUOTATION: "QUO"}

    kind = models.CharField(max_length=10, choices=Kind.choices)
    number = models.PositiveIntegerField()
    party_type = models.CharField(max_length=10, choices=PartyType.choices, default=PartyType.CUSTOMER)
    customer = models.ForeignKey("partners.Customer", null=True, blank=True, on_delete=models.PROTECT, related_name="documents")
    supplier = models.ForeignKey("partners.Supplier", null=True, blank=True, on_delete=models.PROTECT, related_name="documents")
    party_name = models.CharField(max_length=120, blank=True, help_text="For one-off parties")
    party_details = models.CharField(max_length=200, blank=True, help_text="Phone, address or email for one-off parties")
    date = models.DateField(default=timezone.localdate)
    valid_until = models.DateField(null=True, blank=True, help_text="Quotations only")
    due_date = models.DateField(null=True, blank=True, help_text="Invoices only")
    is_bulk = models.BooleanField(default=False, help_text="Apply bulk tier prices to product lines")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    converted_from = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="converted_to"
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-number"]
        unique_together = [("kind", "number")]

    def __str__(self):
        return self.code

    @property
    def code(self):
        return f"{self.PREFIX[self.kind]}-{self.number:04d}"

    @property
    def party(self):
        if self.party_type == self.PartyType.CUSTOMER and self.customer_id:
            return self.customer
        if self.party_type == self.PartyType.SUPPLIER and self.supplier_id:
            return self.supplier
        return None

    @property
    def party_display(self):
        party = self.party
        return party.name if party else self.party_name

    @property
    def subtotal(self):
        return self.lines.aggregate(t=Sum("line_total"))["t"] or ZERO

    @property
    def total(self):
        return self.subtotal - self.discount

    @property
    def balance_due(self):
        return self.total - self.amount_paid


class DocumentLine(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey("catalog.Product", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    description = models.CharField(max_length=200)
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    unit = models.CharField(max_length=10, blank=True)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.description
