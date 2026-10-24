from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.money import ZERO


class Purchase(models.Model):
    """Stock received from a supplier."""

    supplier = models.ForeignKey("partners.Supplier", null=True, blank=True, on_delete=models.PROTECT, related_name="purchases")
    date = models.DateField(default=timezone.localdate)
    supplier_reference = models.CharField(max_length=60, blank=True, help_text="Supplier's invoice or delivery number")
    note = models.CharField(max_length=200, blank=True)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False,
                                      help_text="Cached sum of payments to the supplier")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name="+")
    cancel_reason = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"Purchase P{self.pk:05d}" if self.pk else "New purchase"

    @property
    def is_cancelled(self):
        return self.cancelled_at is not None

    @property
    def balance(self):
        return ZERO if self.is_cancelled else self.total - self.amount_paid

    @property
    def payment_status(self):
        if self.is_cancelled:
            return "Cancelled"
        if self.amount_paid >= self.total:
            return "Paid"
        return "Partly paid" if self.amount_paid > ZERO else "Unpaid"


class SupplierPayment(models.Model):
    """Money paid to a supplier against a purchase."""

    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        MPESA = "mpesa", "M-Pesa"
        BANK = "bank", "Bank"

    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name="payments")
    date = models.DateField(default=timezone.localdate)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=10, choices=Method.choices, default=Method.CASH)
    note = models.CharField(max_length=200, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]


class Conversion(models.Model):
    """Turning some of one product into another: a 50 kg sack of sugar into 1 kg packets,
    or a crate into single bottles. Stock and cost move across; nothing is bought."""

    from_product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")
    from_qty = models.DecimalField(max_digits=14, decimal_places=3)
    to_product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")
    to_qty = models.DecimalField(max_digits=14, decimal_places=3)
    value = models.DecimalField(max_digits=12, decimal_places=2, help_text="Cost moved across")
    note = models.CharField(max_length=200, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"Conversion CV{self.pk:04d}" if self.pk else "New conversion"

    @property
    def yield_pct(self):
        return self.to_qty / self.from_qty * 100 if self.from_qty else ZERO

    @property
    def unit_cost_out(self):
        return self.value / self.to_qty if self.to_qty else ZERO


class Recount(models.Model):
    """A quick count of a few products. Each difference is posted with its own reason."""

    class Kind(models.TextChoices):
        SPOT = "spot", "Spot check"
        OPENING = "opening", "Opening count"
        CLOSING = "closing", "Closing count"
        OTHER = "other", "Other"

    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.SPOT)
    note = models.CharField(max_length=200, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Recount RC{self.pk:04d}" if self.pk else "New recount"


class PurchaseLine(models.Model):
    """'2 sacks of 50 kg at KSh 9,000' -> quantity 100 kg at KSh 180/kg."""

    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="purchase_lines")
    packs = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    pack_size = models.DecimalField(max_digits=12, decimal_places=3, default=1, help_text="Units (pcs, kg or L) per pack")
    pack_cost = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.product} {self.quantity}"


class StockTake(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Counting"
        APPROVED = "approved", "Approved"
        CANCELLED = "cancelled", "Cancelled"

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    note = models.CharField(max_length=200, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    started_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"Stock take ST{self.pk:04d}" if self.pk else "New stock take"


class StockTakeLine(models.Model):
    stocktake = models.ForeignKey(StockTake, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")
    expected_qty = models.DecimalField(max_digits=14, decimal_places=3)
    counted_qty = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["product__name"]
        unique_together = [("stocktake", "product")]

    @property
    def variance(self):
        if self.counted_qty is None:
            return ZERO
        return self.counted_qty - self.expected_qty

    @property
    def variance_value(self):
        return self.variance * self.unit_cost
