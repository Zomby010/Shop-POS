from django.conf import settings
from django.contrib import messages
from django.db.models import Sum
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core import backup
from apps.core.models import ShopSettings
from apps.core.roles import owner_required

from . import reports
from .excel import workbook_response_bytes
from .forms import ExpenseForm
from .models import Expense

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx(name, start, end, title, header, rows, totals=None):
    data = workbook_response_bytes(title, header, rows, totals, subtitle=f"{start:%d %b %Y} to {end:%d %b %Y}")
    response = HttpResponse(data, content_type=XLSX)
    response["Content-Disposition"] = f'attachment; filename="{name}-{start}-to-{end}.xlsx"'
    return response


def _range_context(start, end):
    return {"start": start.isoformat(), "end": end.isoformat()}


@owner_required
def profit_view(request):
    start, end = reports.parse_range(request)
    report = reports.profit(start, end)
    if request.GET.get("format") == "xlsx":
        header = ["Day", "Sales", "Refunds", "Net sales", "Cost of goods", "Gross profit", "Expenses", "Stock loss", "Net profit"]
        row = lambda d: [d.day, d.sales, d.refunds, d.net_sales, d.cost_of_sales, d.gross_profit, d.expenses,
                         d.stock_loss, d.net_profit]
        t = report.total
        return _xlsx("profit", start, end, "Profit", header, [row(d) for d in report.days],
                     ["Total"] + row(t)[1:])
    return render(request, "finance/profit.html", {"report": report, "total": report.total, "tab": "profit",
                                                   **_range_context(start, end)})


@owner_required
def sales_view(request):
    start, end = reports.parse_range(request, default_days=6)
    rows, total = reports.sales_report(start, end)
    if request.GET.get("format") == "xlsx":
        header = ["Day", "Sales count", "Total", "Cash", "M-Pesa", "Deni", "Refunds", "Net", "Voided"]
        row = lambda d: [d.count, d.total, d.cash, d.mpesa, d.credit, d.refunds, d.net, d.voided]
        return _xlsx("sales", start, end, "Sales by payment method", header, [[d.day] + row(d) for d in rows],
                     ["Total"] + row(total))
    return render(request, "finance/sales.html", {"rows": rows, "total": total, "tab": "sales",
                                                  **_range_context(start, end)})


@owner_required
def products_view(request):
    start, end = reports.parse_range(request, default_days=29)
    best, slow, rows = reports.best_and_slow(start, end)
    if request.GET.get("format") == "xlsx":
        header = ["Product", "Category", "Unit", "Quantity sold", "Revenue", "Gross profit", "In stock"]
        data = [[r.product.name, str(r.product.category or ""), r.product.unit, r.quantity, r.revenue, r.profit,
                 r.product.stock_qty] for r in sorted(rows, key=lambda r: r.revenue, reverse=True)]
        return _xlsx("best-and-slow-sellers", start, end, "Best and slow sellers", header, data)
    return render(request, "finance/products.html", {"best": best, "slow": slow, "tab": "products",
                                                     **_range_context(start, end)})


@owner_required
def stock_value_view(request):
    rows, total = reports.stock_value()
    if request.GET.get("format") == "xlsx":
        from django.utils import timezone

        today = timezone.localdate()
        header = ["Category", "Products", "Value at cost", "Value at selling price", "Potential profit"]
        row = lambda r: [r.category, r.products, r.at_cost, r.at_price, r.potential_profit]
        return _xlsx("stock-value", today, today, "Stock value", header, [row(r) for r in rows], row(total))
    return render(request, "finance/stock_value.html", {"rows": rows, "total": total, "tab": "stock"})


@owner_required
def expenses(request):
    start, end = reports.parse_range(request, default_days=29)
    form = ExpenseForm(request.POST or None, initial={"date": end})
    if request.method == "POST" and form.is_valid():
        expense = form.save(commit=False)
        expense.user = request.user
        expense.save()
        messages.success(request, f"Expense of KSh {expense.amount:,.2f} saved.")
        return redirect(f"{request.path}?start={start}&end={end}")
    items = Expense.objects.filter(date__gte=start, date__lte=end).select_related("user", "category")
    if request.GET.get("format") == "xlsx":
        header = ["Date", "Category", "Amount", "Paid by", "Note"]
        data = [[e.date, e.category.name, e.amount, e.get_method_display(), e.note] for e in items]
        return _xlsx("expenses", start, end, "Expenses", header, data)
    return render(request, "finance/expenses.html", {
        "form": form, "items": items, "total": items.aggregate(t=Sum("amount"))["t"] or 0, "tab": "expenses",
        **_range_context(start, end),
    })


@owner_required
@require_POST
def expense_delete(request, pk):
    expense = get_object_or_404(Expense, pk=pk)
    expense.delete()
    messages.success(request, "Expense deleted.")
    return redirect(request.POST.get("next") or "finance:expenses")


@owner_required
def backup_view(request):
    shop = ShopSettings.load()
    if settings.ONLINE:
        # Folder backups need the laptop; online, the database host keeps the backups.
        return render(request, "finance/backup_online.html", {"tab": "backup"})
    if request.method == "POST":
        try:
            path = backup.create_backup()
        except Exception as exc:
            messages.error(request, f"Backup failed: {exc}")
        else:
            messages.success(request, f"Backup saved: {path.name}")
        return redirect("finance:backup")
    folder = backup.backup_folder(shop)
    return render(request, "finance/backup.html", {
        "folder": folder, "backups": backup.list_backups(folder), "due": backup.backup_due(folder=folder), "tab": "backup",
    })


@owner_required
def backup_download(request, name):
    folder = backup.backup_folder()
    path = folder / name
    if not name.startswith(backup.PREFIX) or path.parent != folder or not path.exists():
        raise Http404
    return FileResponse(path.open("rb"), as_attachment=True, filename=name)
