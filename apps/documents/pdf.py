"""Invoice and quotation PDFs with the business name and logo from settings."""

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.core.models import ShopSettings
from apps.core.money import q2

BRAND = colors.HexColor("#11734B")


def _m(value):
    return f"{q2(value):,.2f}"


def _q(value):
    return format(value.normalize(), "f")


def render_document(document):
    shop = ShopSettings.load()
    buffer = BytesIO()
    pdf = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title=f"{document.get_kind_display()} {document.code}",
                            author=shop.business_name)
    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    small = ParagraphStyle("small", parent=normal, fontSize=8.5, leading=11, textColor=colors.HexColor("#475467"))
    right = ParagraphStyle("right", parent=normal, alignment=TA_RIGHT)
    title = ParagraphStyle("title", parent=styles["Title"], alignment=TA_RIGHT, textColor=BRAND, fontSize=22, spaceAfter=2)
    story = []

    business = [f"<b><font size=14>{shop.business_name}</font></b>"]
    for extra in (shop.address, shop.phone and f"Tel: {shop.phone}", shop.kra_pin and f"KRA PIN: {shop.kra_pin}"):
        if extra:
            business.append(extra)
    left_cell = [Paragraph("<br/>".join(business), normal)]
    if shop.logo:
        try:
            logo = Image(shop.logo.path)
            ratio = logo.imageWidth / float(logo.imageHeight)
            logo.drawHeight = 22 * mm
            logo.drawWidth = 22 * mm * ratio
            logo.hAlign = "LEFT"
            left_cell.insert(0, logo)
        except Exception:
            pass
    meta = [f"<b>{document.code}</b>", f"Date: {document.date:%d %b %Y}"]
    if document.kind == document.Kind.QUOTATION and document.valid_until:
        meta.append(f"Valid until: {document.valid_until:%d %b %Y}")
    if document.kind == document.Kind.INVOICE and document.due_date:
        meta.append(f"Due: {document.due_date:%d %b %Y}")
    if document.is_bulk:
        meta.append("Bulk order pricing")
    right_cell = [Paragraph(document.get_kind_display().upper(), title), Paragraph("<br/>".join(meta), right)]
    header = Table([[left_cell, right_cell]], colWidths=[95 * mm, 79 * mm])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [header, Spacer(1, 8 * mm)]

    party = document.party
    to_lines = [f"<b>{document.party_display}</b>"]
    if party is not None:
        to_lines += [x for x in (getattr(party, "contact_person", ""), party.phone, party.email, party.address) if x]
        if getattr(party, "kra_pin", ""):
            to_lines.append(f"KRA PIN: {party.kra_pin}")
    elif document.party_details:
        to_lines.append(document.party_details)
    label = "Quotation for" if document.kind == document.Kind.QUOTATION else "Bill to"
    story += [Paragraph(f"<font color='#667085'>{label}</font>", small), Paragraph("<br/>".join(to_lines), normal),
              Spacer(1, 6 * mm)]

    rows = [["#", "Description", "Qty", "Unit", "Unit price", "Amount"]]
    for i, line in enumerate(document.lines.all(), start=1):
        rows.append([str(i), Paragraph(line.description, normal), _q(line.quantity), line.unit,
                     _m(line.unit_price), _m(line.line_total)])
    subtotal = document.subtotal
    totals = [["", "", "", "", "Subtotal", _m(subtotal)]]
    if document.discount:
        totals.append(["", "", "", "", "Discount", f"-{_m(document.discount)}"])
    totals.append(["", "", "", "", "TOTAL (KSh)", _m(document.total)])
    if document.kind == document.Kind.INVOICE and document.amount_paid:
        totals += [["", "", "", "", "Paid", _m(document.amount_paid)],
                   ["", "", "", "", "Balance due", _m(document.balance_due)]]
    table = Table(rows + totals, colWidths=[8 * mm, 74 * mm, 18 * mm, 14 * mm, 30 * mm, 30 * mm], repeatRows=1)
    n = len(rows)
    total_row = n + (2 if document.discount else 1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("ALIGN", (4, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 1), (-1, n - 1), 0.25, colors.HexColor("#E3E6EB")),
        ("LINEABOVE", (4, n), (-1, n), 0.75, colors.HexColor("#98A2B3")),
        ("FONTNAME", (4, total_row), (-1, total_row), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [table, Spacer(1, 8 * mm)]
    if document.notes:
        story += [Paragraph("<b>Notes</b>", normal), Paragraph(document.notes.replace("\n", "<br/>"), normal),
                  Spacer(1, 6 * mm)]
    if document.kind == document.Kind.QUOTATION:
        story.append(Paragraph("Prices are in Kenya Shillings. This quotation is not a tax invoice.", small))
    story.append(Paragraph(f"Thank you for your business. {shop.business_name}", small))
    pdf.build(story)
    return buffer.getvalue()
