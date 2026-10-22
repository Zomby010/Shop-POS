from decimal import Decimal

from django import template

from apps.core.money import q2

register = template.Library()


@register.filter
def get_item(mapping, key):
    return mapping.get(key, "") if hasattr(mapping, "get") else ""


@register.filter
def money(value):
    """1250 -> '1,250.00'"""
    try:
        return f"{q2(value or 0):,.2f}"
    except (ArithmeticError, TypeError, ValueError):
        return value


@register.filter
def qty(value):
    """Drop trailing zeros: 0.250 -> '0.25', 3.000 -> '3'."""
    try:
        text = format(Decimal(value).normalize(), "f")
    except (ArithmeticError, TypeError, ValueError):
        return value
    return text
