from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image

from apps.core.models import ShopSettings, StoredFile
from apps.core.storage import DatabaseStorage

DB_STORAGE = {
    "default": {"BACKEND": "apps.core.storage.DatabaseStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}


def _png():
    buffer = BytesIO()
    Image.new("RGB", (40, 20), "green").save(buffer, "PNG")
    return buffer.getvalue()


@pytest.mark.django_db
def test_database_storage_round_trip():
    storage = DatabaseStorage()
    name = storage.save("logo/shop.png", SimpleUploadedFile("shop.png", _png()))
    assert storage.exists(name) and storage.size(name) == len(_png())
    assert storage.open(name).read() == _png()
    assert storage.url(name) == "/media/logo/shop.png"
    storage.delete(name)
    assert not StoredFile.objects.exists()


@pytest.mark.django_db
@override_settings(STORAGES=DB_STORAGE)
def test_logo_kept_in_database_is_served_and_used_in_pdfs():
    shop = ShopSettings.load()
    shop.logo.save("shop.png", SimpleUploadedFile("shop.png", _png()))
    stored = StoredFile.objects.get()
    assert stored.name.startswith("logo/")
    from apps.core.storage import serve_stored_file

    response = serve_stored_file(None, stored.name)
    assert response["Content-Type"] == "image/png" and response.content == _png()
    # The document PDF reads the logo through storage, not from a disk path
    from reportlab.platypus import Image as PdfImage

    from apps.documents.pdf import _header, _register_fonts, _styles

    _register_fonts()

    class Doc:
        code = "INV-0001"

        def get_kind_display(self):
            return "Invoice"

    identity = _header(ShopSettings.load(), Doc(), _styles())._cellvalues[0][0]
    assert any(isinstance(f, PdfImage) for f in identity)


@pytest.mark.django_db
@override_settings(ONLINE=True)
def test_online_never_touches_a_printer(cashier_client, soap):
    shop = ShopSettings.load()
    shop.printer_connection = "network"
    shop.printer_address = "192.168.1.50"
    shop.save()
    cashier_client.post("/sell/cart/scan/", {"code": "6161100110016"})
    response = cashier_client.post("/sell/cart/pay/", {"cash": "300"}, HTTP_HX_REQUEST="true")
    assert response.status_code == 200 and "HX-Redirect" in response
    from apps.sales import receipt
    from apps.sales.models import Sale

    assert "online" in receipt.print_receipt(Sale.objects.get(status="completed"))


@pytest.mark.django_db
@override_settings(ONLINE=True)
def test_online_backup_page_explains(owner_client):
    response = owner_client.get("/money/backup/")
    assert response.status_code == 200 and b"runs online" in response.content
