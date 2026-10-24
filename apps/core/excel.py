from django.http import HttpResponse
from django.utils import timezone
from django.utils.text import slugify

from apps.finance.excel import workbook_response_bytes

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def xlsx_response(name, title, header, rows, totals=None):
    """A one-sheet Excel download named after the page and today's date."""
    today = timezone.localdate()
    data = workbook_response_bytes(title, header, rows, totals, subtitle=f"Printed {today:%d %b %Y}")
    response = HttpResponse(data, content_type=XLSX)
    response["Content-Disposition"] = f'attachment; filename="{slugify(name) or "export"}-{today}.xlsx"'
    return response
