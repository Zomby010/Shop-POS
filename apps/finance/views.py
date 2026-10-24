from django.conf import settings
from django.contrib import messages
from django.db.models import Sum
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.catalog.models import Category
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


def _range_context(start, end, request=None):
    return {"start": start.isoformat(), "end": end.isoformat(), "periods": reports.PERIODS,
            "period": request.GET.get("period", "") if request else ""}


@owner_required
def summary_view(request):
    start, end = reports.parse_range(request)
    data = reports.summary(start, end)
    if request.GET.get("format") == "xlsx":
        p = data.profit
        rows = [
            ["Sales", data.sales_count], ["Voided sales", data.voided_count], ["Gross sales", data.gross_sales],
            ["Refunds and voids", data.refunds], ["Net sales", data.net_sales], ["Average sale", data.average_sale],
            ["Paid by cash", data.by_method.get("cash", 0)], ["Paid by M-Pesa", data.by_method.get("mpesa", 0)],
            ["Given on deni", data.by_method.get("credit", 0)],
            ["Collected from sales (after refunds)", data.collected_from_sales],
            ["Deni repaid", data.deni_repaid_total], ["Total collected", data.collected_total],
            ["Collected in cash", data.collected_cash], ["Collected by M-Pesa", data.collected_mpesa],
            ["Customers owe now", data.customers_owe],
            ["Cost of goods sold", p.cost_of_sales], ["Gross profit", p.gross_profit], ["Expenses", p.expenses],
            ["Stock loss", p.stock_loss], ["Net profit", p.net_profit],
            ["Bought from suppliers", data.purchases], ["Paid to suppliers", data.paid_to_suppliers],
            ["Owed to suppliers now", data.owed_to_suppliers],
        ]
        return _xlsx("summary", start, end, "Sales summary", ["Figure", "KSh / count"], rows)
    return render(request, "finance/summary.html", {"s": data, "p": data.profit, "tab": "summary",
                                                    **_range_context(start, end, request)})


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
                                                   **_range_context(start, end, request)})


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
                                                  **_range_context(start, end, request)})


SOLD_SORTS = {"revenue": lambda r: -r.revenue, "profit": lambda r: -r.profit, "margin": lambda r: -r.margin_pct,
              "name": lambda r: r.product.name.lower()}


@owner_required
def products_view(request):
    """Sold items: what sold and at what margin. The margins add up to the period's gross profit."""
    start, end = reports.parse_range(request, default_days=29)
    sort = request.GET.get("sort") if request.GET.get("sort") in SOLD_SORTS else "revenue"
    rows = sorted(reports.sold_items(start, end), key=SOLD_SORTS[sort])
    category = request.GET.get("category", "")
    if category:
        rows = [r for r in rows if str(r.product.category_id) == category]
    totals = {"revenue": sum((r.revenue for r in rows), 0), "cost": sum((r.cost for r in rows), 0),
              "profit": sum((r.profit for r in rows), 0)}
    if request.GET.get("format") == "xlsx":
        header = ["Product", "Category", "Unit", "Quantity sold", "Cost", "Revenue", "Margin (KSh)", "Margin %",
                  "Buying price now", "Selling price now", "In stock"]
        data = [[r.product.name, str(r.product.category or ""), r.product.unit, r.quantity, r.cost, r.revenue,
                 r.profit, round(float(r.margin_pct), 1), r.product.cost_price, r.product.selling_price,
                 r.product.stock_qty] for r in rows]
        return _xlsx("sold-items", start, end, "Sold items", header, data,
                     ["Total", "", "", "", totals["cost"], totals["revenue"], totals["profit"]])
    return render(request, "finance/products.html", {
        "rows": rows, "totals": totals, "sort": sort, "tab": "products", "category": category,
        "categories": Category.objects.all(), **_range_context(start, end, request),
    })


@owner_required
def movers_view(request):
    """Fast and slow movers with a true average per day and how long current stock will last."""
    start, end = reports.parse_range(request, default_days=29)
    rows = reports.movers(start, end)
    speed = request.GET.get("speed", "")
    term = (request.GET.get("q") or "").strip().lower()
    if speed:
        rows = [r for r in rows if r.speed == speed]
    if term:
        rows = [r for r in rows if term in r.product.name.lower()]
    if request.GET.get("format") == "xlsx":
        header = ["Product", "Speed", "Unit", "Total sold", "Average per day", "Revenue", "Margin (KSh)", "In stock",
                  "Days of stock left"]
        labels = {"fast": "Fast", "slow": "Slow", "none": "Not selling"}
        data = [[r.product.name, labels[r.speed], r.product.unit, r.quantity, round(float(r.per_day), 3), r.revenue,
                 r.profit, r.product.stock_qty, round(float(r.days_left), 1) if r.days_left is not None else ""]
                for r in rows]
        return _xlsx("fast-and-slow", start, end, "Fast and slow movers", header, data)
    return render(request, "finance/movers.html", {
        "rows": rows, "speed": speed, "q": request.GET.get("q", ""), "days": (end - start).days + 1, "tab": "movers",
        **_range_context(start, end, request),
    })


@owner_required
def stock_movement_view(request):
    start, end = reports.parse_range(request, default_days=29)
    term = (request.GET.get("q") or "").strip()
    rows = reports.stock_movement(start, end, term)
    columns = [(key, label) for key, label, _ in reports.MOVEMENT_COLUMNS]
    if request.GET.get("format") == "xlsx":
        header = ["Product", "Unit", "Opening"] + [label for _, label in columns] + ["Closing", "Unit cost", "Value"]
        data = [[r.product.name, r.product.unit, r.opening] + r.cells() + [r.closing, r.product.cost_price, r.value]
                for r in rows]
        total = sum((r.value for r in rows), 0)
        return _xlsx("stock-movement", start, end, "Stock movement", header, data,
                     ["Total"] + [""] * (len(header) - 2) + [total])
    return render(request, "finance/stock_movement.html", {
        "rows": rows, "columns": columns, "q": term, "total_value": sum((r.value for r in rows), 0),
        "tab": "movement", **_range_context(start, end, request),
    })


@owner_required
def purchased_view(request):
    start, end = reports.parse_range(request, default_days=29)
    rows = reports.purchased_items(start, end)
    total = sum((r.cost for r in rows), 0)
    if request.GET.get("format") == "xlsx":
        header = ["Product", "Unit", "Quantity bought", "Total cost", "Average unit cost", "Purchases", "Suppliers"]
        data = [[r.product.name, r.product.unit, r.quantity, r.cost, r.unit_cost, r.purchases, r.suppliers]
                for r in rows]
        return _xlsx("purchased-items", start, end, "Purchased items", header, data, ["Total", "", "", total])
    return render(request, "finance/purchased.html", {"rows": rows, "total": total, "tab": "purchased",
                                                      **_range_context(start, end, request)})


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
        **_range_context(start, end, request),
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
