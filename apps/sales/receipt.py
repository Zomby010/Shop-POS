"""Plain-text receipt layout and ESC/POS printing at 58 mm (32 chars) or 80 mm (48 chars)."""

import logging

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


def receipt_lines(sale, shop=None, reprint=False):
    shop = shop or ShopSettings.load()
    width = shop.receipt_chars
    rule = "-" * width
    out = [line.center(width) for line in _wrap(shop.business_name.upper(), width)]
    for extra in (shop.address, shop.phone and f"Tel: {shop.phone}", shop.kra_pin and f"PIN: {shop.kra_pin}"):
        if extra:
            out += [line.center(width) for line in _wrap(extra, width)]
    out.append(rule)
    out.append(_lr(f"Receipt {sale.receipt_no}", "REPRINT" if reprint else "", width))
    out.append(timezone.localtime(sale.completed_at).strftime("%d/%m/%Y %H:%M"))
    out.append(f"Served by: {sale.cashier.get_full_name() or sale.cashier.username}")
    out.append(rule)
    for line in sale.lines.all():
        out += _wrap(line.description, width)
        unit = "" if line.unit == "pcs" else f" {line.unit}"
        detail = f"  {_qty(line.quantity, line.unit)}{unit} x {_money(line.unit_price)}"
        if line.tier_applied:
            detail += " bulk"
        out.append(_lr(detail, _money(line.line_total), width))
    out.append(rule)
    out.append(_lr("TOTAL", f"KSh {_money(sale.total)}", width))
    for payment in sale.payments.all():
        out.append(_lr(payment.get_method_display(), _money(payment.amount), width))
    if sale.amount_tendered and sale.paid_by(Payment.Method.CASH):
        out.append(_lr("Cash given", _money(sale.amount_tendered), width))
        out.append(_lr("Change", _money(sale.change_given), width))
    if sale.customer_id:
        out.append(_lr("Deni customer", sale.customer.name[: width // 2], width))
        out.append(_lr("Balance owed", _money(sale.customer.balance), width))
    out.append(rule)
    if shop.receipt_footer:
        out += [line.center(width) for line in _wrap(shop.receipt_footer, width)]
    return out


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


def send_to_printer(lines, shop=None, with_logo=True):
    shop = shop or ShopSettings.load()
    try:
        device = open_printer(shop)
        if with_logo and shop.logo:
            try:
                device.set(align="center")
                device.image(shop.logo.path, center=True)
            except Exception:  # a logo problem must never stop the receipt
                log.warning("Could not print logo", exc_info=True)
        device.set(align="left")
        device.text("\n".join(lines) + "\n\n")
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
        send_to_printer(receipt_lines(sale, shop, reprint=reprint), shop)
    except PrinterError as exc:
        return str(exc)
    return None


def sample_receipt_lines(shop):
    width = shop.receipt_chars
    return [
        shop.business_name.upper().center(width),
        "-" * width,
        "Printer test".center(width),
        _lr("Pishori 0.25 kg x 200.00", "50.00", width),
        f"Paper width {shop.paper_width_mm} mm, {width} characters".center(width),
        "-" * width,
    ]
