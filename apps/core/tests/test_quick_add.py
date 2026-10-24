import pytest

from apps.catalog.models import Category, Product, QuickSaleCategory
from apps.finance.models import ExpenseCategory
from apps.partners.models import Customer, Supplier


@pytest.mark.django_db
def test_get_returns_the_popup_fields(owner_client):
    html = owner_client.get("/quick-add/product/").content.decode()
    assert 'name="name"' in html and 'name="sold_by"' in html and 'name="selling_price"' in html


@pytest.mark.django_db
def test_add_category(owner_client):
    data = owner_client.post("/quick-add/category/", {"name": "Snacks"}).json()
    assert Category.objects.get(pk=data["id"]).name == "Snacks"
    assert data["label"] == "Snacks"


@pytest.mark.django_db
def test_duplicate_name_is_refused_with_the_form_again(owner_client):
    Category.objects.create(name="Snacks")
    response = owner_client.post("/quick-add/category/", {"name": "snacks"})
    assert response.status_code == 400
    assert "already exists" in response.content.decode()


@pytest.mark.django_db
def test_new_quick_category_goes_last(owner_client):
    QuickSaleCategory.objects.create(name="Rice", order=4)
    data = owner_client.post("/quick-add/quick_category/", {"name": "Flour"}).json()
    assert QuickSaleCategory.objects.get(pk=data["id"]).order == 5


@pytest.mark.django_db
def test_add_product_returns_unit_and_price(owner_client):
    data = owner_client.post("/quick-add/product/", {
        "name": "Ndengu", "sold_by": "weight", "selling_price": "180", "cost_price": "150", "barcode": "",
    }).json()
    product = Product.objects.get(pk=data["id"])
    assert product.barcode is None
    assert data["label"] == "Ndengu (kg)"
    assert data["data"] == {"name": "Ndengu", "unit": "kg", "price": 180.0, "tiers": []}


@pytest.mark.django_db
def test_product_needs_a_price(owner_client):
    response = owner_client.post("/quick-add/product/", {"name": "X", "sold_by": "piece", "selling_price": "0",
                                                         "cost_price": "0"})
    assert response.status_code == 400
    assert not Product.objects.exists()


@pytest.mark.django_db
def test_supplier_customer_and_expense_category(owner_client):
    owner_client.post("/quick-add/supplier/", {"name": "Kapa Oil", "phone": "0711"})
    owner_client.post("/quick-add/customer/", {"name": "Mama Njeri", "phone": "0722"})
    owner_client.post("/quick-add/expense_category/", {"name": "Security"})
    assert Supplier.objects.get().phone == "0711"
    assert Customer.objects.get().name == "Mama Njeri"
    assert ExpenseCategory.objects.filter(name="Security").exists()


@pytest.mark.django_db
def test_cashier_may_add_customers_only(cashier_client):
    assert cashier_client.post("/quick-add/customer/", {"name": "Baba Otieno"}).status_code == 200
    assert cashier_client.post("/quick-add/category/", {"name": "Snacks"}).status_code == 403
    assert cashier_client.post("/quick-add/product/", {"name": "X"}).status_code == 403
    page = cashier_client.get("/sell/").content.decode()
    assert 'data-quick-add="customer"' in page


@pytest.mark.django_db
def test_unknown_kind(owner_client):
    assert owner_client.post("/quick-add/sale/", {"name": "x"}).status_code == 404


@pytest.mark.django_db
def test_forms_offer_new_options(owner_client):
    assert 'data-quick-add="category"' in owner_client.get("/products/new/").content.decode()
    assert 'data-quick-add="supplier"' in owner_client.get("/stock/purchases/new/").content.decode()
    assert 'data-quick-add="expense_category"' in owner_client.get("/money/expenses/").content.decode()
    page = owner_client.get("/documents/new/?kind=quotation").content.decode()
    assert 'data-quick-add="customer"' in page and 'data-quick-add="product"' in page
