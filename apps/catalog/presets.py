"""Parse and format quick-sale presets such as '1/4 kg', '500 g', '1/2 L' or 'KSh 50'."""

import re
from decimal import Decimal
from fractions import Fraction

from apps.core.money import q3, to_decimal

AMOUNT_RE = re.compile(r"^(?:ksh\.?|kes|sh\.?)\s*([\d,.]+)$|^([\d,.]+)\s*(?:/=|/-|ksh|bob|shillings?)$", re.I)
QTY_RE = re.compile(r"^(\d+(?:\.\d+)?|\d+\s*/\s*\d+|\d+\s+\d+\s*/\s*\d+)\s*([a-z]*)$", re.I)

UNIT_ALIASES = {
    "kg": ("kg", Decimal(1)),
    "kgs": ("kg", Decimal(1)),
    "kilo": ("kg", Decimal(1)),
    "g": ("kg", Decimal("0.001")),
    "gm": ("kg", Decimal("0.001")),
    "l": ("L", Decimal(1)),
    "lt": ("L", Decimal(1)),
    "ltr": ("L", Decimal(1)),
    "litre": ("L", Decimal(1)),
    "liter": ("L", Decimal(1)),
    "ml": ("L", Decimal("0.001")),
    "pc": ("pcs", Decimal(1)),
    "pcs": ("pcs", Decimal(1)),
    "": (None, Decimal(1)),
}

NICE_FRACTIONS = {
    Decimal("0.25"): "1/4",
    Decimal("0.5"): "1/2",
    Decimal("0.75"): "3/4",
}


class PresetError(ValueError):
    pass


def _number(text):
    text = re.sub(r"\s*/\s*", "/", text.strip())
    if "/" in text:
        parts = text.split()
        whole = Fraction(int(parts[0])) if len(parts) == 2 else Fraction(0)
        frac = Fraction(parts[-1].replace(" ", ""))
        value = whole + frac
        return Decimal(value.numerator) / Decimal(value.denominator)
    return Decimal(text)


def parse_preset(text, unit):
    """Return (kind, value) for preset text on a product sold in `unit` ('pcs', 'kg' or 'L')."""
    raw = (text or "").strip()
    if not raw:
        raise PresetError("Empty preset")
    m = AMOUNT_RE.match(raw.replace(" ", "") if raw.lower().startswith(("ksh", "kes", "sh")) else raw)
    if m:
        amount = to_decimal(m.group(1) or m.group(2))
        if amount is None or amount <= 0:
            raise PresetError(f"Bad amount in '{raw}'")
        return "amount", amount
    m = QTY_RE.match(raw)
    if not m:
        raise PresetError(f"Can't read '{raw}'. Use e.g. '1/4 kg', '500 g', '1 L' or 'KSh 50'")
    number_text, unit_text = m.groups()
    alias = UNIT_ALIASES.get(unit_text.lower())
    if alias is None:
        raise PresetError(f"Unknown unit '{unit_text}' in '{raw}'")
    base_unit, factor = alias
    if base_unit is not None and base_unit != unit:
        raise PresetError(f"'{raw}' is in {base_unit} but the product is sold in {unit}")
    try:
        value = q3(_number(number_text) * factor)
    except (ArithmeticError, ValueError, ZeroDivisionError):
        raise PresetError(f"Bad number in '{raw}'")
    if value <= 0:
        raise PresetError(f"'{raw}' must be more than zero")
    if unit == "pcs" and value != value.to_integral_value():
        raise PresetError(f"'{raw}': pieces must be whole numbers")
    return "qty", value


def parse_preset_list(text, unit):
    """Parse '1/4 kg; 1/2 kg; KSh 50' into a list of (kind, value). Raises PresetError."""
    items = [p for p in re.split(r"[;|\n]", text or "") if p.strip()]
    return [parse_preset(p, unit) for p in items]


def format_quantity(value, unit):
    value = Decimal(value)
    nice = NICE_FRACTIONS.get(value.normalize())
    if nice and unit != "pcs":
        return f"{nice} {unit}"
    text = format(value.normalize(), "f")
    return f"{text} {unit}"


def format_preset(kind, value, unit):
    if kind == "amount":
        return f"KSh {Decimal(value).normalize():f}"
    return format_quantity(value, unit)
