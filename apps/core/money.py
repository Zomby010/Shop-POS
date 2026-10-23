"""Decimal helpers. All money and quantities go through these, never floats."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

MONEY = Decimal("0.01")
QTY = Decimal("0.001")
SHILLING = Decimal("1")
ZERO = Decimal("0")


def to_decimal(value, default=None):
    """Parse user input (str, int, Decimal) into a Decimal, or return default."""
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    text = str(value).strip().replace(",", "")
    if text == "":
        return default
    try:
        return Decimal(text)
    except InvalidOperation:
        return default


def q2(value):
    return Decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def q3(value):
    return Decimal(value).quantize(QTY, rounding=ROUND_HALF_UP)


def round_shilling(value):
    """Round to the nearest whole shilling (used for loose-goods line totals)."""
    return Decimal(value).quantize(SHILLING, rounding=ROUND_HALF_UP).quantize(MONEY)


def ksh(value):
    """Format for display: 'KSh 1,250.00'."""
    return f"KSh {q2(value or 0):,.2f}"
