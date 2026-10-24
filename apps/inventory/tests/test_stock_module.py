from decimal import Decimal

import pytest

from apps.catalog.models import Category, PriceChange, Product, StockMovement
from apps.inventory import services
from apps.inventory.models import Conversion, Purchase, Recount
from apps.inventory.services import PurchaseItem, StockError
from apps.partners.models import Supplier
from apps.sales import services as sales


@pytest.mark.django_db
def test_conversion_moves_stock_and_cost_without_a_purchase(clerk, rice, make_product):
    packets = make_product("Pishori 1kg packet", price="230", cost="0")
    done = services.convert(rice, "10", packets, "10", user=clerk, note="Packed")
    rice.refresh_from_db()
    packets.refresh_from_db()
    assert rice.stock_qty == Decimal("40.000") and rice.cost_price == Decimal("170.00")
    assert packets.stock_qty == Decimal("10.000") and packets.cost_price == Decimal("170.00")
    assert done.value == Decimal("1700.00") and done.yield_pct == 100
    assert not Purchase.objects.exists()
    kinds = set(StockMovement.objects.filter(reference=str(done)).values_list("kind", flat=True))
    assert kinds == {StockMovement.Kind.CONVERSION_OUT, StockMovement.Kind.CONVERSION_IN}


@pytest.mark.django_db
def test_conversion_spreads_cost_over_what_was_made(clerk, soap, make_product):
    single = make_product("Bar soap single", price="20", cost="0")
    # 1 bar at 185 cut into 10 small pieces -> 18.50 each
    services.convert(soap, "1", single, "10", user=clerk)
    single.refresh_from_db()
    assert single.cost_price == Decimal("18.50")


@pytest.mark.django_db
def test_conversion_checks_stock_and_whole_pieces(clerk, rice, soap):
    with pytest.raises(StockError):
        services.convert(rice, "60", soap, "1", user=clerk)
    with pytest.raises(StockError):
        services.convert(rice, "1", soap, "1.5", user=clerk)
    with pytest.raises(StockError):
        services.convert(rice, "1", rice, "1", user=clerk)
    assert not Conversion.objects.exists()


@pytest.mark.django_db
def test_recount_needs_a_reason_that_matches_the_difference(clerk, rice, soap):
    with pytest.raises(StockError, match="short"):
        services.recount({rice: ("48", "")}, user=clerk)
    # A gain can't be filed under a loss reason
    with pytest.raises(StockError, match="extra"):
        services.recount({soap: ("26", "Damaged")}, user=clerk)
    session, moved = services.recount({soap: ("26", "Delivery not recorded"), rice: ("50", "")}, user=clerk,
                                      kind=Recount.Kind.CLOSING, note="Evening")
    assert session.get_kind_display() == "Closing count"
    assert [(m.product, m.quantity, m.reason) for m in moved] == [(soap, Decimal("2.000"), "Delivery not recorded")]


@pytest.mark.django_db
def test_recount_view_previews_then_confirms(owner_client, rice):
    data = {"kind": "spot", "note": "", f"count_{rice.pk}": "49", f"reason_{rice.pk}": "Normal loss"}
    response = owner_client.post("/stock/recount/", data)
    assert response.status_code == 200 and b"Confirm and save" in response.content
    rice.refresh_from_db()
    assert rice.stock_qty == Decimal("50.000")  # nothing saved yet
    owner_client.post("/stock/recount/", {**data, "confirm": "1"})
    rice.refresh_from_db()
    assert rice.stock_qty == Decimal("49.000")
    assert Recount.objects.count() == 1


@pytest.mark.django_db
def test_part_paid_purchase_and_paying_later(clerk, rice):
    supplier = Supplier.objects.create(name="Mwea Rice")
    purchase = services.create_purchase([PurchaseItem(rice, 1, 50, 9000)], user=clerk, supplier=supplier,
                                        amount_paid="4000")
    assert purchase.amount_paid == Decimal("4000.00") and purchase.balance == Decimal("5000.00")
    assert purchase.payment_status == "Partly paid"
    assert services.supplier_balance(supplier) == Decimal("5000.00")
    with pytest.raises(StockError):
        services.pay_supplier(purchase, "6000", user=clerk)
    services.pay_supplier(purchase, "5000", user=clerk, method="mpesa")
    purchase.refresh_from_db()
    assert purchase.payment_status == "Paid" and services.supplier_balance(supplier) == 0
    # Blank means paid in full
    full = services.create_purchase([PurchaseItem(rice, 1, 1, 180)], user=clerk, supplier=supplier)
    assert full.balance == 0 and full.payments.count() == 1


@pytest.mark.django_db
def test_cancel_purchase_takes_stock_off_again(owner, cashier, rice):
    purchase = services.create_purchase([PurchaseItem(rice, 1, 50, 9000)], user=owner, amount_paid="0")
    rice.refresh_from_db()
    assert rice.stock_qty == Decimal("100.000")
    with pytest.raises(StockError):
        services.cancel_purchase(purchase, user=owner, reason="")
    services.cancel_purchase(purchase, user=owner, reason="Entered twice")
    rice.refresh_from_db()
    purchase.refresh_from_db()
    assert rice.stock_qty == Decimal("50.000")
    assert purchase.is_cancelled and purchase.balance == 0
    with pytest.raises(StockError):
        services.cancel_purchase(purchase, user=owner, reason="Again")
    with pytest.raises(StockError):
        services.pay_supplier(purchase, "100", user=owner)


@pytest.mark.django_db
def test_cancel_refused_once_the_stock_is_sold(owner, cashier, make_product):
    milk = make_product("Milk 500ml", price="60", cost="50")
    purchase = services.create_purchase([PurchaseItem(milk, 1, 10, 500)], user=owner)
    cart = sales.current_cart(cashier)
    sales.add_to_cart(cart, milk, quantity=Decimal("3"))
    sales.complete_sale(cart, user=cashier)
    with pytest.raises(StockError, match="already been sold"):
        services.cancel_purchase(purchase, user=owner, reason="Mistake")


@pytest.mark.django_db
def test_purchase_detail_pay_and_cancel(client, owner, clerk, rice):
    purchase = services.create_purchase([PurchaseItem(rice, 1, 50, 9000)], user=clerk, amount_paid="0")
    url = f"/stock/purchases/{purchase.pk}/"
    client.force_login(clerk)
    assert b"Unpaid" in client.get(url).content
    client.post(url, {"action": "pay", "amount": "2000", "date": "2026-10-24", "method": "cash", "note": ""})
    purchase.refresh_from_db()
    assert purchase.amount_paid == Decimal("2000.00")
    client.post(url, {"action": "cancel", "reason": "Clerk tries"})
    purchase.refresh_from_db()
    assert not purchase.is_cancelled
    client.force_login(owner)
    client.post(url, {"action": "cancel", "reason": "Wrong supplier"})
    purchase.refresh_from_db()
    assert purchase.is_cancelled and purchase.cancelled_by == owner


@pytest.mark.django_db
def test_new_selling_price_on_receipt_is_logged(clerk, rice):
    services.create_purchase([PurchaseItem(rice, 1, 50, 9500, new_price=Decimal("215"))], user=clerk)
    rice.refresh_from_db()
    assert rice.selling_price == Decimal("215.00")
    change = PriceChange.objects.filter(product=rice, new_price=Decimal("215.00")).get()
    assert change.old_price == Decimal("200.00") and "New selling price" in change.reason
    # The cost went from 170 to (50*170 + 50*190)/100 = 180 and that is logged too
    assert PriceChange.objects.filter(product=rice, old_cost=Decimal("170.00"), new_cost=Decimal("180.00")).exists()


@pytest.mark.django_db
def test_product_edit_logs_price_change(owner_client, rice):
    data = {"name": rice.name, "barcode": "", "category": "", "sold_by": "weight", "selling_price": "210",
            "cost_price": "170", "low_stock_threshold": "", "reorder_qty": "50", "quick_category": "",
            "quick_order": "0", "active": "on",
            "tiers-TOTAL_FORMS": "0", "tiers-INITIAL_FORMS": "0", "presets-TOTAL_FORMS": "0", "presets-INITIAL_FORMS": "0"}
    response = owner_client.post(f"/products/{rice.pk}/", data)
    assert response.status_code == 302, response.content
    rice.refresh_from_db()
    assert rice.reorder_qty == Decimal("50.000")
    assert PriceChange.objects.filter(product=rice, old_price=Decimal("200.00"), new_price=Decimal("210.00")).exists()


@pytest.mark.django_db
def test_movements_record_before_and_after(clerk, rice):
    services.record_loss(rice, "2", user=clerk, reason="Spillage")
    movement = rice.movements.first()
    assert movement.stock_before == Decimal("50.000") and movement.stock_after == Decimal("48.000")


@pytest.mark.django_db
def test_history_and_low_stock_pages_and_excel(owner_client, clerk, rice, soap, make_product):
    services.record_loss(rice, "1", user=clerk, reason="Spillage")
    make_product("Matches", price="5", cost="3", stock="0", reorder_qty=Decimal("100"))
    response = owner_client.get(f"/stock/products/{rice.pk}/history/")
    assert response.status_code == 200 and b"Spillage" in response.content
    response = owner_client.get(f"/stock/products/{rice.pk}/history/?kind=loss&format=xlsx")
    assert response["Content-Type"].startswith("application/vnd.openxmlformats")
    response = owner_client.get("/stock/low-stock/")
    assert response.status_code == 200 and b"Matches" in response.content and b"Out of stock" in response.content
    assert b"300.00" in response.content  # 100 x 3
    response = owner_client.get("/stock/low-stock/?format=xlsx")
    assert response["Content-Type"].startswith("application/vnd.openxmlformats")
    for url in ["/stock/conversion/", "/stock/recount/?q=pish", "/people/suppliers/", "/products/categories/"]:
        assert owner_client.get(url).status_code == 200, url


@pytest.mark.django_db
def test_category_page_shows_description_and_counts(owner_client, rice):
    cat = Category.objects.create(name="Grains", description="Rice, beans and maize")
    rice.category = cat
    rice.save()
    content = owner_client.get("/products/categories/").content.decode()
    assert "Rice, beans and maize" in content and f"?category={cat.pk}\">1<" in content


@pytest.mark.django_db
def test_conversion_view(owner_client, rice, make_product):
    packets = make_product("Pishori 2kg packet", price="450", cost="0")
    owner_client.post("/stock/conversion/", {"from_product": rice.pk, "from_qty": "4", "to_product": packets.pk,
                                             "to_qty": "2", "note": ""})
    packets.refresh_from_db()
    assert packets.stock_qty == Decimal("2.000") and packets.cost_price == Decimal("340.00")
