import pytest

from apps.partners.models import Customer, Supplier


@pytest.mark.django_db
def test_owner_adds_supplier(owner_client):
    response = owner_client.post("/people/suppliers/new/", {"name": "Mwea Rice", "phone": "0711", "active": "on"})
    supplier = Supplier.objects.get()
    assert response["Location"] == f"/people/suppliers/{supplier.pk}/"
    assert owner_client.get(response["Location"]).status_code == 200


@pytest.mark.django_db
def test_cashier_cannot_add_supplier_or_set_credit_limit(cashier_client):
    assert cashier_client.get("/people/suppliers/new/").status_code == 403
    cashier_client.post("/people/customers/new/", {"name": "Akinyi", "credit_limit": "99999", "active": "on"})
    assert Customer.objects.get().credit_limit is None


@pytest.mark.django_db
def test_repayment_view(cashier_client, cashier):
    from apps.partners.models import CreditEntry

    customer = Customer.objects.create(name="Akinyi")
    CreditEntry.objects.create(customer=customer, kind="charge", amount=500)
    cashier_client.post(f"/people/customers/{customer.pk}/", {"amount": "200", "method": "cash"})
    customer.refresh_from_db()
    assert customer.balance == 300
