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


@pytest.mark.django_db
def test_opening_balance_starts_the_deni_statement(cashier_client):
    response = cashier_client.post("/people/customers/new/", {
        "name": "Wanjiku", "phone": "0722", "kra_pin": "A123", "opening_balance": "1500", "active": "on",
    })
    customer = Customer.objects.get()
    assert response.status_code == 302 and customer.balance == 1500 and customer.kra_pin == "A123"
    entry = customer.credit_entries.get()
    assert entry.note == "Opening balance" and entry.kind == "charge"
    # Editing never asks for (or adds) an opening balance again
    page = cashier_client.get(f"/people/customers/{customer.pk}/edit/").content.decode()
    assert "opening_balance" not in page


@pytest.mark.django_db
def test_customer_list_balances_total_spent_and_excel(owner_client, owner, rice):
    from apps.partners.models import CreditEntry
    from apps.sales import services

    owing = Customer.objects.create(name="Owing")
    CreditEntry.objects.create(customer=owing, kind="charge", amount=765)
    overpaid = Customer.objects.create(name="Overpaid")
    CreditEntry.objects.create(customer=overpaid, kind="repayment", amount=100)
    clear = Customer.objects.create(name="Clear")
    for c in (owing, overpaid, clear):
        from apps.partners.models import recalculate_balance
        recalculate_balance(c)
    # A deni sale counts towards total spent (the Bizkit report showed 0 here)
    cart = services.current_cart(owner)
    services.add_to_cart(cart, rice, quantity=2)
    buyer = Customer.objects.create(name="Buyer")
    services.complete_sale(cart, user=owner, credit="400", customer=buyer)

    page = owner_client.get("/people/customers/").content.decode()
    assert "765.00" in page and "overpaid" in page and "400.00" in page
    assert "Clear" not in owner_client.get("/people/customers/?balance=owing").content.decode()
    assert "Overpaid" in owner_client.get("/people/customers/?balance=overpaid").content.decode()
    assert "Owing" not in owner_client.get("/people/customers/?balance=clear").content.decode()
    response = owner_client.get("/people/customers/?format=xlsx")
    assert response["Content-Type"].startswith("application/vnd.openxmlformats")
    assert "400.00" in owner_client.get(f"/people/customers/{buyer.pk}/").content.decode()


@pytest.mark.django_db
def test_supplier_list_filters_and_excel(client, clerk, rice):
    from apps.inventory import services
    from apps.inventory.services import PurchaseItem

    owed = Supplier.objects.create(name="Mwea Rice")
    Supplier.objects.create(name="Paid Up")
    services.create_purchase([PurchaseItem(rice, 1, 10, 1800)], user=clerk, supplier=owed, amount_paid="800")
    client.force_login(clerk)
    page = client.get("/people/suppliers/").content.decode()
    assert "1,000.00" in page and "New purchase" in page
    assert "Paid Up" not in client.get("/people/suppliers/?balance=owing").content.decode()
    assert "Mwea Rice" not in client.get("/people/suppliers/?balance=clear").content.decode()
    assert client.get("/people/suppliers/?format=xlsx")["Content-Type"].startswith("application/vnd.openxmlformats")
    # Stock clerks reach People (suppliers) from the top menu, but not users or roles
    assert 'href="/people/suppliers/"' in client.get("/").content.decode()
    assert client.get("/people/users/").status_code == 403
    assert client.get("/people/roles/").status_code == 403


@pytest.mark.django_db
def test_users_and_roles_pages(owner_client, owner, cashier, rice):
    from apps.sales import services

    cart = services.current_cart(cashier)
    services.add_to_cart(cart, rice, quantity=1)
    services.complete_sale(cart, user=cashier, cash_tendered="200")
    page = owner_client.get("/people/users/").content.decode()
    assert "1 · KSh 200.00" in page and "Roles and privileges" in page
    assert owner_client.get("/settings/users/")["Location"] == "/people/users/"
    roles = owner_client.get("/people/roles/").content.decode()
    assert "With owner PIN" in roles and "Approve a stock take" in roles


@pytest.mark.django_db
def test_customer_kra_pin_is_on_invoices(owner_client):
    from apps.documents.models import Document

    customer = Customer.objects.create(name="Hotel Amani", kra_pin="P051234567X")
    doc = Document.objects.create(kind="invoice", number=1, customer=customer)
    assert "KRA PIN P051234567X" in owner_client.get(f"/documents/{doc.pk}/").content.decode()
