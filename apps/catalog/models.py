from django.conf import settings
from django.db import models
from django.db.models import F, Q, Value
from django.db.models.functions import Coalesce


class Category(models.Model):
    name = models.CharField(max_length=80, unique=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class QuickSaleCategory(models.Model):
    """A tab on the sell screen's quick-sale panel (Rice, Beans, Cooking oil...)."""

    name = models.CharField(max_length=60, unique=True)
    order = models.PositiveIntegerField(default=0, help_text="Lower comes first. The first eight get F1 to F8.")
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "name"]
        verbose_name_plural = "quick-sale categories"

    def __str__(self):
        return self.name


class ProductQuerySet(models.QuerySet):
    def active(self):
        return self.filter(active=True)

    def with_threshold(self):
        from apps.core.models import ShopSettings

        default = ShopSettings.load().low_stock_default
        return self.annotate(
            effective_threshold=Coalesce(
                "low_stock_threshold", Value(default), output_field=models.DecimalField(max_digits=12, decimal_places=3)
            )
        )

    def low_stock(self):
        return self.active().with_threshold().filter(stock_qty__lte=F("effective_threshold"))

    def search(self, term):
        term = (term or "").strip()
        if not term:
            return self
        return self.filter(Q(name__icontains=term) | Q(barcode=term) | Q(category__name__icontains=term))


class Product(models.Model):
    class SoldBy(models.TextChoices):
        PIECE = "piece", "Piece"
        WEIGHT = "weight", "Weight (kg)"
        VOLUME = "volume", "Volume (litre)"

    UNIT_LABELS = {SoldBy.PIECE: "pcs", SoldBy.WEIGHT: "kg", SoldBy.VOLUME: "L"}

    name = models.CharField(max_length=120, db_index=True)
    barcode = models.CharField(max_length=64, unique=True, null=True, blank=True)
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="products")
    sold_by = models.CharField(max_length=10, choices=SoldBy.choices, default=SoldBy.PIECE)
    selling_price = models.DecimalField(max_digits=12, decimal_places=2, help_text="Per piece, per kg or per litre")
    cost_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, help_text="Per piece, per kg or per litre (weighted average)"
    )
    stock_qty = models.DecimalField(
        max_digits=14, decimal_places=3, default=0, editable=False, help_text="Cached sum of stock movements"
    )
    low_stock_threshold = models.DecimalField(
        max_digits=12, decimal_places=3, null=True, blank=True, help_text="Leave blank to use the shop default"
    )
    active = models.BooleanField(default=True)
    quick_category = models.ForeignKey(
        QuickSaleCategory, null=True, blank=True, on_delete=models.SET_NULL, related_name="products"
    )
    quick_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.barcode = (self.barcode or "").strip() or None
        super().save(*args, **kwargs)

    @property
    def unit(self):
        return self.UNIT_LABELS[self.sold_by]

    @property
    def is_loose(self):
        return self.sold_by != self.SoldBy.PIECE

    @property
    def threshold(self):
        if self.low_stock_threshold is not None:
            return self.low_stock_threshold
        from apps.core.models import ShopSettings

        return ShopSettings.load().low_stock_default

    @property
    def is_low_stock(self):
        return self.stock_qty <= self.threshold

    def visible_presets(self):
        return [p for p in self.presets.all() if not p.hidden]


class PriceTier(models.Model):
    """Bulk price: from min_qty upwards the line uses unit_price."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="tiers")
    min_qty = models.DecimalField(max_digits=12, decimal_places=3)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["min_qty"]
        unique_together = [("product", "min_qty")]

    def __str__(self):
        return f"{self.product}: from {self.min_qty.normalize()} {self.product.unit} at {self.unit_price}"


class QuickPreset(models.Model):
    """A one-tap button on the quick-sale panel: a quantity (1/4 kg) or an amount (KSh 50)."""

    class Kind(models.TextChoices):
        QUANTITY = "qty", "Quantity"
        AMOUNT = "amount", "Amount (KSh)"

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="presets")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.QUANTITY)
    value = models.DecimalField(max_digits=12, decimal_places=3)
    label = models.CharField(max_length=30, blank=True, help_text="Optional. Generated if blank, e.g. '1/4 kg'")
    order = models.PositiveIntegerField(default=0)
    hidden = models.BooleanField(default=False)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.product}: {self.display_label}"

    @property
    def display_label(self):
        if self.label:
            return self.label
        from .presets import format_preset

        return format_preset(self.kind, self.value, self.product.unit)


class StockMovement(models.Model):
    """Every change to stock is one row. Product.stock_qty caches the sum."""

    class Kind(models.TextChoices):
        OPENING = "opening", "Opening stock"
        PURCHASE = "purchase", "Purchase"
        SALE = "sale", "Sale"
        REFUND = "refund", "Refund"
        RECOUNT = "recount", "Recount adjustment"
        STOCKTAKE = "stocktake", "Stock take"
        LOSS = "loss", "Loss or wastage"

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="movements")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    quantity = models.DecimalField(max_digits=14, decimal_places=3, help_text="Positive adds stock, negative removes")
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    reason = models.CharField(max_length=200, blank=True)
    reference = models.CharField(max_length=60, blank=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.get_kind_display()} {self.quantity} {self.product.unit} {self.product}"

    @property
    def value(self):
        return self.quantity * self.unit_cost
