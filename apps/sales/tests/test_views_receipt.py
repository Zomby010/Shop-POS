from decimal import Decimal

import pytest
from escpos.printer import Dummy

from apps.core.models import ShopSettings
from apps.partners.models import Customer
from apps.sales import receipt, services
from apps.sales.models import Sale


@pytest.mark.django_db
def test_sell_screen_shows_quick_sale_buttons(cashier_client, rice, oil):
    response = cashier_client.get("/sell/")
    assert response.status_code == 200
    content = response.content.decode()
    assert "1/4 kg" in content and "KSh 50" in content and "F1" in content


@pytest.mark.django_db
def test_scan_flow(cashier_client, cashier, soap, rice):
    response = cashier_client.post("/sell/cart/scan/", {"code": "3*6161100110016"})
    assert b"Bar soap" in response.content
    response = cashier_client.post("/sell/cart/scan/", {"code": "999"})
    assert b"Nothing found" in response.content
    response = cashier_client.post("/sell/cart/scan/", {"code": "pish"})  # one name match is added straight away
    assert b"Added Pishori" in response.content
    cart = services.current_cart(cashier)
    assert cart.lines.get(product=soap).quantity == Decimal("3.000")


@pytest.mark.django_db
def test_name_search_with_several_matches_offers_choices(cashier_client, make_product):
    make_product("Royco Beef")
    make_product("Royco Chicken")
    response = cashier_client.post("/sell/cart/scan/", {"code": "royco"})
    assert b"2 products match" in response.content


@pytest.mark.django_db
def test_quick_add_by_preset(cashier_client, cashier, rice, oil):
    cashier_client.post("/sell/cart/add/", {"product": rice.pk, "kind": "qty", "value": "0.25"})
    cashier_client.post("/sell/cart/add/", {"product": oil.pk, "kind": "amount", "value": "50"})
    cart = services.current_cart(cashier)
    assert cart.total == Decimal("100.00")


@pytest.mark.django_db
def test_cashier_needs_pin_to_remove_line(cashier_client, cashier, soap):
    cashier_client.post("/sell/cart/scan/", {"code": "6161100110016"})
    line = services.current_cart(cashier).lines.get()
    response = cashier_client.post(f"/sell/cart/line/{line.pk}/", {"quantity": "0"})
    assert b"owner PIN" in response.content
    response = cashier_client.post(f"/sell/cart/line/{line.pk}/", {"quantity": "0", "pin": "0000"})
    assert services.current_cart(cashier).lines.count() == 1


@pytest.mark.django_db
def test_owner_pin_allows_removal(cashier_client, cashier, owner, soap):
    cashier_client.post("/sell/cart/scan/", {"code": "6161100110016"})
    line = services.current_cart(cashier).lines.get()
    cashier_client.post(f"/sell/cart/line/{line.pk}/", {"quantity": "0"}, HTTP_HX_PROMPT="1234")
    assert services.current_cart(cashier).lines.count() == 0


@pytest.mark.django_db
def test_pay_with_split_redirects_to_receipt(cashier_client, cashier, soap):
    cashier_client.post("/sell/cart/scan/", {"code": "2*6161100110016"})
    response = cashier_client.post("/sell/cart/pay/", {"mpesa": "220", "cash": "500"}, HTTP_HX_REQUEST="true")
    sale = Sale.objects.get(status="completed")
    assert response["HX-Redirect"] == f"/sell/receipt/{sale.pk}/?done=1"
    assert sale.change_given == Decimal("300.00")
    page = cashier_client.get(response["HX-Redirect"])
    assert b"R000001" in page.content and b"Change" in page.content


@pytest.mark.django_db
def test_pay_error_is_shown_in_dialog(cashier_client, soap):
    cashier_client.post("/sell/cart/scan/", {"code": "6161100110016"})
    response = cashier_client.post("/sell/cart/pay/", {"cash": "100"}, HTTP_HX_REQUEST="true")
    assert response["HX-Retarget"] == "#pay-error"
    assert b"less than the cash due" in response.content


@pytest.mark.django_db
def test_pay_on_deni_with_new_customer(cashier_client, soap):
    cashier_client.post("/sell/cart/scan/", {"code": "6161100110016"})
    cashier_client.post("/sell/cart/pay/", {"credit": "210", "new_customer_name": "Baba Otieno", "new_customer_phone": "0700"},
                        HTTP_HX_REQUEST="true")
    assert Customer.objects.get(name="Baba Otieno").balance == Decimal("210.00")


@pytest.mark.django_db
def test_hold_resume_views(cashier_client, cashier, soap):
    cashier_client.post("/sell/cart/scan/", {"code": "6161100110016"})
    cashier_client.post("/sell/cart/hold/", {"label": "Mama Wanjiku"})
    held = Sale.objects.get(status="held")
    assert b"Mama Wanjiku" in cashier_client.get("/sell/held/").content
    cashier_client.post(f"/sell/held/{held.pk}/resume/")
    held.refresh_from_db()
    assert held.status == "open"


@pytest.mark.django_db
def test_refund_view_needs_correct_pin(cashier_client, cashier, owner, soap):
    cart = services.current_cart(cashier)
    services.add_to_cart(cart, soap, quantity=Decimal(2))
    sale = services.complete_sale(cart, user=cashier)
    line = sale.lines.get()
    data = {"action": "refund", f"qty_{line.pk}": "1", "reason": "Damaged", "method": "cash"}
    cashier_client.post(f"/sell/sale/{sale.pk}/", {**data, "pin": "9999"})
    assert not sale.refunds.exists()
    cashier_client.post(f"/sell/sale/{sale.pk}/", {**data, "pin": "1234"})
    assert sale.refunds.get().authorised_by == owner


@pytest.mark.django_db
def test_void_view_with_owner_pin(cashier_client, cashier, owner, soap):
    cart = services.current_cart(cashier)
    services.add_to_cart(cart, soap)
    sale = services.complete_sale(cart, user=cashier)
    cashier_client.post(f"/sell/sale/{sale.pk}/", {"action": "void", "reason": "Wrong item", "pin": "1234"})
    sale.refresh_from_db()
    assert sale.status == "voided"


@pytest.mark.django_db
def test_cashup_view(cashier_client, cashier, soap):
    cart = services.current_cart(cashier)
    services.add_to_cart(cart, soap)
    services.complete_sale(cart, user=cashier)
    assert b"210.00" in cashier_client.get("/sell/cash-up/").content
    response = cashier_client.post("/sell/cash-up/", {"counted_cash": "210", "counted_mpesa": "0", "opening_float": "0"})
    assert response.status_code == 302
    assert b"0.00" in cashier_client.get(response["Location"]).content


@pytest.mark.django_db
def test_history_and_pages(owner_client, owner, soap):
    cart = services.current_cart(owner)
    services.add_to_cart(cart, soap)
    sale = services.complete_sale(cart, user=owner)
    for url in ["/sell/history/", "/sell/history/?q=R000001", "/sell/cash-ups/", f"/sell/receipt/{sale.pk}/",
                "/people/customers/", "/people/suppliers/"]:
        assert owner_client.get(url).status_code == 200, url


@pytest.mark.django_db
def test_receipt_layout_fits_paper(cashier, rice, soap, oil):
    shop = ShopSettings.load()
    cart = services.current_cart(cashier)
    services.add_to_cart(cart, rice, quantity=Decimal("0.25"))
    services.add_to_cart(cart, oil, amount=Decimal("50"))
    services.add_to_cart(cart, soap)
    sale = services.complete_sale(cart, user=cashier, cash_tendered="1000")
    for width_mm, chars in ((58, 32), (80, 48)):
        shop.paper_width_mm = width_mm
        lines = receipt.receipt_lines(sale, shop)
        assert all(len(line) <= chars for line in lines), [l for l in lines if len(l) > chars]
    text = "\n".join(lines)
    assert "0.250 kg x 200.00" in text and "1 x 210.00" in text and "Change" in text and "R000001" in text


@pytest.mark.django_db
def test_print_receipt_sends_escpos(monkeypatch, cashier, soap):
    device = Dummy()
    device.close = lambda: None
    monkeypatch.setattr(receipt, "open_printer", lambda shop: device)
    cart = services.current_cart(cashier)
    services.add_to_cart(cart, soap)
    sale = services.complete_sale(cart, user=cashier)
    assert receipt.print_receipt(sale) is None
    assert b"Bar soap" in device.output


@pytest.mark.django_db
def test_print_failure_keeps_sale(cashier_client, cashier, soap):
    shop = ShopSettings.load()
    shop.printer_connection = "network"
    shop.printer_address = ""
    shop.save()
    cashier_client.post("/sell/cart/scan/", {"code": "6161100110016"})
    response = cashier_client.post("/sell/cart/pay/", {}, HTTP_HX_REQUEST="true")
    assert Sale.objects.filter(status="completed").count() == 1
    page = cashier_client.get(response["HX-Redirect"])
    assert b"did not print" in page.content
