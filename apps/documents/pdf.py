"""Invoice and quotation PDFs with the business name and logo from settings.

Layout: an accent bar and the business identity at the top, the document title and number on the right,
a summary strip (who it is for, the dates, the amount), the line items, the totals ending in a filled
"amount due" band, then notes and, on quotations, an acceptance line. Set in Inter, bundled in static/fonts.
"""

from html import escape
from io import BytesIO

from django.conf import settings
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.core.models import ShopSettings
from apps.core.money import q2

BRAND = colors.HexColor("#11734B")
BRAND_SOFT = colors.HexColor("#E8F3EE")
INK = colors.HexColor("#101828")
MUTED = colors.HexColor("#667085")
LINE = colors.HexColor("#E4E7EC")
PANEL = colors.HexColor("#F7F8FA")

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN

FONT, FONT_SEMI, FONT_BOLD = "Inter", "Inter-SemiBold", "Inter-Bold"


def _register_fonts():
    if FONT in pdfmetrics.getRegisteredFontNames():
        return
    folder = settings.BASE_DIR / "static" / "fonts"
    for name, file in ((FONT, "Inter-Regular.ttf"), (FONT_SEMI, "Inter-SemiBold.ttf"), (FONT_BOLD, "Inter-Bold.ttf")):
        pdfmetrics.registerFont(TTFont(name, str(folder / file)))
    pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=FONT_BOLD, italic=FONT, boldItalic=FONT_BOLD)


def _m(value):
    return f"{q2(value):,.2f}"


def _q(value):
    return format(value.normalize(), "f")


def _styles():
    base = ParagraphStyle("base", fontName=FONT, fontSize=9.5, leading=13.5, textColor=INK)
    return {
        "base": base,
        "right": ParagraphStyle("right", parent=base, alignment=TA_RIGHT),
        "label": ParagraphStyle("label", parent=base, fontName=FONT_SEMI, fontSize=7.5, leading=10, textColor=MUTED,
                                spaceAfter=3),
        "small": ParagraphStyle("small", parent=base, fontSize=8.5, leading=12, textColor=MUTED),
        "business": ParagraphStyle("business", parent=base, fontName=FONT_BOLD, fontSize=15, leading=19),
        "title": ParagraphStyle("title", parent=base, fontName=FONT_BOLD, fontSize=26, leading=30, alignment=TA_RIGHT,
                                textColor=BRAND),
        "number": ParagraphStyle("number", parent=base, fontName=FONT_SEMI, fontSize=11, leading=14,
                                 alignment=TA_RIGHT),
        "party": ParagraphStyle("party", parent=base, fontName=FONT_SEMI, fontSize=11, leading=15),
        "amount": ParagraphStyle("amount", parent=base, fontName=FONT_BOLD, fontSize=17, leading=21,
                                 textColor=BRAND),
        "cell": ParagraphStyle("cell", parent=base, fontSize=9.5, leading=13),
        "head": ParagraphStyle("head", parent=base, fontName=FONT_SEMI, fontSize=7.5, leading=10, textColor=MUTED),
        "head_r": ParagraphStyle("head_r", parent=base, fontName=FONT_SEMI, fontSize=7.5, leading=10,
                                 textColor=MUTED, alignment=TA_RIGHT),
    }


def _label(text, styles):
    return Paragraph(text.upper(), styles["label"])


def _page_decor(shop, document):
    contact = "  ·  ".join(x for x in (shop.business_name, shop.phone, shop.kra_pin and f"KRA PIN {shop.kra_pin}") if x)

    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(BRAND)
        canvas.rect(0, PAGE_H - 5 * mm, PAGE_W, 5 * mm, stroke=0, fill=1)
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.6)
        canvas.line(MARGIN, 14 * mm, PAGE_W - MARGIN, 14 * mm)
        canvas.setFont(FONT, 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(MARGIN, 9.5 * mm, contact)
        canvas.drawRightString(PAGE_W - MARGIN, 9.5 * mm, f"{document.code}  ·  Page {doc.page}")
        canvas.restoreState()

    return draw


def _header(shop, document, styles):
    identity = []
    if shop.logo:
        try:
            with shop.logo.open("rb") as f:
                logo = Image(BytesIO(f.read()))
            ratio = logo.imageWidth / float(logo.imageHeight)
            logo.drawHeight = 18 * mm
            logo.drawWidth = min(18 * mm * ratio, 45 * mm)
            logo.drawHeight = logo.drawWidth / ratio
            logo.hAlign = "LEFT"
            identity += [logo, Spacer(1, 3 * mm)]
        except Exception:  # an unreadable logo must not stop the document
            pass
    identity.append(Paragraph(escape(shop.business_name), styles["business"]))
    contact = [escape(x) for x in (shop.address, shop.phone and f"Tel {shop.phone}",
                                    shop.kra_pin and f"KRA PIN {shop.kra_pin}") if x]
    if contact:
        identity.append(Paragraph("<br/>".join(contact), styles["small"]))
    title = [Paragraph(document.get_kind_display().upper(), styles["title"]),
             Paragraph(document.code, styles["number"])]
    table = Table([[identity, title]], colWidths=[CONTENT_W * 0.58, CONTENT_W * 0.42])
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    return table


def _summary(document, styles):
    is_quote = document.kind == document.Kind.QUOTATION
    party = document.party
    who = [_label("Quotation for" if is_quote else "Bill to", styles),
           Paragraph(escape(document.party_display or "-"), styles["party"])]
    details = []
    if party is not None:
        details += [x for x in (getattr(party, "contact_person", ""), party.phone, party.email, party.address) if x]
        if getattr(party, "kra_pin", ""):
            details.append(f"KRA PIN {party.kra_pin}")
    elif document.party_details:
        details.append(document.party_details)
    if details:
        who.append(Paragraph("<br/>".join(escape(x) for x in details), styles["small"]))

    dates = [("Date", f"{document.date:%d %b %Y}")]
    if is_quote and document.valid_until:
        dates.append(("Valid until", f"{document.valid_until:%d %b %Y}"))
    if not is_quote and document.due_date:
        dates.append(("Due date", f"{document.due_date:%d %b %Y}"))
    if document.is_bulk:
        dates.append(("Pricing", "Bulk order"))
    if not is_quote and document.status in (document.Status.PAID, document.Status.PARTLY_PAID):
        dates.append(("Status", document.get_status_display()))
    when = [_label("Details", styles)] + [
        Paragraph(f"<font color='#667085'>{k}</font>&nbsp;&nbsp;{escape(v)}", styles["base"]) for k, v in dates
    ]

    if is_quote:
        amount_label, amount = "Quotation total", document.total
    else:
        amount_label, amount = "Amount due", document.balance_due
    money = [_label(amount_label, styles), Paragraph(f"KSh {_m(amount)}", styles["amount"])]
    if document.due_date and not is_quote:
        money.append(Paragraph(f"by {document.due_date:%d %b %Y}", styles["small"]))
    elif is_quote and document.valid_until:
        money.append(Paragraph(f"valid until {document.valid_until:%d %b %Y}", styles["small"]))

    table = Table([[who, when, money]], colWidths=[CONTENT_W * 0.40, CONTENT_W * 0.30, CONTENT_W * 0.30])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (1, 0), PANEL),
        ("BACKGROUND", (2, 0), (2, 0), BRAND_SOFT),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LINEAFTER", (0, 0), (0, 0), 0.6, LINE),
        ("ROUNDEDCORNERS", [4, 4, 4, 4]),
    ]))
    return table


def _items(document, styles):
    head = [Paragraph("#", styles["head"]), Paragraph("DESCRIPTION", styles["head"]),
            Paragraph("QTY", styles["head_r"]), Paragraph("UNIT PRICE", styles["head_r"]),
            Paragraph("AMOUNT", styles["head_r"])]
    rows = [head]
    for i, line in enumerate(document.lines.all(), start=1):
        qty = _q(line.quantity) + (f" {line.unit}" if line.unit else "")
        rows.append([Paragraph(str(i), styles["small"]), Paragraph(escape(line.description), styles["cell"]),
                     Paragraph(escape(qty), styles["right"]), Paragraph(_m(line.unit_price), styles["right"]),
                     Paragraph(_m(line.line_total), styles["right"])])
    table = Table(rows, colWidths=[9 * mm, CONTENT_W - 9 * mm - 26 * mm - 30 * mm - 32 * mm, 26 * mm, 30 * mm, 32 * mm],
                  repeatRows=1)
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, 0), 1.2, BRAND),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
    ]))
    return table


def _totals(document, styles):
    is_quote = document.kind == document.Kind.QUOTATION
    rows = [["Subtotal", _m(document.subtotal)]]
    if document.discount:
        rows.append(["Discount", f"-{_m(document.discount)}"])
    if not is_quote and document.amount_paid:
        rows += [["Total", _m(document.total)], ["Paid", f"-{_m(document.amount_paid)}"]]
        band = ["Balance due (KSh)", _m(document.balance_due)]
    else:
        band = ["Total (KSh)", _m(document.total)]
    rows.append(band)
    last = len(rows) - 1
    table = Table(rows, colWidths=[42 * mm, 36 * mm], hAlign="RIGHT")
    table.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), FONT, 9.5),
        ("TEXTCOLOR", (0, 0), (0, last - 1), MUTED),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, last), (-1, last), BRAND),
        ("TEXTCOLOR", (0, last), (-1, last), colors.white),
        ("FONT", (0, last), (-1, last), FONT_BOLD, 11.5),
        ("TOPPADDING", (0, last), (-1, last), 8), ("BOTTOMPADDING", (0, last), (-1, last), 8),
        ("ROUNDEDCORNERS", [3, 3, 3, 3]),
    ]))
    return table


def render_document(document):
    _register_fonts()
    shop = ShopSettings.load()
    styles = _styles()
    buffer = BytesIO()
    pdf = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=14 * mm,
                            bottomMargin=20 * mm, title=f"{document.get_kind_display()} {document.code}",
                            author=shop.business_name)
    is_quote = document.kind == document.Kind.QUOTATION
    story = [_header(shop, document, styles), Spacer(1, 8 * mm), _summary(document, styles), Spacer(1, 8 * mm),
             _items(document, styles), Spacer(1, 5 * mm), KeepTogether(_totals(document, styles)),
             Spacer(1, 9 * mm)]
    if document.notes:
        notes = Table([[[_label("Payment details and notes", styles),
                         Paragraph(escape(document.notes).replace("\n", "<br/>"), styles["base"])]]],
                      colWidths=[CONTENT_W])
        notes.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PANEL), ("LEFTPADDING", (0, 0), (-1, -1), 10),
                                   ("RIGHTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 8),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 10), ("ROUNDEDCORNERS", [4, 4, 4, 4])]))
        story += [KeepTogether(notes), Spacer(1, 7 * mm)]
    if is_quote:
        terms = "Prices are in Kenya Shillings."
        if document.valid_until:
            terms += f" This quotation is valid until {document.valid_until:%d %b %Y}."
        terms += " It is not a tax invoice."
        sign = Table([["Accepted by", "", "Date", ""]], colWidths=[24 * mm, 70 * mm, 12 * mm, 40 * mm], hAlign="LEFT")
        sign.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), FONT, 9), ("TEXTCOLOR", (0, 0), (-1, -1), MUTED),
                                  ("LINEBELOW", (1, 0), (1, 0), 0.6, MUTED), ("LINEBELOW", (3, 0), (3, 0), 0.6, MUTED),
                                  ("VALIGN", (0, 0), (-1, -1), "BOTTOM"), ("TOPPADDING", (0, 0), (-1, -1), 14)]))
        story += [KeepTogether([Paragraph(terms, styles["small"]), Spacer(1, 4 * mm), sign])]
    else:
        story.append(Paragraph(f"Thank you for your business. Please quote <b>{document.code}</b> when paying.",
                               styles["small"]))
    decor = _page_decor(shop, document)
    pdf.build(story, onFirstPage=decor, onLaterPages=decor)
    return buffer.getvalue()
