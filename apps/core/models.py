from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import models


class ShopSettings(models.Model):
    """Single-row settings for the shop, edited on the one settings page."""

    class Connection(models.TextChoices):
        NONE = "none", "No printer (show receipt on screen)"
        USB = "usb", "USB (vendor:product id)"
        NETWORK = "network", "Network (IP address)"
        WINDOWS = "windows", "Windows printer name"

    business_name = models.CharField(max_length=120, default="My Minimart")
    logo = models.ImageField(upload_to="logo/", blank=True)
    address = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=50, blank=True)
    kra_pin = models.CharField("KRA PIN", max_length=30, blank=True)
    receipt_footer = models.CharField(max_length=200, default="Thank you for shopping with us!", blank=True)
    printer_connection = models.CharField(max_length=10, choices=Connection.choices, default=Connection.NONE)
    printer_address = models.CharField(
        max_length=120,
        blank=True,
        help_text="USB: 0x0416:0x5011 · Network: 192.168.1.50 · Windows: the printer name as shown in Windows",
    )
    paper_width_mm = models.PositiveSmallIntegerField(choices=[(58, "58 mm"), (80, "80 mm")], default=80)
    low_stock_default = models.DecimalField(max_digits=12, decimal_places=3, default=5)
    backup_folder = models.CharField(max_length=300, blank=True, help_text="Folder on a USB stick or a cloud-synced folder")
    backups_to_keep = models.PositiveSmallIntegerField(default=30)

    class Meta:
        verbose_name = "shop settings"
        verbose_name_plural = "shop settings"

    def __str__(self):
        return self.business_name

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def receipt_chars(self):
        """Characters per line for the configured paper width (Font A)."""
        return 32 if self.paper_width_mm == 58 else 48


class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    pin_hash = models.CharField(max_length=128, blank=True)

    def set_pin(self, pin):
        self.pin_hash = make_password(str(pin))

    def check_pin(self, pin):
        return bool(self.pin_hash) and check_password(str(pin), self.pin_hash)

    def __str__(self):
        return f"Profile of {self.user}"


class AuditLog(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    authorised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    action = models.CharField(max_length=50)
    object_repr = models.CharField(max_length=200, blank=True)
    reason = models.CharField(max_length=300, blank=True)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action} {self.object_repr}"


class Sequence(models.Model):
    """Gap-free counters for receipt, invoice and quotation numbers."""

    name = models.CharField(max_length=20, unique=True)
    last = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.name}: {self.last}"

    @classmethod
    def next(cls, name):
        """Call inside a transaction."""
        seq, _ = cls.objects.select_for_update().get_or_create(name=name)
        seq.last += 1
        seq.save(update_fields=["last"])
        return seq.last


class StoredFile(models.Model):
    """An uploaded file (the logo) kept in the database when the POS runs online with no lasting disk."""

    name = models.CharField(max_length=255, unique=True)
    content = models.BinaryField()
    size = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
