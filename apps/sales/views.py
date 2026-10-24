from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.contrib.auth import get_user_model
from django.db.models import Case, Count, DecimalField, Exists, OuterRef, Prefetch, Q, Subquery, Sum, When
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.catalog.models import Category, Product, QuickPreset, QuickSaleCategory
from apps.core.audit import verify_owner_pin
from apps.core.excel import xlsx_response
from apps.core.forms import ShopSettingsForm
from apps.core.models import ShopSettings
from apps.core.money import ZERO, to_decimal
from apps.core.roles import CASHIER, is_owner, owner_required, role_required
from apps.finance import reports
from apps.partners.models import Customer

from . import receipt, services
from .models import CashUp, Payment, Refund, Sale, SaleLine
from .services import SaleError

seller_required = role_required(CASHIER)
User = get_user_model()
MONEY = DecimalField(max_digits=12, decimal_places=2)


def _approver(request):
    """The owner approving a sensitive step: the logged-in owner, or whoever's PIN was typed."""
    if is_owner(request.user):
        return request.user
    return verify_owner_pin(request.POST.get("pin") or request.headers.get("HX-Prompt", ""))


def _cart_response(request, cart, error=None, info=None, choices=None):
    cart.refresh_from_db()
    lines = cart.lines.select_related("product")
    return render(request, "sales/_cart.html", {
        "cart": cart, "lines": lines, "error": error, "info": info, "choices": choices,
        "held_count": Sale.objects.filter(status=Sale.Status.HELD).count(),
    })


@seller_required
def sell(request):
    cart = services.current_cart(request.user)
    presets = QuickPreset.objects.filter(hidden=False).order_by("order", "id")
    categories = (
        QuickSaleCategory.objects.filter(active=True)
        .prefetch_related(Prefetch(
            "products", queryset=Product.objects.active().order_by("quick_order", "name")
            .prefetch_related(Prefetch("presets", queryset=presets))
        ))
    )
    customers = Customer.objects.filter(active=True).order_by("name")
    return render(request, "sales/sell.html", {
        "cart": cart, "lines": cart.lines.select_related("product"), "categories": categories,
        "product_categories": Category.objects.filter(products__active=True).distinct(),
        "customers": customers, "held_count": Sale.objects.filter(status=Sale.Status.HELD).count(),
    })


PRODUCT_LIST_LIMIT = 200


@seller_required
def product_list(request):
    """The sell screen's scrollable item list, for picking products without scanning."""
    products = Product.objects.active().select_related("category").with_threshold().order_by("name")
    term = request.GET.get("q", "").strip()
    if term:
        products = products.filter(
            Q(name__icontains=term) | Q(barcode__icontains=term) | Q(category__name__icontains=term)
        )
    category = request.GET.get("category")
    if category == "none":
        products = products.filter(category__isnull=True)
    elif category:
        products = products.filter(category_id=category)
    total = products.count()
    return render(request, "sales/_product_list.html", {
        "products": products[:PRODUCT_LIST_LIMIT], "total": total, "limit": PRODUCT_LIST_LIMIT,
    })


@seller_required
def cart_view(request):
    return _cart_response(request, services.current_cart(request.user))


@seller_required
@require_POST
def scan(request):
    cart = services.current_cart(request.user)
    try:
        quantity, code = services.parse_scan(request.POST.get("code"))
        if not code:
            return _cart_response(request, cart)
        found = services.find_products(code)
        if not found:
            extra = " You can add it as a new product." if is_owner(request.user) else ""
            return _cart_response(request, cart, error=f"Nothing found for '{code}'.{extra}",
                                  choices={"unknown": code})
        if len(found) > 1:
            return _cart_response(request, cart, info=f"{len(found)} products match '{code}'. Pick one:",
                                  choices={"products": found, "quantity": quantity})
        line = services.add_to_cart(cart, found[0], quantity=quantity)
    except SaleError as exc:
        return _cart_response(request, cart, error=str(exc))
    return _cart_response(request, cart, info=f"Added {line.description}.")


@seller_required
@require_POST
def add(request):
    cart = services.current_cart(request.user)
    product = get_object_or_404(Product, pk=request.POST.get("product"))
    kind, value = request.POST.get("kind", "qty"), request.POST.get("value")
    if to_decimal(value) is None:
        return _cart_response(request, cart, error="Enter a quantity or amount.")
    try:
        if kind == "amount":
            line = services.add_to_cart(cart, product, amount=value)
        else:
            line = services.add_to_cart(cart, product, quantity=value)
    except SaleError as exc:
        return _cart_response(request, cart, error=str(exc))
    return _cart_response(request, cart, info=f"Added {line.description}.")


@seller_required
@require_POST
def line_update(request, pk):
    cart = services.current_cart(request.user)
    line = get_object_or_404(cart.lines, pk=pk)
    new_qty = to_decimal(request.POST.get("quantity"))
    if new_qty is None:
        return _cart_response(request, cart, error="Enter a number.")
    approver = None
    if services.needs_approval(line, new_qty):
        approver = _approver(request)
        if approver is None:
            return _cart_response(request, cart, error="Wrong or missing owner PIN.")
    try:
        services.change_line_quantity(line, new_qty, user=request.user, approver=approver)
    except SaleError as exc:
        return _cart_response(request, cart, error=str(exc))
    return _cart_response(request, cart)


@seller_required
@require_POST
def hold(request):
    cart = services.current_cart(request.user)
    try:
        services.hold_cart(cart, request.POST.get("label", ""))
    except SaleError as exc:
        return _cart_response(request, cart, error=str(exc))
    return _cart_response(request, services.current_cart(request.user), info=f"Held as '{cart.label}'.")


@seller_required
def held_list(request):
    held = Sale.objects.filter(status=Sale.Status.HELD).select_related("cashier").prefetch_related("lines")
    return render(request, "sales/held.html", {"held": held})


@seller_required
@require_POST
def resume(request, pk):
    sale = get_object_or_404(Sale, pk=pk, status=Sale.Status.HELD)
    try:
        services.resume_cart(sale, request.user)
    except SaleError as exc:
        messages.error(request, str(exc))
    return redirect("sales:sell")


@seller_required
@require_POST
def pay(request):
    cart = services.current_cart(request.user)
    customer = None
    credit = to_decimal(request.POST.get("credit"), ZERO)
    try:
        if credit > ZERO:
            customer = _customer_from_post(request)
        sale = services.complete_sale(
            cart, user=request.user, cash_tendered=request.POST.get("cash") or None,
            mpesa=request.POST.get("mpesa"), credit=credit, customer=customer,
            mpesa_code=request.POST.get("mpesa_code", ""),
        )
    except SaleError as exc:
        response = HttpResponse(f'<p class="errorlist">{exc}</p>')
        response["HX-Retarget"] = "#pay-error"
        return response
    printer_on = ShopSettings.load().printer_connection != "none" and not settings.ONLINE
    error = receipt.print_receipt(sale) if printer_on else None
    if error:
        messages.warning(request, f"The sale is saved, but the receipt did not print: {error}")
    url = f"/sell/receipt/{sale.pk}/?done=1"
    if request.headers.get("HX-Request"):
        response = HttpResponse()
        response["HX-Redirect"] = url
        return response
    return redirect(url)


def _customer_from_post(request):
    if request.POST.get("customer"):
        return get_object_or_404(Customer, pk=request.POST["customer"], active=True)
    name = (request.POST.get("new_customer_name") or "").strip()
    if not name:
        raise SaleError("Choose the customer who is taking this on deni, or type a new customer's name.")
    phone = (request.POST.get("new_customer_phone") or "").strip()
    existing = Customer.objects.filter(name__iexact=name, phone=phone).first()
    return existing or Customer.objects.create(name=name, phone=phone)


@seller_required
def receipt_view(request, pk):
    sale = get_object_or_404(Sale.objects.select_related("cashier", "customer"), pk=pk)
    if sale.status in (Sale.Status.OPEN, Sale.Status.HELD):
        return redirect("sales:sell")
    return render(request, "sales/receipt.html", {
        "sale": sale, "rows": receipt.receipt_rows(sale), "done": request.GET.get("done"),
    })


@seller_required
@require_POST
def reprint(request, pk):
    sale = get_object_or_404(Sale, pk=pk, status__in=[Sale.Status.COMPLETED, Sale.Status.VOIDED])
    error = receipt.print_receipt(sale, reprint=True)
    if error:
        messages.error(request, error)
    else:
        messages.success(request, "Receipt sent to the printer.")
    return redirect("sales:receipt", pk=sale.pk)


def _paid(method):
    rows = Payment.objects.filter(sale=OuterRef("pk"), method=method).values("sale").annotate(t=Sum("amount"))
    return Coalesce(Subquery(rows.values("t")), ZERO, output_field=MONEY)


def _sales_list(request):
    """Completed and voided sales for the Sales page, filtered by the query string, with payment columns."""
    start, end = reports.parse_range(request)
    lo, hi = reports.day_bounds(start, end)
    refunded = Refund.objects.filter(sale=OuterRef("pk")).values("sale").annotate(t=Sum("total")).values("t")
    items = SaleLine.objects.filter(sale=OuterRef("pk")).values("sale").annotate(n=Count("id")).values("n")
    codes = Payment.objects.filter(sale=OuterRef("pk"), method=Payment.Method.MPESA).exclude(reference="")
    qs = (Sale.objects.filter(status__in=[Sale.Status.COMPLETED, Sale.Status.VOIDED])
          .select_related("cashier", "customer")
          .annotate(cash=_paid(Payment.Method.CASH), mpesa=_paid(Payment.Method.MPESA),
                    credit=_paid(Payment.Method.CREDIT),
                    refunded=Coalesce(Subquery(refunded), ZERO, output_field=MONEY),
                    item_count=Coalesce(Subquery(items), 0),
                    mpesa_code=Subquery(codes.values("reference")[:1])))
    term = (request.GET.get("q") or "").strip()
    number = term.upper().lstrip("R").lstrip("0")
    if term and number.isdigit():
        qs = qs.filter(number=int(number))  # a receipt number finds the sale on any date
    else:
        qs = qs.filter(completed_at__gte=lo, completed_at__lt=hi)
        if term:
            qs = qs.filter(Q(customer__name__icontains=term) | Q(Exists(codes.filter(reference__icontains=term))))
    method = request.GET.get("method", "")
    if method == "cash":
        qs = qs.filter(cash__gt=0, mpesa=0, credit=0)
    elif method == "mpesa":
        qs = qs.filter(mpesa__gt=0, cash=0, credit=0)
    elif method == "credit":
        qs = qs.filter(credit__gt=0)
    elif method == "split":
        qs = qs.annotate(methods=Case(When(cash__gt=0, then=1), default=0) + Case(When(mpesa__gt=0, then=1), default=0)
                         + Case(When(credit__gt=0, then=1), default=0)).filter(methods__gt=1)
    status = request.GET.get("status", "")
    if status == "voided":
        qs = qs.filter(status=Sale.Status.VOIDED)
    elif status == "refunded":
        qs = qs.filter(status=Sale.Status.COMPLETED, refunded__gt=0)
    elif status == "paid":
        qs = qs.filter(status=Sale.Status.COMPLETED, refunded=0)
    if not is_owner(request.user):
        qs = qs.filter(cashier=request.user)
    elif request.GET.get("cashier"):
        qs = qs.filter(cashier_id=request.GET["cashier"])
    return start, end, term, qs.order_by("-completed_at")


@seller_required
def history(request):
    """The Sales page: every sale in a period with how it was paid, refunds, deni and totals."""
    start, end, term, qs = _sales_list(request)
    if request.GET.get("format") == "xlsx":
        header = ["Receipt", "Date and time", "Items", "Total", "Cash", "M-Pesa", "M-Pesa code", "Deni", "Refunded",
                  "Net", "Customer", "Cashier", "Status"]
        rows = [[s.receipt_no, timezone.localtime(s.completed_at).replace(tzinfo=None), s.item_count, s.total, s.cash,
                 s.mpesa, s.mpesa_code or "", s.credit, s.refunded, s.total - s.refunded,
                 s.customer.name if s.customer else "", str(s.cashier), _sale_status(s)] for s in qs]
        return xlsx_response(f"sales-{start}-to-{end}", "Sales", header, rows)
    ids = qs.values("pk")
    totals = {"cash": 0, "mpesa": 0, "credit": 0, **{
        r["method"]: r["t"] for r in Payment.objects.filter(sale__in=ids).values("method").annotate(t=Sum("amount"))}}
    totals.update(Sale.objects.filter(pk__in=ids).aggregate(count=Count("id"), total=Coalesce(Sum("total"), ZERO)))
    totals["refunded"] = Refund.objects.filter(sale__in=ids).aggregate(t=Coalesce(Sum("total"), ZERO))["t"]
    totals["net"] = totals["total"] - totals["refunded"]
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    for sale in page:
        sale.state = _sale_status(sale)
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "sales/history.html", {
        "page": page, "q": term, "totals": totals, "start": start.isoformat(), "end": end.isoformat(),
        "periods": reports.PERIODS, "period": request.GET.get("period", ""), "method": request.GET.get("method", ""),
        "status": request.GET.get("status", ""), "cashier": request.GET.get("cashier", ""),
        "cashiers": User.objects.filter(sales__isnull=False).distinct().order_by("username") if is_owner(request.user) else [],
        "query": params.urlencode(),
    })


def _sale_status(sale):
    if sale.status == Sale.Status.VOIDED:
        return "Voided"
    if sale.refunded:
        return "Part refunded"
    return "On deni" if sale.credit else "Paid"


@seller_required
def sale_detail(request, pk):
    sale = get_object_or_404(Sale.objects.select_related("cashier", "customer"), pk=pk)
    if sale.status in (Sale.Status.OPEN, Sale.Status.HELD):
        return redirect("sales:sell")
    if request.method == "POST":
        approver = _approver(request)
        reason = request.POST.get("reason", "")
        try:
            if request.POST.get("action") == "void":
                services.void_sale(sale, user=request.user, approver=approver, reason=reason)
                messages.success(request, f"{sale.receipt_no} voided. Stock is back and payments are reversed.")
            else:
                quantities = {k[4:]: v for k, v in request.POST.items() if k.startswith("qty_")}
                refund = services.refund_lines(sale, quantities, user=request.user, approver=approver, reason=reason,
                                               method=request.POST.get("method", Refund.Method.CASH))
                messages.success(request, f"Refunded KSh {refund.total:,.2f}.")
        except SaleError as exc:
            if approver is None and not is_owner(request.user):
                exc = SaleError("Wrong or missing owner PIN.")
            messages.error(request, str(exc))
        return redirect("sales:sale_detail", pk=sale.pk)
    return render(request, "sales/sale_detail.html", {
        "sale": sale, "lines": sale.lines.all(), "payments": sale.payments.all(),
        "refunds": sale.refunds.select_related("user", "authorised_by").prefetch_related("lines__sale_line"),
        "refund_methods": Refund.Method.choices,
    })


@seller_required
def cashup(request):
    now = timezone.now()
    start = services.cashup_period_start(request.user, now)
    opening_float = to_decimal(request.POST.get("opening_float") or request.GET.get("opening_float"), ZERO)
    if request.method == "POST":
        record = services.save_cashup(
            request.user, counted_cash=request.POST.get("counted_cash"), counted_mpesa=request.POST.get("counted_mpesa"),
            opening_float=opening_float, note=request.POST.get("note", ""), now=now,
        )
        messages.success(request, "Cash-up saved.")
        return redirect("sales:cashup_detail", pk=record.pk)
    expected = services.expected_takings(request.user, start, now, opening_float)
    return render(request, "sales/cashup.html", {"expected": expected, "opening_float": opening_float})


@seller_required
def cashup_detail(request, pk):
    record = get_object_or_404(CashUp, pk=pk)
    if record.cashier != request.user and not is_owner(request.user):
        return redirect("sales:cashup")
    expected = services.expected_takings(record.cashier, record.period_start, record.period_end, record.opening_float)
    return render(request, "sales/cashup_detail.html", {"record": record, "expected": expected})


@owner_required
def cashup_list(request):
    records = CashUp.objects.select_related("cashier")[:200]
    return render(request, "sales/cashup_list.html", {"records": records})


@owner_required
@require_POST
def test_print(request):
    form = ShopSettingsForm(request.POST, request.FILES, instance=ShopSettings.load())
    if form.is_valid():
        shop = form.save()
        try:
            receipt.send_to_printer(receipt.sample_receipt_lines(shop), shop)
        except receipt.PrinterError as exc:
            messages.error(request, f"Settings saved, but the test receipt failed: {exc}")
        else:
            messages.success(request, "Settings saved and test receipt sent.")
    else:
        messages.error(request, "Fix the settings errors first.")
    return redirect("settings")
