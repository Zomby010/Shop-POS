from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum

from apps.core.money import ZERO


class Sale(models.Model):
    """A cart while open or held; a sale once completed. Held carts do not touch stock."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        HELD = "held", "Held"
        COMPLETED = "completed", "Completed"
        VOIDED = "voided", "Voided"

    number = models.PositiveIntegerField(unique=True, null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True)
    label = models.CharField(max_length=80, blank=True, help_text="Name for a held sale, e.g. 'Mama Wanjiku'")
    cashier = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sales")
    customer = models.ForeignKey(
        "partners.Customer", null=True, blank=True, on_delete=models.PROTECT, related_name="sales"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cost_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_tendered = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    change_given = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.receipt_no if self.number else f"Cart #{self.pk}"

    @property
    def receipt_no(self):
        return f"R{self.number:06d}" if self.number else ""

    @property
    def is_editable(self):
        return self.status in (self.Status.OPEN, self.Status.HELD)

    def recalculate(self):
        total = self.lines.aggregate(t=Sum("line_total"))["t"] or ZERO
        self.subtotal = total
        self.total = total
        return total

    def paid_by(self, method):
        return self.payments.filter(method=method).aggregate(t=Sum("amount"))["t"] or ZERO

    @property
    def refunded_total(self):
        return self.refunds.aggregate(t=Sum("total"))["t"] or ZERO


class SaleLine(models.Model):
    class EnteredAs(models.TextChoices):
        QUANTITY = "qty", "Quantity"
        AMOUNT = "amount", "Amount"

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="sale_lines")
    description = models.CharField(max_length=120)
    unit = models.CharField(max_length=5)
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tier_applied = models.BooleanField(default=False)
    entered_as = models.CharField(max_length=6, choices=EnteredAs.choices, default=EnteredAs.QUANTITY)
    refunded_qty = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.description} {self.quantity} {self.unit}"

    @property
    def refundable_qty(self):
        return self.quantity - self.refunded_qty


class Payment(models.Model):
    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        MPESA = "mpesa", "M-Pesa"
        CREDIT = "credit", "Deni (credit)"

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="payments")
    method = models.CharField(max_length=10, choices=Method.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reference = models.CharField(max_length=30, blank=True, db_index=True,
                                 help_text="M-Pesa transaction code, optional")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_method_display()} {self.amount}"


class Refund(models.Model):
    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        MPESA = "mpesa", "M-Pesa"
        CREDIT = "credit", "Reduce customer's deni"

    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="refunds")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    authorised_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    reason = models.CharField(max_length=200)
    method = models.CharField(max_length=10, choices=Method.choices, default=Method.CASH)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_void = models.BooleanField(default=False, help_text="Whole sale voided")

    def __str__(self):
        return f"Refund on {self.sale} ({self.total})"


class RefundLine(models.Model):
    refund = models.ForeignKey(Refund, on_delete=models.CASCADE, related_name="lines")
    sale_line = models.ForeignKey(SaleLine, on_delete=models.PROTECT, related_name="refund_lines")
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    amount = models.DecimalField(max_digits=12, decimal_places=2)


class CashUp(models.Model):
    """End-of-shift check of the drawer and M-Pesa against recorded sales."""

    cashier = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="cashups")
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    opening_float = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    expected_cash = models.DecimalField(max_digits=12, decimal_places=2)
    counted_cash = models.DecimalField(max_digits=12, decimal_places=2)
    expected_mpesa = models.DecimalField(max_digits=12, decimal_places=2)
    counted_mpesa = models.DecimalField(max_digits=12, decimal_places=2)
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-period_end"]

    def __str__(self):
        return f"Cash-up {self.cashier} {self.period_end:%Y-%m-%d %H:%M}"

    @property
    def cash_difference(self):
        return self.counted_cash - self.expected_cash

    @property
    def mpesa_difference(self):
        return self.counted_mpesa - self.expected_mpesa
