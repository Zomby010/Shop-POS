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
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"Purchase P{self.pk:05d}" if self.pk else "New purchase"


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
