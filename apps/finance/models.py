from django.conf import settings
from django.db import models
from django.utils import timezone


class ExpenseCategory(models.Model):
    """Rent, electricity, transport... The owner can add their own."""

    name = models.CharField(max_length=60, unique=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]
        verbose_name_plural = "expense categories"

    def __str__(self):
        return self.name


class Expense(models.Model):
    class Method(models.TextChoices):
        CASH = "cash", "Cash (from drawer)"
        MPESA = "mpesa", "M-Pesa"
        BANK = "bank", "Bank"

    date = models.DateField(default=timezone.localdate, db_index=True)
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, related_name="expenses")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=10, choices=Method.choices, default=Method.CASH)
    note = models.CharField(max_length=200, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.date} {self.category} {self.amount}"
