from django.db import transaction

from apps.catalog.pricing import unit_price_for
from apps.core.models import Sequence
from apps.core.money import ZERO, q2

from .models import Document, DocumentLine


class DocumentError(ValueError):
    pass


def next_number(kind):
    return Sequence.next(kind)


def suggested_price(product, quantity, bulk):
    """Bulk documents use tier prices; others use the normal selling price."""
    if bulk:
        return unit_price_for(product, quantity)[0]
    return product.selling_price


def line_amount(quantity, unit_price):
    return q2(quantity * unit_price)


@transaction.atomic
def convert_to_invoice(quotation, *, user):
    if quotation.kind != Document.Kind.QUOTATION:
        raise DocumentError("Only quotations can be converted.")
    if hasattr(quotation, "converted_to"):
        raise DocumentError(f"Already converted to {quotation.converted_to.code}.")
    invoice = Document.objects.create(
        kind=Document.Kind.INVOICE, number=next_number(Document.Kind.INVOICE), party_type=quotation.party_type,
        customer=quotation.customer, supplier=quotation.supplier, party_name=quotation.party_name,
        party_details=quotation.party_details, is_bulk=quotation.is_bulk, discount=quotation.discount,
        notes=quotation.notes, converted_from=quotation, created_by=user,
    )
    DocumentLine.objects.bulk_create(
        DocumentLine(document=invoice, product=l.product, description=l.description, quantity=l.quantity,
                     unit=l.unit, unit_price=l.unit_price, line_total=l.line_total, order=l.order)
        for l in quotation.lines.all()
    )
    quotation.status = Document.Status.CONVERTED
    quotation.save(update_fields=["status"])
    return invoice


def record_payment(invoice, amount):
    if invoice.kind != Document.Kind.INVOICE:
        raise DocumentError("Payments are recorded on invoices.")
    if amount <= ZERO:
        raise DocumentError("Enter an amount.")
    invoice.amount_paid = q2(invoice.amount_paid + amount)
    invoice.status = Document.Status.PAID if invoice.amount_paid >= invoice.total else Document.Status.PARTLY_PAID
    invoice.save(update_fields=["amount_paid", "status"])
    return invoice
