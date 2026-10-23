import pytest

OWNER_PAGES = [
    "/", "/settings/", "/settings/users/", "/settings/users/new/", "/settings/audit-log/",
    "/products/", "/products/?low=1", "/products/new/", "/products/categories/",
    "/products/quick-sale-categories/", "/products/import/", "/products/import/template.xlsx",
]


@pytest.mark.django_db
@pytest.mark.parametrize("url", OWNER_PAGES)
def test_owner_pages_render(owner_client, rice, oil, soap, url):
    assert owner_client.get(url).status_code == 200


@pytest.mark.django_db
def test_product_edit_page_renders(owner_client, rice):
    response = owner_client.get(f"/products/{rice.pk}/")
    assert response.status_code == 200
    assert b"1/4 kg" in response.content
