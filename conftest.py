from decimal import Decimal

import pytest
from django.contrib.auth.models import Group

from apps.catalog.models import Product, QuickPreset, QuickSaleCategory, StockMovement
from apps.catalog.stock import record_movement
from apps.core.roles import CASHIER, OWNER, STOCK_CLERK, ensure_groups


@pytest.fixture(autouse=True)
def _media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.DATA_DIR = tmp_path / "data"
    settings.AUTO_BACKUP = False


def _make_user(django_user_model, username, role, pin=None):
    ensure_groups()
    user = django_user_model.objects.create_user(username=username, password="pass12345")
    user.groups.add(Group.objects.get(name=role))
    if pin:
        user.profile.set_pin(pin)
        user.profile.save()
    return user


@pytest.fixture
def owner(django_user_model):
    return _make_user(django_user_model, "owner", OWNER, pin="1234")


@pytest.fixture
def cashier(django_user_model):
    return _make_user(django_user_model, "cashier", CASHIER)


@pytest.fixture
def clerk(django_user_model):
    return _make_user(django_user_model, "clerk", STOCK_CLERK)


@pytest.fixture
def owner_client(client, owner):
    client.force_login(owner)
    return client


@pytest.fixture
def cashier_client(client, cashier):
    client.force_login(cashier)
    return client


@pytest.fixture
def make_product(db):
    def make(name="Soap", sold_by=Product.SoldBy.PIECE, price="100", cost="80", stock="0", barcode=None, **kw):
        product = Product.objects.create(
            name=name, sold_by=sold_by, selling_price=Decimal(price), cost_price=Decimal(cost), barcode=barcode, **kw
        )
        if Decimal(stock):
            record_movement(product, StockMovement.Kind.OPENING, Decimal(stock), unit_cost=Decimal(cost))
            product.refresh_from_db()
        return product

    return make


@pytest.fixture
def rice(make_product):
    qc = QuickSaleCategory.objects.create(name="Rice")
    product = make_product("Pishori", Product.SoldBy.WEIGHT, price="200", cost="170", stock="50", quick_category=qc)
    QuickPreset.objects.create(product=product, kind="qty", value=Decimal("0.25"), order=0)
    QuickPreset.objects.create(product=product, kind="qty", value=Decimal("0.5"), order=1)
    return product


@pytest.fixture
def oil(make_product):
    qc = QuickSaleCategory.objects.create(name="Cooking oil")
    product = make_product("Loose oil", Product.SoldBy.VOLUME, price="300", cost="260", stock="20", quick_category=qc)
    QuickPreset.objects.create(product=product, kind="amount", value=Decimal("50"), order=0)
    return product


@pytest.fixture
def soap(make_product):
    return make_product("Bar soap", price="210", cost="185", stock="24", barcode="6161100110016")
