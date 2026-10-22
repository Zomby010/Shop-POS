from decimal import Decimal

import pytest

from apps.catalog.models import PriceTier
from apps.core.models import ShopSettings
from apps.documents import services
from apps.documents.models import Document
from apps.documents.pdf import render_document
from apps.partners.models import Customer, Supplier


def doc_data(**overrides):
    data = {
        "kind": "quotation", "party_type": "customer", "customer": "", "supplier": "", "party_name": "",
        "party_details": "", "date": "2026-10-22", "valid_until": "2026-11-05", "due_date": "", "discount": "0",
        "status": "draft", "notes": "",
        "lines-TOTAL_FORMS": "2", "lines-INITIAL_FORMS": "0", "lines-MIN_NUM_FORMS": "1", "lines-MAX_NUM_FORMS": "1000",
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
def test_bulk_quotation_for_customer_uses_tier_prices(owner_client, make_product):
    sugar = make_product("Sugar", "weight", price="180", cost="160")
    PriceTier.objects.create(product=sugar, min_qty=10, unit_price=170)
    customer = Customer.objects.create(name="Hotel Mwangaza")
    response = owner_client.post("/documents/new/", doc_data(
        customer=customer.pk, is_bulk="on",
        **{"lines-0-product": sugar.pk, "lines-0-quantity": "50", "lines-0-description": "", "lines-0-unit_price": "",
           "lines-1-description": "Delivery", "lines-1-quantity": "1", "lines-1-unit_price": "500"},
    ))
    assert response.status_code == 302, response.context["form"].errors if response.context else ""
    quote = Document.objects.get()
    assert quote.code == "QUO-0001"
    lines = list(quote.lines.all())
    assert lines[0].unit_price == Decimal("170.00") and lines[0].unit == "kg" and lines[0].description == "Sugar"
    assert quote.total == Decimal("9000.00")


@pytest.mark.django_db
def test_invoice_for_supplier_and_one_off(owner_client):
    supplier = Supplier.objects.create(name="Bidco")
    owner_client.post("/documents/new/", doc_data(kind="invoice", party_type="supplier", supplier=supplier.pk, **{
        "lines-0-description": "Returned crates", "lines-0-quantity": "10", "lines-0-unit_price": "150"}))
    owner_client.post("/documents/new/", doc_data(kind="invoice", party_type="other", party_name="Church event", **{
        "lines-0-description": "Sodas", "lines-0-quantity": "48", "lines-0-unit_price": "60"}))
    codes = sorted(Document.objects.values_list("number", flat=True))
    assert codes == [1, 2]
    assert Document.objects.get(supplier=supplier).total == Decimal("1500.00")
    assert Document.objects.get(party_name="Church event").party_display == "Church event"


@pytest.mark.django_db
def test_party_is_required(owner_client):
    response = owner_client.post("/documents/new/", doc_data(**{
        "lines-0-description": "x", "lines-0-quantity": "1", "lines-0-unit_price": "1"}))
    assert response.status_code == 200 and not Document.objects.exists()


@pytest.mark.django_db
def test_convert_and_pay(owner, owner_client):
    customer = Customer.objects.create(name="A")
    quote = Document.objects.create(kind="quotation", number=services.next_number("quotation"), customer=customer)
    quote.lines.create(description="Rice 50 kg", quantity=1, unit="bag", unit_price=9500, line_total=9500)
    response = owner_client.post(f"/documents/{quote.pk}/convert/")
    invoice = Document.objects.get(kind="invoice")
    assert response["Location"] == f"/documents/{invoice.pk}/"
    assert invoice.total == Decimal("9500.00") and invoice.converted_from == quote
    quote.refresh_from_db()
    assert quote.status == "converted"
    with pytest.raises(services.DocumentError):
        services.convert_to_invoice(quote, user=owner)
    owner_client.post(f"/documents/{invoice.pk}/", {"amount": "5000"})
    invoice.refresh_from_db()
    assert invoice.status == "partly_paid" and invoice.balance_due == Decimal("4500.00")
    owner_client.post(f"/documents/{invoice.pk}/", {"amount": "4500"})
    invoice.refresh_from_db()
    assert invoice.status == "paid"


@pytest.mark.django_db
def test_pdf_has_business_name_and_logo(owner_client, tmp_path):
    from django.core.files.base import ContentFile
    from PIL import Image
    from io import BytesIO

    shop = ShopSettings.load()
    shop.business_name = "Kayliz Minimart"
    buffer = BytesIO()
    Image.new("RGB", (120, 60), "green").save(buffer, "PNG")
    shop.logo.save("logo.png", ContentFile(buffer.getvalue()))
    shop.save()
    customer = Customer.objects.create(name="Hotel Mwangaza", phone="0700")
    doc = Document.objects.create(kind="invoice", number=1, customer=customer, discount=100, is_bulk=True)
    doc.lines.create(description="Sugar", quantity=Decimal("50"), unit="kg", unit_price=170, line_total=8500)
    pdf = render_document(doc)
    assert pdf.startswith(b"%PDF")
    assert b"/Image" in pdf or b"/XObject" in pdf
    response = owner_client.get(f"/documents/{doc.pk}/pdf/")
    assert response["Content-Type"] == "application/pdf"
    for url in ["/documents/", f"/documents/{doc.pk}/", f"/documents/{doc.pk}/edit/", "/documents/new/?kind=quotation"]:
        assert owner_client.get(url).status_code == 200, url


@pytest.mark.django_db
def test_cashier_cannot_open_documents(cashier_client):
    assert cashier_client.get("/documents/").status_code == 403
