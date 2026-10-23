from django.contrib import messages
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.catalog.models import Category, Product, StockMovement
from apps.core.roles import STOCK_CLERK, is_owner, owner_required, role_required
from apps.partners.models import Supplier

from . import services
from .forms import LossForm, PurchaseForm, PurchaseLineFormSet, StockTakeStartForm
from .models import Purchase, StockTake
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
                                  f.cleaned_data["pack_cost"])
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
    purchase = get_object_or_404(Purchase.objects.select_related("supplier", "user"), pk=pk)
    return render(request, "inventory/purchase_detail.html", {
        "purchase": purchase, "lines": purchase.lines.select_related("product"),
    })


@stock_required
def recount(request):
    term = (request.GET.get("q") or "").strip()
    products = Product.objects.active().search(term).order_by("name")[:40] if term else []
    if request.method == "POST":
        counts = {}
        for key, value in request.POST.items():
            if key.startswith("count_") and value.strip():
                counts[get_object_or_404(Product, pk=key[6:])] = value
        try:
            moved = services.recount(counts, user=request.user, reason=request.POST.get("reason") or "Recount")
        except StockError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"Recount saved. {len(moved)} product{'s' if len(moved) != 1 else ''} adjusted.")
            return redirect(f"{request.path}?q={term}")
    return render(request, "inventory/recount.html", {"products": products, "q": term})


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
    return render(request, "inventory/movements.html", {
        "movements": qs[:300], "kinds": StockMovement.Kind.choices, "kind": request.GET.get("kind", ""),
    })
