from decimal import Decimal

import pytest

from apps.core.audit import verify_owner_pin
from apps.core.money import q3, round_shilling, to_decimal
from apps.core.models import Sequence, ShopSettings
from apps.core.roles import has_role, is_owner, STOCK_CLERK


def test_round_shilling_rounds_half_up():
    assert round_shilling(Decimal("49.5")) == Decimal("50.00")
    assert round_shilling(Decimal("49.49")) == Decimal("49.00")


def test_q3_and_to_decimal():
    assert q3(Decimal("0.16666")) == Decimal("0.167")
    assert to_decimal("1,250.50") == Decimal("1250.50")
    assert to_decimal("abc") is None
    assert to_decimal("") is None


@pytest.mark.django_db
def test_settings_is_singleton():
    a = ShopSettings.load()
    a.business_name = "Kayliz"
    a.save()
    ShopSettings(business_name="Other").save()
    assert ShopSettings.objects.count() == 1
    assert ShopSettings.load().business_name == "Other"


@pytest.mark.django_db
def test_sequence_counts_up():
    assert Sequence.next("receipt") == 1
    assert Sequence.next("receipt") == 2
    assert Sequence.next("invoice") == 1


@pytest.mark.django_db
def test_roles(owner, cashier, clerk):
    assert is_owner(owner) and not is_owner(cashier)
    assert has_role(owner, STOCK_CLERK)
    assert has_role(clerk, STOCK_CLERK) and not has_role(cashier, STOCK_CLERK)


@pytest.mark.django_db
def test_owner_pin(owner, cashier):
    cashier.profile.set_pin("9999")
    cashier.profile.save()
    assert verify_owner_pin("1234") == owner
    assert verify_owner_pin("9999") is None  # cashiers can't approve
    assert verify_owner_pin("0000") is None


@pytest.mark.django_db
def test_login_required(client):
    response = client.get("/")
    assert response.status_code == 302 and response["Location"].startswith("/login/")


@pytest.mark.django_db
def test_settings_page_owner_only(owner_client, client, cashier):
    assert owner_client.get("/settings/").status_code == 200
    response = owner_client.post("/settings/", {
        "business_name": "Kayliz Minimart", "receipt_footer": "Asante", "printer_connection": "none",
        "paper_width_mm": "58", "low_stock_default": "3", "backups_to_keep": "30",
    })
    assert response.status_code == 302
    assert ShopSettings.load().paper_width_mm == 58
    client.force_login(cashier)
    assert client.get("/settings/").status_code == 403


@pytest.mark.django_db
def test_owner_creates_cashier_with_role(owner_client, django_user_model):
    response = owner_client.post("/people/users/new/", {
        "username": "jane", "first_name": "Jane", "role": "Cashier", "password": "secret12", "is_active": "on",
    })
    assert response.status_code == 302
    jane = django_user_model.objects.get(username="jane")
    assert list(jane.groups.values_list("name", flat=True)) == ["Cashier"]
    assert jane.check_password("secret12")


@pytest.mark.django_db
def test_dashboard_renders(owner_client, rice):
    response = owner_client.get("/")
    assert response.status_code == 200
    assert b"Low stock" in response.content
