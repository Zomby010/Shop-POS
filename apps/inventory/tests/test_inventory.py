from decimal import Decimal

import pytest

from apps.catalog.models import Product, StockMovement
from apps.inventory import services
from apps.inventory.models import StockTake
from apps.inventory.services import PurchaseItem, StockError
from apps.partners.models import Supplier
from apps.sales import services as sales


@pytest.mark.django_db
def test_purchase_converts_packs(clerk, rice, soap):
    supplier = Supplier.objects.create(name="Mwea Rice")
    purchase = services.create_purchase(
        [PurchaseItem(rice, Decimal(2), Decimal(50), Decimal(9000)), PurchaseItem(soap, Decimal(1), Decimal(12), Decimal(2160))],
        user=clerk, supplier=supplier,
    )
    assert purchase.total == Decimal("20160.00")
    line = purchase.lines.get(product=rice)
    assert line.quantity == Decimal("100.000") and line.unit_cost == Decimal("180.00")
    rice.refresh_from_db()
    assert rice.stock_qty == Decimal("150.000")
    # 50 kg at 170 + 100 kg at 180 -> 176.67
    assert rice.cost_price == Decimal("176.67")
    soap.refresh_from_db()
    assert soap.stock_qty == Decimal("36.000")


@pytest.mark.django_db
def test_purchase_rejects_fractional_pieces(clerk, soap):
    with pytest.raises(StockError):
        services.create_purchase([PurchaseItem(soap, Decimal("1.5"), Decimal(1), Decimal(100))], user=clerk)


@pytest.mark.django_db
def test_recount_and_loss(clerk, rice, soap):
    moved = services.recount({rice: "48.5", soap: "24"}, user=clerk)
    assert len(moved) == 1 and moved[0].quantity == Decimal("-1.500")
    services.record_loss(rice, "0.5", user=clerk, reason="Spillage")
    rice.refresh_from_db()
    assert rice.stock_qty == Decimal("48.000")
    with pytest.raises(StockError):
        services.record_loss(soap, "0.5", user=clerk, reason="Damaged")


@pytest.mark.django_db
def test_stocktake_posts_variance_and_keeps_sales_during_count(owner, cashier, rice, soap):
    take = services.start_stocktake(user=owner)
    assert take.lines.count() == 2
    with pytest.raises(StockError):
        services.start_stocktake(user=owner)
    # A sale happens while counting
    cart = sales.current_cart(cashier)
    sales.add_to_cart(cart, rice, quantity=Decimal("1"))
    sales.complete_sale(cart, user=cashier)
    lines = {l.product_id: l for l in take.lines.all()}
    errors = services.save_counts(take, {lines[rice.pk].pk: "47.25", lines[soap.pk].pk: ""})
    assert errors == []
    services.approve_stocktake(take, user=owner)
    rice.refresh_from_db()
    soap.refresh_from_db()
    # expected 50, counted 47.25 -> -2.75, and the 1 kg sold during the count stays sold
    assert rice.stock_qty == Decimal("46.250")
    assert soap.stock_qty == Decimal("24.000")  # uncounted, untouched
    take.refresh_from_db()
    assert take.status == StockTake.Status.APPROVED
    with pytest.raises(StockError):
        services.approve_stocktake(take, user=owner)


@pytest.mark.django_db
def test_save_counts_validates(owner, soap):
    take = services.start_stocktake(user=owner)
    line = take.lines.get()
    assert services.save_counts(take, {line.pk: "abc"})
    assert services.save_counts(take, {line.pk: "2.5"})


@pytest.mark.django_db
def test_loose_loss_report(owner, cashier, rice, soap):
    cart = sales.current_cart(cashier)
    sales.add_to_cart(cart, rice, quantity=Decimal("10"))
    sales.complete_sale(cart, user=cashier)
    services.record_loss(rice, "0.5", user=owner, reason="Spillage")
    take = services.start_stocktake(user=owner)
    line = take.lines.get(product=rice)
    services.save_counts(take, {line.pk: "38.5"})  # expected 39.5
    services.approve_stocktake(take, user=owner)
    rows = services.loose_loss_report()
    assert [r.product for r in rows] == [rice]  # soap is sold by the piece
    row = rows[0]
    assert row.variance == Decimal("-1.000")
    assert row.recorded_losses == Decimal("0.500")
    assert row.sold == Decimal("10.000")
    assert row.total_loss == Decimal("1.500")
    assert row.variance_value == Decimal("-170.00")


@pytest.mark.django_db
def test_inventory_pages(owner_client, owner, rice, soap):
    take = services.start_stocktake(user=owner)
    for url in ["/stock/", "/stock/purchases/", "/stock/purchases/new/", "/stock/recount/?q=pish", "/stock/loss/",
                "/stock/stock-takes/", f"/stock/stock-takes/{take.pk}/", "/stock/loss-report/", "/stock/movements/"]:
        assert owner_client.get(url).status_code == 200, url


@pytest.mark.django_db
def test_purchase_view(owner_client, rice):
    data = {"date": "2026-10-22", "supplier": "", "lines-TOTAL_FORMS": "2", "lines-INITIAL_FORMS": "0",
            "lines-MIN_NUM_FORMS": "1", "lines-MAX_NUM_FORMS": "1000",
            "lines-0-product": rice.pk, "lines-0-packs": "1", "lines-0-pack_size": "50", "lines-0-pack_cost": "9000"}
    response = owner_client.post("/stock/purchases/new/", data)
    assert response.status_code == 302
    rice.refresh_from_db()
    assert rice.stock_qty == Decimal("100.000")


@pytest.mark.django_db
def test_stocktake_views(owner_client, rice):
    owner_client.post("/stock/stock-takes/", {"note": "Month end"})
    take = StockTake.objects.get()
    line = take.lines.get()
    owner_client.post(f"/stock/stock-takes/{take.pk}/", {f"count_{line.pk}": "49"})
    owner_client.post(f"/stock/stock-takes/{take.pk}/approve/")
    rice.refresh_from_db()
    assert rice.stock_qty == Decimal("49.000")


@pytest.mark.django_db
def test_cashier_cannot_use_stock_pages(cashier_client):
    assert cashier_client.get("/stock/").status_code == 403


@pytest.mark.django_db
def test_clerk_cannot_approve_stocktake(client, clerk, rice):
    client.force_login(clerk)
    take = services.start_stocktake(user=clerk)
    assert client.post(f"/stock/stock-takes/{take.pk}/approve/").status_code == 403


@pytest.mark.django_db
def test_loss_with_own_reason(owner_client, rice):
    owner_client.post("/stock/loss/", {"product": rice.pk, "quantity": "0.25", "reason": "Rats in the store", "note": ""})
    movement = StockMovement.objects.filter(kind=StockMovement.Kind.LOSS).get()
    assert movement.reason == "Rats in the store"
