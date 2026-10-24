"""Plain-text receipt layout and ESC/POS printing at 58 mm (32 chars) or 80 mm (48 chars)."""

import logging
from dataclasses import dataclass

from django.utils import timezone

from apps.core.models import ShopSettings
from apps.core.money import q2

from .models import Payment

log = logging.getLogger(__name__)


def _money(value):
    return f"{q2(value):,.2f}"


def _qty(value, unit):
    """Loose goods always show 3 decimals (0.250 kg); pieces show whole numbers."""
    return f"{value:.3f}" if unit != "pcs" else f"{value:.0f}"


def _lr(left, right, width):
    space = width - len(left) - len(right)
    if space < 1:
        left = left[: max(width - len(right) - 1, 0)]
        space = 1
    return f"{left}{' ' * space}{right}"


def _wrap(text, width):
    words, lines, current = text.split(), [], ""
    for word in words:
        if len(current) + len(word) + (1 if current else 0) > width:
            if current:
                lines.append(current)
            current = word[:width]
        else:
            current = f"{current} {word}" if current else word
    if current:
        lines.append(current)
    return lines or [""]


@dataclass
class Row:
    """One receipt line. `kind` is text, rule (thin dashes), rule2 (thick equals) or gap.

    `size` is normal, tall (double height, same width) or title (double width and height,
    so only half as many characters fit). The printer, the screen and plain text all draw from these rows.
    """

    left: str = ""
    right: str = ""
    kind: str = "text"
    align: str = "left"
    bold: bool = False
    size: str = "normal"
    muted: bool = False


def _shop_name(shop):
    return shop.business_name.upper()


def receipt_rows(sale, shop=None, reprint=False):
    shop = shop or ShopSettings.load()
    width = shop.receipt_chars
    cashier = sale.cashier.get_full_name() or sale.cashier.username
    rows = [Row(line, align="center", bold=True, size="title") for line in _wrap(_shop_name(shop), width // 2)]
    contact = " · ".join(x for x in (shop.address, shop.phone and f"Tel {shop.phone}") if x)
    rows += [Row(line, align="center") for line in _wrap(contact, width)] if contact else []
    if shop.kra_pin:
        rows.append(Row(f"KRA PIN {shop.kra_pin}", align="center"))
    rows.append(Row(kind="rule2"))
    title = "SALES RECEIPT" + (" (COPY)" if reprint else "")
    if sale.status == sale.Status.VOIDED:
        title = "VOIDED SALE"
    rows.append(Row(title, sale.receipt_no, bold=True))
    rows.append(Row(timezone.localtime(sale.completed_at).strftime("%d %b %Y, %H:%M"), f"Cashier: {cashier}"[: width // 2]))
    rows.append(Row(kind="rule"))
    rows.append(Row("ITEM", "AMOUNT", bold=True, muted=True))
    count = 0
    for line in sale.lines.all():
        count += 1
        rows += [Row(text, bold=True) for text in _wrap(line.description, width)]
        unit = "" if line.unit == "pcs" else f" {line.unit}"
        detail = f"  {_qty(line.quantity, line.unit)}{unit} x {_money(line.unit_price)}"
        if line.tier_applied:
            detail += " (bulk)"
        rows.append(Row(detail, _money(line.line_total), muted=True))
    rows.append(Row(kind="rule"))
    rows.append(Row(f"{count} item{'s' if count != 1 else ''}", ""))
    rows.append(Row(kind="rule2"))
    rows.append(Row("TOTAL", f"KSh {_money(sale.total)}", bold=True, size="tall"))
    rows.append(Row(kind="rule2"))
    payments = list(sale.payments.all())
    if payments:
        rows.append(Row("PAID BY", bold=True, muted=True))
        for payment in payments:
            label = f"{payment.get_method_display()} {payment.reference}".strip()
            rows.append(Row(f"  {label}", _money(payment.amount)))
    if sale.amount_tendered and sale.paid_by(Payment.Method.CASH):
        rows.append(Row("  Cash given", _money(sale.amount_tendered)))
        rows.append(Row("  Change", _money(sale.change_given), bold=True))
    if sale.customer_id:
        rows.append(Row(kind="rule"))
        rows.append(Row("Deni customer", sale.customer.name[: width // 2]))
        rows.append(Row("Balance owed", f"KSh {_money(sale.customer.balance)}", bold=True))
    rows.append(Row(kind="rule"))
    if shop.receipt_footer:
        rows += [Row(line, align="center", bold=True) for line in _wrap(shop.receipt_footer, width)]
    else:
        rows.append(Row("Thank you for shopping with us!", align="center", bold=True))
    rows.append(Row(f"Receipt {sale.receipt_no} · Prices in KSh", align="center", muted=True))
    return rows


def _text(row, width):
    if row.kind == "rule":
        return "-" * width
    if row.kind == "rule2":
        return "=" * width
    if row.kind == "gap":
        return ""
    if row.right:
        return _lr(row.left, row.right, width)
    return row.left.center(width).rstrip() if row.align == "center" else row.left[:width]


def receipt_lines(sale, shop=None, reprint=False):
    """The receipt as plain text lines, for checks and anywhere styling isn't available."""
    shop = shop or ShopSettings.load()
    return [_text(row, shop.receipt_chars) for row in receipt_rows(sale, shop, reprint=reprint)]


class PrinterError(Exception):
    pass


def open_printer(shop):
    from escpos import printer

    address = (shop.printer_address or "").strip()
    if shop.printer_connection == shop.Connection.USB:
        try:
            vendor, product = (int(part, 16) for part in address.split(":"))
        except ValueError:
            raise PrinterError("USB address must look like 0x0416:0x5011 (vendor:product).")
        return printer.Usb(vendor, product)
    if shop.printer_connection == shop.Connection.NETWORK:
        if not address:
            raise PrinterError("Enter the printer's IP address in Settings.")
        return printer.Network(address, timeout=5)
    if shop.printer_connection == shop.Connection.WINDOWS:
        if not hasattr(printer, "Win32Raw"):
            raise PrinterError("Windows printing only works on Windows with pywin32 installed.")
        return printer.Win32Raw(address or None)
    raise PrinterError("No receipt printer is set up. Choose one in Settings.")


def _print_rows(device, rows, width):
    for row in rows:
        title = row.size == "title"
        tall = title or row.size == "tall"
        centered = row.align == "center" or title
        device.set(align="center" if centered else "left", bold=row.bold, normal_textsize=not tall,
                   double_width=title, double_height=tall)
        # Centred lines go unpadded so the printer centres them; the rest are laid out to the paper width.
        device.text((row.left if centered and row.kind == "text" else _text(row, width // 2 if title else width)) + "\n")
    device.set(align="left", bold=False, normal_textsize=True)


def send_to_printer(rows, shop=None, with_logo=True):
    """Print receipt rows (or plain text lines) on the configured ESC/POS printer."""
    shop = shop or ShopSettings.load()
    rows = [row if isinstance(row, Row) else Row(row) for row in rows]
    try:
        device = open_printer(shop)
        if with_logo and shop.logo:
            try:
                device.set(align="center")
                device.image(shop.logo.path, center=True)
            except Exception:  # a logo problem must never stop the receipt
                log.warning("Could not print logo", exc_info=True)
        _print_rows(device, rows, shop.receipt_chars)
        device.text("\n\n")
        device.cut()
        device.close()
    except PrinterError:
        raise
    except Exception as exc:
        raise PrinterError(f"Printer problem: {exc}") from exc


def print_receipt(sale, reprint=False):
    """Print a receipt. Returns None on success or an error message; the sale is already saved either way."""
    shop = ShopSettings.load()
    try:
        send_to_printer(receipt_rows(sale, shop, reprint=reprint), shop)
    except PrinterError as exc:
        return str(exc)
    return None


def sample_receipt_lines(shop):
    width = shop.receipt_chars
    return [
        Row(_shop_name(shop)[: width // 2], align="center", bold=True, size="title"),
        Row(kind="rule2"),
        Row("PRINTER TEST", align="center", bold=True),
        Row("Pishori Rice", bold=True),
        Row("  0.250 kg x 200.00", "50.00", muted=True),
        Row(kind="rule2"),
        Row("TOTAL", "KSh 50.00", bold=True, size="tall"),
        Row(kind="rule2"),
        Row(f"Paper {shop.paper_width_mm} mm, {width} characters", align="center"),
    ]
