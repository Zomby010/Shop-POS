from django.conf import settings
from django.db import models
from django.utils import timezone


class Expense(models.Model):
    class Category(models.TextChoices):
        RENT = "rent", "Rent"
        ELECTRICITY = "electricity", "Electricity"
        WATER = "water", "Water"
        TRANSPORT = "transport", "Transport"
        WAGES = "wages", "Wages"
        PACKAGING = "packaging", "Packaging and bags"
        LICENCES = "licences", "Licences and permits"
        OTHER = "other", "Other"

    class Method(models.TextChoices):
        CASH = "cash", "Cash (from drawer)"
        MPESA = "mpesa", "M-Pesa"
        BANK = "bank", "Bank"

    date = models.DateField(default=timezone.localdate, db_index=True)
    category = models.CharField(max_length=15, choices=Category.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=10, choices=Method.choices, default=Method.CASH)
    note = models.CharField(max_length=200, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.date} {self.get_category_display()} {self.amount}"
