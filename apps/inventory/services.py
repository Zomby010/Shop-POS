"""Receiving stock, recounts, stock takes and losses. All stock changes go through catalog.stock."""

from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.catalog.models import Product, StockMovement
from apps.catalog.stock import log_price_change, record_movement, set_counted_stock
from apps.core.money import ZERO, q2, q3, to_decimal

from .models import Conversion, Purchase, PurchaseLine, Recount, StockTake, StockTakeLine, SupplierPayment


class StockError(ValueError):
    pass


@dataclass
class PurchaseItem:
    product: Product
    packs: Decimal
    pack_size: Decimal
    pack_cost: Decimal
    new_price: Decimal | None = None  # a new selling price per unit, set while receiving


@transaction.atomic
def create_purchase(items, *, user, supplier=None, date=None, supplier_reference="", note="",
                    amount_paid=None, payment_method=SupplierPayment.Method.CASH):
    """'1 sack of 50 kg at KSh 9,000' becomes +50 kg at KSh 180/kg.

    amount_paid is what was paid on delivery; None means paid in full. The rest is owed to the supplier."""
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
        new_price = to_decimal(item.new_price)
        if new_price is not None:
            if new_price <= ZERO:
                raise StockError(f"{item.product.name}: the new selling price must be more than zero.")
            product = Product.objects.get(pk=item.product.pk)
            old_price = product.selling_price
            product.selling_price = q2(new_price)
            product.save(update_fields=["selling_price", "updated_at"])
            log_price_change(product, old_cost=product.cost_price, old_price=old_price, user=user,
                             reason=f"New selling price on {purchase}")
        total += line_total
    purchase.total = total
    purchase.save(update_fields=["total"])
    paid = total if amount_paid is None else q2(to_decimal(amount_paid, ZERO))
    if paid < ZERO or paid > total:
        raise StockError(f"Amount paid must be between 0 and the purchase total of KSh {total:,.2f}.")
    if paid > ZERO:
        pay_supplier(purchase, paid, user=user, method=payment_method, date=purchase.date, note="Paid on delivery")
        purchase.amount_paid = paid
    return purchase


@transaction.atomic
def pay_supplier(purchase, amount, *, user, method=SupplierPayment.Method.CASH, date=None, note=""):
    purchase = Purchase.objects.select_for_update().get(pk=purchase.pk)
    amount = q2(to_decimal(amount, ZERO))
    if purchase.is_cancelled:
        raise StockError("This purchase is cancelled.")
    if amount <= ZERO:
        raise StockError("Enter the amount paid.")
    if amount > purchase.balance:
        raise StockError(f"That is more than the KSh {purchase.balance:,.2f} still owed on {purchase}.")
    payment = SupplierPayment.objects.create(purchase=purchase, amount=amount, method=method, user=user,
                                             date=date or timezone.localdate(), note=note)
    purchase.amount_paid = purchase.payments.aggregate(t=Sum("amount"))["t"] or ZERO
    purchase.save(update_fields=["amount_paid"])
    return payment


def supplier_balance(supplier):
    """What the shop still owes a supplier across its purchases."""
    owed = ZERO
    for purchase in supplier.purchases.filter(cancelled_at=None):
        owed += purchase.balance
    return owed


@transaction.atomic
def cancel_purchase(purchase, *, user, reason):
    """Undo a purchase entered by mistake: its stock comes off again. Payments stay on record."""
    purchase = Purchase.objects.select_for_update().get(pk=purchase.pk)
    if purchase.is_cancelled:
        raise StockError("This purchase is already cancelled.")
    if not (reason or "").strip():
        raise StockError("Give a reason for cancelling.")
    lines = list(purchase.lines.select_related("product"))
    short = [l.product.name for l in lines if l.product.stock_qty < l.quantity]
    if short:
        raise StockError(f"Can't cancel: some of this stock has already been sold or used ({', '.join(short)}). "
                         "Record a loss or recount instead.")
    for line in lines:
        record_movement(line.product, StockMovement.Kind.PURCHASE_CANCEL, -line.quantity, unit_cost=line.unit_cost,
                        user=user, reason=reason, reference=str(purchase))
    purchase.cancelled_at = timezone.now()
    purchase.cancelled_by = user
    purchase.cancel_reason = reason.strip()[:200]
    purchase.save(update_fields=["cancelled_at", "cancelled_by", "cancel_reason"])
    return purchase


# ---------------------------------------------------------------- conversions

@transaction.atomic
def convert(from_product, from_qty, to_product, to_qty, *, user, note=""):
    """Move stock from one product into another, carrying its cost.

    2 kg of loose sugar at 160/kg into 2 x 1 kg packets: -2 kg sugar, +2 packets at 160 each.
    The cost moved is the input at its current cost, so the output's average cost reflects what it
    really cost the shop. Nothing is recorded as a purchase."""
    from_qty, to_qty = to_decimal(from_qty), to_decimal(to_qty)
    if from_product.pk == to_product.pk:
        raise StockError("Pick two different products.")
    if not from_qty or from_qty <= ZERO or not to_qty or to_qty <= ZERO:
        raise StockError("Enter how much goes in and how much comes out.")
    for product, qty in ((from_product, from_qty), (to_product, to_qty)):
        if not product.is_loose and qty != qty.to_integral_value():
            raise StockError(f"{product.name} is counted in pieces, so its quantity must be whole.")
    from_product.refresh_from_db()
    if from_qty > from_product.stock_qty:
        raise StockError(f"Only {from_product.stock_qty.normalize():f} {from_product.unit} of {from_product.name} "
                         f"in stock.")
    from_qty, to_qty = q3(from_qty), q3(to_qty)
    value = q2(from_qty * from_product.cost_price)
    conversion = Conversion.objects.create(from_product=from_product, from_qty=from_qty, to_product=to_product,
                                           to_qty=to_qty, value=value, note=note, user=user)
    ref = str(conversion)
    record_movement(from_product, StockMovement.Kind.CONVERSION_OUT, -from_qty, unit_cost=from_product.cost_price,
                    user=user, reason=f"Into {to_qty.normalize():f} {to_product.unit} {to_product.name}", reference=ref)
    record_movement(to_product, StockMovement.Kind.CONVERSION_IN, to_qty, unit_cost=value / to_qty, user=user,
                    reason=f"From {from_qty.normalize():f} {from_product.unit} {from_product.name}", reference=ref)
    return conversion


SHORTAGE_REASONS = ["Normal loss", "Used in the shop", "Damaged", "Expired", "Theft", "Other shortage"]
SURPLUS_REASONS = ["Over-counted before", "Delivery not recorded", "Returned by customer", "Other surplus"]


@dataclass
class CountLine:
    product: Product
    counted: Decimal
    reason: str = ""

    @property
    def difference(self):
        return q3(self.counted - self.product.stock_qty)

    @property
    def value(self):
        return q2(self.difference * self.product.cost_price)


def check_counts(counts):
    """counts: {product: (counted text, reason)}. Returns CountLines, or raises StockError listing every problem.

    A shortage needs a shortage reason and a surplus a surplus reason, so gains are never filed as losses."""
    lines, errors = [], []
    for product, (text, reason) in counts.items():
        counted = to_decimal(text)
        if counted is None or counted < ZERO:
            errors.append(f"{product.name}: enter the counted quantity.")
            continue
        if not product.is_loose and counted != counted.to_integral_value():
            errors.append(f"{product.name} is counted in pieces, so the count must be whole.")
            continue
        product.refresh_from_db(fields=["stock_qty", "cost_price"])
        line = CountLine(product, q3(counted), (reason or "").strip())
        if line.difference < ZERO and line.reason not in SHORTAGE_REASONS:
            errors.append(f"{product.name} is {(-line.difference).normalize():f} {product.unit} short: choose why.")
        elif line.difference > ZERO and line.reason not in SURPLUS_REASONS:
            errors.append(f"{product.name} has {line.difference.normalize():f} {product.unit} extra: choose why.")
        lines.append(line)
    if errors:
        raise StockError(" ".join(errors))
    if not lines:
        raise StockError("Type a count for at least one product.")
    return lines


@transaction.atomic
def recount(counts, *, user, kind=Recount.Kind.SPOT, note=""):
    """counts: {product: (counted, reason)}. Saves a Recount and returns it with the movements made."""
    lines = check_counts(counts)
    session = Recount.objects.create(kind=kind, note=note, user=user)
    movements = []
    for line in lines:
        reason = line.reason or "Count matched"
        movement = set_counted_stock(line.product, line.counted, kind=StockMovement.Kind.RECOUNT, user=user,
                                     reason=reason, reference=str(session))
        if movement:
            movements.append(movement)
    return session, movements


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
