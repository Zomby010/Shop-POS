"""The only place stock levels change."""

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from apps.core.money import ZERO, q2, q3

from .models import Product, StockMovement

COST_UPDATING_KINDS = {StockMovement.Kind.PURCHASE, StockMovement.Kind.OPENING}


@transaction.atomic
def record_movement(product, kind, quantity, *, unit_cost=None, user=None, reason="", reference=""):
    """Add a stock movement and update the product's cached stock (and average cost on purchases)."""
    quantity = q3(quantity)
    product = Product.objects.select_for_update().get(pk=product.pk)
    if unit_cost is not None and kind in COST_UPDATING_KINDS and quantity > ZERO:
        unit_cost = Decimal(unit_cost)
        on_hand = max(product.stock_qty, ZERO)
        total_qty = on_hand + quantity
        product.cost_price = q2((on_hand * product.cost_price + quantity * unit_cost) / total_qty)
    movement = StockMovement.objects.create(
        product=product,
        kind=kind,
        quantity=quantity,
        unit_cost=q2(unit_cost if unit_cost is not None else product.cost_price),
        user=user if user and user.is_authenticated else None,
        reason=reason[:200],
        reference=reference[:60],
    )
    product.stock_qty = q3(product.stock_qty + quantity)
    product.save(update_fields=["stock_qty", "cost_price", "updated_at"])
    return movement


def set_counted_stock(product, counted, *, kind=StockMovement.Kind.RECOUNT, user=None, reason="", reference=""):
    """Adjust stock so it equals `counted`. Returns the movement, or None when nothing changed."""
    product.refresh_from_db(fields=["stock_qty", "cost_price"])
    difference = q3(Decimal(counted) - product.stock_qty)
    if difference == ZERO:
        return None
    return record_movement(product, kind, difference, user=user, reason=reason, reference=reference)


def recalculate_stock(product):
    """Rebuild the cached stock from movements (used by checks and tests)."""
    total = product.movements.aggregate(total=Sum("quantity"))["total"] or ZERO
    Product.objects.filter(pk=product.pk).update(stock_qty=total)
    return total
