"""Receiving stock, recounts, stock takes and losses. All stock changes go through catalog.stock."""

from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.catalog.models import Product, StockMovement
from apps.catalog.stock import record_movement, set_counted_stock
from apps.core.money import ZERO, q2, q3, to_decimal

from .models import Purchase, PurchaseLine, StockTake, StockTakeLine


class StockError(ValueError):
    pass


@dataclass
class PurchaseItem:
    product: Product
    packs: Decimal
    pack_size: Decimal
    pack_cost: Decimal


@transaction.atomic
def create_purchase(items, *, user, supplier=None, date=None, supplier_reference="", note=""):
    """'1 sack of 50 kg at KSh 9,000' becomes +50 kg at KSh 180/kg."""
    if not items:
        raise StockError("Add at least one item.")
    purchase = Purchase.objects.create(supplier=supplier, date=date or timezone.localdate(),
                                       supplier_reference=supplier_reference, note=note, user=user)
    total = ZERO
    for item in items:
        packs, size, cost = to_decimal(item.packs), to_decimal(item.pack_size), to_decimal(item.pack_cost)
        if not packs or packs <= ZERO or not size or size <= ZERO or cost is None or cost < ZERO:
            raise StockError(f"{item.product.name}: packs, pack size and cost must be positive numbers.")
        quantity = q3(packs * size)
        if not item.product.is_loose and quantity != quantity.to_integral_value():
            raise StockError(f"{item.product.name} is counted in pieces, so the quantity must be whole.")
        line_total = q2(packs * cost)
        unit_cost = q2(cost / size)
        PurchaseLine.objects.create(purchase=purchase, product=item.product, packs=packs, pack_size=size,
                                    pack_cost=cost, quantity=quantity, unit_cost=unit_cost, line_total=line_total)
        record_movement(item.product, StockMovement.Kind.PURCHASE, quantity, unit_cost=cost / size, user=user,
                        reason=f"From {supplier}" if supplier else "Stock received", reference=str(purchase))
        total += line_total
    purchase.total = total
    purchase.save(update_fields=["total"])
    return purchase


@transaction.atomic
def recount(counts, *, user, reason="Recount"):
    """counts: {product: counted quantity}. Returns the movements made."""
    movements = []
    for product, counted in counts.items():
        counted = to_decimal(counted)
        if counted is None or counted < ZERO:
            raise StockError(f"{product.name}: enter the counted quantity.")
        if not product.is_loose and counted != counted.to_integral_value():
            raise StockError(f"{product.name} is counted in pieces, so the count must be whole.")
        movement = set_counted_stock(product, counted, kind=StockMovement.Kind.RECOUNT, user=user, reason=reason)
        if movement:
            movements.append(movement)
    return movements


LOSS_REASONS = ["Spillage", "Scooping loss", "Expired", "Damaged", "Pests", "Theft", "Other"]


@transaction.atomic
def record_loss(product, quantity, *, user, reason, note=""):
    quantity = to_decimal(quantity)
    if quantity is None or quantity <= ZERO:
        raise StockError("Enter the quantity lost.")
    if not product.is_loose and quantity != quantity.to_integral_value():
        raise StockError(f"{product.name} is counted in pieces, so the quantity must be whole.")
    text = f"{reason}: {note}" if note else reason
    return record_movement(product, StockMovement.Kind.LOSS, -quantity, user=user, reason=text)


# ---------------------------------------------------------------- stock takes

@transaction.atomic
def start_stocktake(*, user, note="", category=None):
    if StockTake.objects.filter(status=StockTake.Status.OPEN).exists():
        raise StockError("A stock take is already in progress. Finish or cancel it first.")
    take = StockTake.objects.create(started_by=user, note=note)
    products = Product.objects.active()
    if category is not None:
        products = products.filter(category=category)
    StockTakeLine.objects.bulk_create(
        StockTakeLine(stocktake=take, product=p, expected_qty=p.stock_qty, unit_cost=p.cost_price) for p in products
    )
    return take


def save_counts(take, counts):
    """counts: {line id: text}. Blank leaves a line uncounted."""
    if take.status != StockTake.Status.OPEN:
        raise StockError("This stock take is closed.")
    lines = {str(line.pk): line for line in take.lines.select_related("product")}
    errors = []
    for line_id, text in counts.items():
        line = lines.get(str(line_id))
        if line is None:
            continue
        text = (text or "").strip()
        if text == "":
            value = None
        else:
            value = to_decimal(text)
            if value is None or value < ZERO:
                errors.append(f"{line.product.name}: '{text}' is not a valid count.")
                continue
            if not line.product.is_loose and value != value.to_integral_value():
                errors.append(f"{line.product.name} is counted in pieces.")
                continue
            value = q3(value)
        if value != line.counted_qty:
            line.counted_qty = value
            line.save(update_fields=["counted_qty"])
    return errors


@transaction.atomic
def approve_stocktake(take, *, user):
    """Post each counted line's variance (counted minus expected at the start) as a stock movement.
    Using the variance keeps sales made during counting."""
    take = StockTake.objects.select_for_update().get(pk=take.pk)
    if take.status != StockTake.Status.OPEN:
        raise StockError("This stock take is already closed.")
    for line in take.lines.select_related("product").exclude(counted_qty=None):
        if line.variance != ZERO:
            record_movement(line.product, StockMovement.Kind.STOCKTAKE, line.variance, user=user,
                            reason="Stock take", reference=str(take))
    take.status = StockTake.Status.APPROVED
    take.approved_by = user
    take.approved_at = timezone.now()
    take.save()
    return take


def cancel_stocktake(take):
    if take.status != StockTake.Status.OPEN:
        raise StockError("This stock take is already closed.")
    take.status = StockTake.Status.CANCELLED
    take.save(update_fields=["status"])


# ---------------------------------------------------------------- reports

@dataclass
class LooseLossRow:
    product: Product
    stocktakes: int
    expected: Decimal
    counted: Decimal
    variance: Decimal
    variance_value: Decimal
    recorded_losses: Decimal
    recorded_loss_value: Decimal
    sold: Decimal

    @property
    def variance_pct(self):
        return (self.variance / self.expected * 100) if self.expected else ZERO

    @property
    def total_loss(self):
        return -self.variance + self.recorded_losses

    @property
    def loss_pct_of_sales(self):
        return (self.total_loss / self.sold * 100) if self.sold else ZERO


def loose_loss_report(start=None, end=None):
    """Expected against counted kg/L for weighed and measured goods across approved stock takes."""
    lines = StockTakeLine.objects.filter(stocktake__status=StockTake.Status.APPROVED).exclude(counted_qty=None)
    movements = StockMovement.objects.all()
    if start:
        lines = lines.filter(stocktake__approved_at__date__gte=start)
        movements = movements.filter(created_at__date__gte=start)
    if end:
        lines = lines.filter(stocktake__approved_at__date__lte=end)
        movements = movements.filter(created_at__date__lte=end)
    rows = []
    for product in Product.objects.exclude(sold_by=Product.SoldBy.PIECE).order_by("name"):
        product_lines = list(lines.filter(product=product))
        losses = movements.filter(product=product, kind=StockMovement.Kind.LOSS)
        sold = -(movements.filter(product=product, kind=StockMovement.Kind.SALE).aggregate(t=Sum("quantity"))["t"] or ZERO)
        lost_qty = -(losses.aggregate(t=Sum("quantity"))["t"] or ZERO)
        lost_value = -sum((m.quantity * m.unit_cost for m in losses), ZERO)
        if not product_lines and not lost_qty and not sold:
            continue
        expected = sum((l.expected_qty for l in product_lines), ZERO)
        counted = sum((l.counted_qty for l in product_lines), ZERO)
        rows.append(LooseLossRow(
            product=product, stocktakes=len(product_lines), expected=expected, counted=counted,
            variance=counted - expected, variance_value=q2(sum((l.variance_value for l in product_lines), ZERO)),
            recorded_losses=lost_qty, recorded_loss_value=q2(lost_value), sold=sold,
        ))
    rows.sort(key=lambda r: r.variance_value)
    return rows
