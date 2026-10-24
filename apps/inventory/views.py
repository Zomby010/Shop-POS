from django.contrib import messages
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.catalog.models import Category, Product, StockMovement
from apps.core.excel import xlsx_response
from apps.core.roles import STOCK_CLERK, is_owner, owner_required, role_required
from apps.partners.models import Supplier

from . import services
from .forms import (
    CancelPurchaseForm, ConversionForm, LossForm, PurchaseForm, PurchaseLineFormSet, RecountSessionForm,
    StockTakeStartForm, SupplierPaymentForm,
)
from .models import Conversion, Purchase, PurchaseLine, Recount, StockTake
from .services import StockError

stock_required = role_required(STOCK_CLERK)


@stock_required
def home(request):
    return render(request, "inventory/home.html", {
        "low_stock": Product.objects.low_stock().select_related("category")[:30],
        "open_take": StockTake.objects.filter(status=StockTake.Status.OPEN).first(),
        "purchases": Purchase.objects.select_related("supplier")[:10],
        "movements": StockMovement.objects.select_related("product", "user")[:25],
    })


@stock_required
def purchase_new(request):
    initial = {"date": timezone.localdate(), "supplier": request.GET.get("supplier")}
    form = PurchaseForm(request.POST or None, initial=initial)
    formset = PurchaseLineFormSet(request.POST or None, prefix="lines")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        items = [
            services.PurchaseItem(f.cleaned_data["product"], f.cleaned_data["packs"], f.cleaned_data["pack_size"],
                                  f.cleaned_data["pack_cost"], f.cleaned_data.get("new_price"))
            for f in formset if f.cleaned_data
        ]
        try:
            purchase = services.create_purchase(items, user=request.user, **form.cleaned_data)
        except StockError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"{purchase} saved. Stock and costs are updated.")
            return redirect("inventory:purchase_detail", pk=purchase.pk)
    return render(request, "inventory/purchase_form.html", {"form": form, "formset": formset})


@stock_required
def purchase_list(request):
    purchases = Purchase.objects.select_related("supplier", "user").annotate(line_count=Count("lines"))[:200]
    return render(request, "inventory/purchase_list.html", {"purchases": purchases})


@stock_required
def purchase_detail(request, pk):
    purchase = get_object_or_404(Purchase.objects.select_related("supplier", "user", "cancelled_by"), pk=pk)
    pay_form = SupplierPaymentForm(initial={"amount": purchase.balance, "date": timezone.localdate()})
    cancel_form = CancelPurchaseForm()
    if request.method == "POST" and request.POST.get("action") == "pay":
        pay_form = SupplierPaymentForm(request.POST)
        if pay_form.is_valid():
            try:
                services.pay_supplier(purchase, user=request.user, **pay_form.cleaned_data)
            except StockError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, f"Payment of KSh {pay_form.cleaned_data['amount']:,.2f} recorded.")
                return redirect("inventory:purchase_detail", pk=pk)
    elif request.method == "POST" and request.POST.get("action") == "cancel":
        if not is_owner(request.user):
            messages.error(request, "Only the owner can cancel a purchase.")
            return redirect("inventory:purchase_detail", pk=pk)
        cancel_form = CancelPurchaseForm(request.POST)
        if cancel_form.is_valid():
            try:
                services.cancel_purchase(purchase, user=request.user, reason=cancel_form.cleaned_data["reason"])
            except StockError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, f"{purchase} cancelled. Its stock has been taken off again.")
                return redirect("inventory:purchase_detail", pk=pk)
    return render(request, "inventory/purchase_detail.html", {
        "purchase": purchase, "lines": purchase.lines.select_related("product"),
        "payments": purchase.payments.select_related("user"), "pay_form": pay_form, "cancel_form": cancel_form,
    })


def _posted_counts(request):
    counts = {}
    for key, value in request.POST.items():
        if key.startswith("count_") and value.strip():
            product = get_object_or_404(Product, pk=key[6:])
            counts[product] = (value.strip(), request.POST.get(f"reason_{product.pk}", ""))
    return counts


@stock_required
def recount(request):
    """Search, type counts with a reason for each difference, check the summary, then confirm."""
    term = (request.GET.get("q") or "").strip()
    products = Product.objects.active().search(term).order_by("name")[:40] if term else []
    session_form = RecountSessionForm(request.POST or None)
    preview = None
    if request.method == "POST" and session_form.is_valid():
        counts = _posted_counts(request)
        try:
            if "edit" in request.POST:
                raise StockError("")
            if "confirm" in request.POST:
                session, moved = services.recount(counts, user=request.user, **session_form.cleaned_data)
                messages.success(request, f"{session} saved. {len(moved)} product{'s' if len(moved) != 1 else ''} "
                                          f"adjusted.")
                return redirect(f"{request.path}?q={term}")
            preview = services.check_counts(counts)
        except StockError as exc:
            if str(exc):
                messages.error(request, str(exc))
            products = list(counts)
            posted = {p.pk: v for p, v in counts.items()}
            for p in products:
                p.posted_count, p.posted_reason = posted[p.pk]
    return render(request, "inventory/recount.html", {
        "products": products, "q": term, "session_form": session_form, "preview": preview,
        "shortage_reasons": services.SHORTAGE_REASONS, "surplus_reasons": services.SURPLUS_REASONS,
        "recent": Recount.objects.select_related("user")[:10],
        "kind_label": dict(Recount.Kind.choices).get(session_form.cleaned_data.get("kind")) if preview else "",
    })


@stock_required
def conversion(request):
    form = ConversionForm(request.POST or None, initial={"from_product": request.GET.get("product")})
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            done = services.convert(data["from_product"], data["from_qty"], data["to_product"], data["to_qty"],
                                    user=request.user, note=data["note"])
        except StockError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"{done}: {done.from_qty.normalize():f} {done.from_product.unit} "
                                      f"{done.from_product.name} turned into {done.to_qty.normalize():f} "
                                      f"{done.to_product.unit} {done.to_product.name}.")
            return redirect("inventory:conversion")
    products = Product.objects.active().order_by("name")
    return render(request, "inventory/conversion.html", {
        "form": form, "recent": Conversion.objects.select_related("from_product", "to_product", "user")[:20],
        "product_info": {p.pk: {"unit": p.unit, "cost": float(p.cost_price), "stock": float(p.stock_qty)}
                         for p in products},
    })


@stock_required
def loss(request):
    form = LossForm(request.POST or None, initial={"product": request.GET.get("product")})
    if request.method == "POST" and form.is_valid():
        try:
            services.record_loss(form.cleaned_data["product"], form.cleaned_data["quantity"], user=request.user,
                                 reason=form.cleaned_data["reason"], note=form.cleaned_data["note"])
        except StockError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Loss recorded.")
            return redirect("inventory:loss")
    recent = StockMovement.objects.filter(kind=StockMovement.Kind.LOSS).select_related("product", "user")[:30]
    return render(request, "inventory/loss.html", {"form": form, "recent": recent, "reasons": services.LOSS_REASONS})


@stock_required
def stocktake_list(request):
    form = StockTakeStartForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            take = services.start_stocktake(user=request.user, **form.cleaned_data)
        except StockError as exc:
            messages.error(request, str(exc))
        else:
            return redirect("inventory:stocktake", pk=take.pk)
    takes = StockTake.objects.select_related("started_by", "approved_by").annotate(line_count=Count("lines"))[:50]
    return render(request, "inventory/stocktake_list.html", {"takes": takes, "form": form})


@stock_required
def stocktake(request, pk):
    take = get_object_or_404(StockTake, pk=pk)
    lines = take.lines.select_related("product", "product__category")
    category = request.GET.get("category")
    if category:
        lines = lines.filter(product__category_id=category)
    if request.GET.get("uncounted"):
        lines = lines.filter(counted_qty=None)
    if request.method == "POST":
        counts = {k[6:]: v for k, v in request.POST.items() if k.startswith("count_")}
        try:
            errors = services.save_counts(take, counts)
        except StockError as exc:
            errors = [str(exc)]
        for error in errors:
            messages.error(request, error)
        if not errors:
            messages.success(request, "Counts saved.")
        return redirect(request.get_full_path())
    all_lines = list(take.lines.all())
    counted = [l for l in all_lines if l.counted_qty is not None]
    return render(request, "inventory/stocktake.html", {
        "take": take, "lines": lines, "categories": Category.objects.all(), "category": category,
        "counted_count": len(counted), "total_count": len(all_lines),
        "variance_value": sum((l.variance_value for l in counted), 0),
    })


@owner_required
@require_POST
def stocktake_approve(request, pk):
    take = get_object_or_404(StockTake, pk=pk)
    try:
        services.approve_stocktake(take, user=request.user)
    except StockError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Stock take approved. Stock levels now match the counts.")
    return redirect("inventory:stocktake", pk=pk)


@stock_required
@require_POST
def stocktake_cancel(request, pk):
    take = get_object_or_404(StockTake, pk=pk)
    try:
        services.cancel_stocktake(take)
    except StockError as exc:
        messages.error(request, str(exc))
    return redirect("inventory:stocktakes")


@owner_required
def loss_report(request):
    start = request.GET.get("start") or None
    end = request.GET.get("end") or None
    rows = services.loose_loss_report(start, end)
    return render(request, "inventory/loss_report.html", {"rows": rows, "start": start or "", "end": end or ""})


@stock_required
def movements(request):
    qs = StockMovement.objects.select_related("product", "user")
    if request.GET.get("kind"):
        qs = qs.filter(kind=request.GET["kind"])
    if request.GET.get("product"):
        qs = qs.filter(product_id=request.GET["product"])
    if request.GET.get("reference"):
        qs = qs.filter(reference=request.GET["reference"])
    return render(request, "inventory/movements.html", {
        "movements": qs[:300], "kinds": StockMovement.Kind.choices, "kind": request.GET.get("kind", ""),
    })


def _movement_rows(movements):
    return [[timezone.localtime(m.created_at).replace(tzinfo=None), m.product.name, m.get_kind_display(),
             m.quantity, m.stock_before, m.stock_after, m.product.unit, m.unit_cost, str(m.user or ""),
             m.reason, m.reference] for m in movements]


MOVEMENT_HEADER = ["When", "Product", "Type", "Quantity", "Before", "After", "Unit", "Unit cost", "By", "Reason",
                   "Reference"]


@stock_required
def product_history(request, pk):
    """Every stock movement of one product with before and after figures, plus its cost and price changes."""
    product = get_object_or_404(Product, pk=pk)
    movements = product.movements.select_related("user", "product")
    kind = request.GET.get("kind", "")
    start, end = request.GET.get("start", ""), request.GET.get("end", "")
    if kind:
        movements = movements.filter(kind=kind)
    if start:
        movements = movements.filter(created_at__date__gte=start)
    if end:
        movements = movements.filter(created_at__date__lte=end)
    if request.GET.get("format") == "xlsx":
        return xlsx_response(f"history-{product.name}", "History", MOVEMENT_HEADER, _movement_rows(movements))
    return render(request, "inventory/product_history.html", {
        "product": product, "movements": movements[:500], "kinds": StockMovement.Kind.choices, "kind": kind,
        "start": start, "end": end, "price_changes": product.price_changes.select_related("user")[:100],
    })


@stock_required
def low_stock(request):
    """Products at or below their alert level, ready to use as a shopping list for suppliers."""
    products = list(Product.objects.low_stock().select_related("category").order_by("stock_qty", "name"))
    last_supplier = {}
    for line in (PurchaseLine.objects.filter(product__in=products, purchase__cancelled_at=None,
                                             purchase__supplier__isnull=False)
                 .select_related("purchase__supplier").order_by("purchase__date", "id")):
        last_supplier[line.product_id] = line.purchase.supplier
    for p in products:
        p.last_supplier = last_supplier.get(p.pk)
        p.order_cost = (p.reorder_qty or 0) * p.cost_price
    if request.GET.get("format") == "xlsx":
        rows = [[p.name, str(p.category or ""), p.stock_qty, p.effective_threshold, p.reorder_qty, p.unit,
                 p.cost_price, p.order_cost, str(p.last_supplier or ""), p.barcode or ""] for p in products]
        return xlsx_response("low-stock", "Low stock",
                             ["Product", "Category", "In stock", "Alert at", "Reorder qty", "Unit", "Cost", "Order cost",
                              "Last supplier", "Barcode"], rows)
    return render(request, "inventory/low_stock.html", {
        "products": products, "order_total": sum((p.order_cost for p in products), 0),
    })
