from decimal import Decimal

import pytest

from apps.catalog.models import PriceTier, Product
from apps.catalog.presets import PresetError, format_preset, parse_preset, parse_preset_list
from apps.catalog.pricing import PricingError, price_by_amount, price_by_quantity


@pytest.mark.parametrize("text,unit,expected", [
    ("1/4 kg", "kg", ("qty", Decimal("0.250"))),
    ("1/2", "kg", ("qty", Decimal("0.500"))),
    ("1 1/2 kg", "kg", ("qty", Decimal("1.500"))),
    ("500 g", "kg", ("qty", Decimal("0.500"))),
    ("2kg", "kg", ("qty", Decimal("2.000"))),
    ("1/2 L", "L", ("qty", Decimal("0.500"))),
    ("250 ml", "L", ("qty", Decimal("0.250"))),
    ("KSh 50", "L", ("amount", Decimal("50"))),
    ("ksh50", "kg", ("amount", Decimal("50"))),
    ("100/=", "kg", ("amount", Decimal("100"))),
    ("3 pcs", "pcs", ("qty", Decimal("3.000"))),
])
def test_parse_preset(text, unit, expected):
    assert parse_preset(text, unit) == expected


@pytest.mark.parametrize("text,unit", [("1 L", "kg"), ("1/2 pcs", "pcs"), ("abc", "kg"), ("0 kg", "kg"), ("2 tins", "kg")])
def test_parse_preset_rejects(text, unit):
    with pytest.raises(PresetError):
        parse_preset(text, unit)


def test_parse_preset_list_and_format():
    items = parse_preset_list("1/4 kg; 1/2 kg; KSh 50", "kg")
    assert [format_preset(k, v, "kg") for k, v in items] == ["1/4 kg", "1/2 kg", "KSh 50"]
    assert format_preset("qty", Decimal("2.000"), "kg") == "2 kg"


@pytest.mark.django_db
def test_price_by_quantity_loose_rounds_to_shilling(rice):
    rice.selling_price = Decimal("215")
    line = price_by_quantity(rice, Decimal("0.25"))
    assert line.quantity == Decimal("0.250")
    assert line.total == Decimal("54.00")  # 53.75 rounds to 54


@pytest.mark.django_db
def test_price_by_quantity_piece_must_be_whole(soap):
    assert price_by_quantity(soap, Decimal("3")).total == Decimal("630.00")
    with pytest.raises(PricingError):
        price_by_quantity(soap, Decimal("1.5"))


@pytest.mark.django_db
def test_price_by_amount(oil):
    line = price_by_amount(oil, Decimal("50"))
    assert line.quantity == Decimal("0.167")
    assert line.total == Decimal("50.00")
    assert line.unit_price == Decimal("300")


@pytest.mark.django_db
def test_price_by_amount_not_for_pieces(soap):
    with pytest.raises(PricingError):
        price_by_amount(soap, Decimal("50"))


@pytest.mark.django_db
def test_bulk_tier_applies_from_threshold(make_product):
    sugar = make_product("Sugar", Product.SoldBy.WEIGHT, price="180", cost="160")
    PriceTier.objects.create(product=sugar, min_qty=10, unit_price=170)
    PriceTier.objects.create(product=sugar, min_qty=50, unit_price=165)
    assert price_by_quantity(sugar, Decimal("9.999")).unit_price == Decimal("180")
    ten = price_by_quantity(sugar, Decimal("10"))
    assert ten.unit_price == Decimal("170") and ten.tier_applied and ten.total == Decimal("1700.00")
    assert price_by_quantity(sugar, Decimal("60")).unit_price == Decimal("165")


@pytest.mark.django_db
def test_bulk_tier_by_amount(make_product):
    sugar = make_product("Sugar", Product.SoldBy.WEIGHT, price="180", cost="160")
    PriceTier.objects.create(product=sugar, min_qty=10, unit_price=170)
    line = price_by_amount(sugar, Decimal("1800"))  # 10 kg at 180 -> qualifies for 170
    assert line.unit_price == Decimal("170")
    assert line.quantity == Decimal("10.588")
