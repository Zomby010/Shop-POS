"""Line pricing for the sell screen, invoices and quotations."""

from dataclasses import dataclass
from decimal import Decimal

from apps.core.money import ZERO, q2, q3, round_shilling


class PricingError(ValueError):
    pass


@dataclass
class LinePrice:
    quantity: Decimal
    unit_price: Decimal
    total: Decimal
    tier_applied: bool


def unit_price_for(product, quantity, tiers=None):
    """The selling price per unit for a line of `quantity`, applying the best bulk tier."""
    tiers = list(product.tiers.all()) if tiers is None else tiers
    best = None
    for tier in tiers:
        if quantity >= tier.min_qty and (best is None or tier.min_qty > best.min_qty):
            best = tier
    if best is not None:
        return best.unit_price, True
    return product.selling_price, False


def line_total(product, quantity, unit_price):
    raw = quantity * unit_price
    return round_shilling(raw) if product.is_loose else q2(raw)


def price_by_quantity(product, quantity):
    quantity = q3(quantity)
    if quantity <= ZERO:
        raise PricingError("Quantity must be more than zero")
    if not product.is_loose and quantity != quantity.to_integral_value():
        raise PricingError(f"{product.name} is sold by the piece, so the quantity must be a whole number")
    unit_price, tier = unit_price_for(product, quantity)
    return LinePrice(quantity, unit_price, line_total(product, quantity, unit_price), tier)


def price_by_amount(product, amount):
    """Customer asks for 'KSh 50 of oil': work out the quantity they get."""
    if not product.is_loose:
        raise PricingError(f"{product.name} is sold by the piece; enter a quantity instead")
    amount = round_shilling(amount)
    if amount <= ZERO:
        raise PricingError("Amount must be more than zero")
    if product.selling_price <= ZERO:
        raise PricingError(f"{product.name} has no selling price")
    unit_price, tier = unit_price_for(product, amount / product.selling_price)
    quantity = q3(amount / unit_price)
    # A tier price gives more quantity, which can only qualify for the same or a better tier.
    better_price, better_tier = unit_price_for(product, quantity)
    if better_price != unit_price:
        unit_price, tier = better_price, better_tier
        quantity = q3(amount / unit_price)
    if quantity <= ZERO:
        raise PricingError("That amount is too small to sell")
    return LinePrice(quantity, unit_price, amount, tier)
