from decimal import Decimal

import pytest

from apps.catalog.models import Product, StockMovement
from apps.catalog.stock import record_movement, recalculate_stock, set_counted_stock


@pytest.mark.django_db
def test_movements_update_cached_stock(rice):
    record_movement(rice, StockMovement.Kind.SALE, Decimal("-0.25"))
    rice.refresh_from_db()
    assert rice.stock_qty == Decimal("49.750")
    assert recalculate_stock(rice) == Decimal("49.750")


@pytest.mark.django_db
def test_purchase_updates_weighted_average_cost(rice):
    # 50 kg at 170, then 50 kg at 190 -> 180
    record_movement(rice, StockMovement.Kind.PURCHASE, Decimal("50"), unit_cost=Decimal("190"))
    rice.refresh_from_db()
    assert rice.cost_price == Decimal("180.00")
    assert rice.stock_qty == Decimal("100.000")


@pytest.mark.django_db
def test_sale_movement_uses_cost_at_the_time(rice):
    sale = record_movement(rice, StockMovement.Kind.SALE, Decimal("-1"))
    record_movement(rice, StockMovement.Kind.PURCHASE, Decimal("49"), unit_cost=Decimal("230"))
    sale.refresh_from_db()
    assert sale.unit_cost == Decimal("170.00")


@pytest.mark.django_db
def test_set_counted_stock(rice):
    movement = set_counted_stock(rice, Decimal("48.5"), reason="Recount")
    assert movement.quantity == Decimal("-1.500")
    assert set_counted_stock(rice, Decimal("48.5")) is None


@pytest.mark.django_db
def test_low_stock_uses_product_or_default_threshold(make_product):
    from apps.core.models import ShopSettings

    shop = ShopSettings.load()
    shop.low_stock_default = Decimal("5")
    shop.save()
    low = make_product("A", stock="3")
    make_product("B", stock="10")
    custom = make_product("C", stock="10", low_stock_threshold=Decimal("12"))
    assert set(Product.objects.low_stock()) == {low, custom}
    assert low.is_low_stock
