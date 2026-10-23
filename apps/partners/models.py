from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum


class Supplier(models.Model):
    name = models.CharField(max_length=120, unique=True)
    contact_person = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=200, blank=True)
    kra_pin = models.CharField("KRA PIN", max_length=30, blank=True)
    notes = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Customer(models.Model):
    """Customers exist for credit (deni) and for invoices and quotations."""

    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=50, blank=True, db_index=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=200, blank=True)
    credit_limit = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, help_text="Leave blank for no limit"
    )
    balance = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, editable=False, help_text="Amount the customer owes"
    )
    notes = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.phone})" if self.phone else self.name

    def available_credit(self):
        if self.credit_limit is None:
            return None
        return self.credit_limit - self.balance


class CreditEntry(models.Model):
    """A charge (sale on deni) increases the balance; a repayment reduces it."""

    class Kind(models.TextChoices):
        CHARGE = "charge", "Credit sale"
        REPAYMENT = "repayment", "Repayment"

    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        MPESA = "mpesa", "M-Pesa"

    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="credit_entries")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=10, choices=Method.choices, blank=True, help_text="For repayments")
    sale = models.ForeignKey("sales.Sale", null=True, blank=True, on_delete=models.PROTECT, related_name="credit_entries")
    note = models.CharField(max_length=200, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "credit entries"

    def __str__(self):
        return f"{self.get_kind_display()} {self.amount} {self.customer.name}"

    @property
    def signed_amount(self):
        return self.amount if self.kind == self.Kind.CHARGE else -self.amount


def recalculate_balance(customer):
    totals = {
        row["kind"]: row["total"]
        for row in customer.credit_entries.values("kind").annotate(total=Sum("amount"))
    }
    balance = totals.get(CreditEntry.Kind.CHARGE, Decimal(0)) - totals.get(CreditEntry.Kind.REPAYMENT, Decimal(0))
    Customer.objects.filter(pk=customer.pk).update(balance=balance)
    customer.balance = balance
    return balance
