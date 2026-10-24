"""Profit, sales, best/slow sellers and stock value. Dates are local shop days."""

from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.catalog.models import Category, Product, StockMovement
from apps.core.money import ZERO, q2
from apps.inventory.models import Purchase, PurchaseLine, SupplierPayment
from apps.partners.models import CreditEntry, Customer
from apps.sales.models import Payment, Refund, RefundLine, Sale, SaleLine

from .models import Expense

SOLD = [Sale.Status.COMPLETED, Sale.Status.VOIDED]


def day_bounds(start, end):
    tz = timezone.get_current_timezone()
    return (timezone.make_aware(datetime.combine(start, time.min), tz),
            timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min), tz))


def days_between(start, end):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


PERIODS = [
    ("today", "Today"), ("yesterday", "Yesterday"), ("this_week", "This week"), ("last_week", "Last week"),
    ("this_month", "This month"), ("last_month", "Last month"), ("this_year", "This year"), ("last_year", "Last year"),
]


def period_range(period, today=None):
    """Start and end dates for a named period; weeks start on Monday. None if the name is unknown."""
    today = today or timezone.localdate()
    if period == "today":
        return today, today
    if period == "yesterday":
        day = today - timedelta(days=1)
        return day, day
    if period == "this_week":
        return today - timedelta(days=today.weekday()), today
    if period == "last_week":
        end = today - timedelta(days=today.weekday() + 1)
        return end - timedelta(days=6), end
    if period == "this_month":
        return today.replace(day=1), today
    if period == "last_month":
        end = today.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    if period == "this_year":
        return today.replace(month=1, day=1), today
    if period == "last_year":
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    return None


def parse_range(request, default_days=0):
    today = timezone.localdate()
    named = period_range(request.GET.get("period", ""), today)
    if named:
        return named
    try:
        start = date.fromisoformat(request.GET.get("start", ""))
    except ValueError:
        start = today - timedelta(days=default_days)
    try:
        end = date.fromisoformat(request.GET.get("end", ""))
    except ValueError:
        end = today
    if end < start:
        start, end = end, start
    return start, end


def _by_day(qs, date_field, value_expr):
    rows = qs.annotate(day=TruncDate(date_field, tzinfo=timezone.get_current_timezone())).values("day").annotate(v=value_expr)
    return {row["day"]: row["v"] or ZERO for row in rows}


LINE_COST = ExpressionWrapper(F("quantity") * F("unit_cost"), output_field=DecimalField(max_digits=18, decimal_places=5))
REFUND_COST = ExpressionWrapper(F("quantity") * F("sale_line__unit_cost"),
                                output_field=DecimalField(max_digits=18, decimal_places=5))
MOVE_VALUE = ExpressionWrapper(F("quantity") * F("unit_cost"), output_field=DecimalField(max_digits=18, decimal_places=5))


@dataclass
class ProfitDay:
    day: date
    sales: Decimal = ZERO
    refunds: Decimal = ZERO
    cost_of_sales: Decimal = ZERO
    expenses: Decimal = ZERO
    stock_loss: Decimal = ZERO

    @property
    def net_sales(self):
        return self.sales - self.refunds

    @property
    def gross_profit(self):
        return self.net_sales - self.cost_of_sales

    @property
    def net_profit(self):
        return self.gross_profit - self.expenses - self.stock_loss

    @property
    def margin_pct(self):
        return (self.gross_profit / self.net_sales * 100) if self.net_sales else ZERO


@dataclass
class ProfitReport:
    start: date
    end: date
    days: list
    expenses_by_category: list = field(default_factory=list)
    loss_by_kind: list = field(default_factory=list)

    def _sum(self, attr):
        return sum((getattr(d, attr) for d in self.days), ZERO)

    @property
    def total(self):
        t = ProfitDay(self.end)
        for attr in ("sales", "refunds", "cost_of_sales", "expenses", "stock_loss"):
            setattr(t, attr, q2(self._sum(attr)))
        return t


def profit(start, end):
    """Sales minus cost of goods = gross profit; minus expenses and stock loss = net profit."""
    lo, hi = day_bounds(start, end)
    lines = SaleLine.objects.filter(sale__status__in=SOLD, sale__completed_at__gte=lo, sale__completed_at__lt=hi)
    refunds = RefundLine.objects.filter(refund__created_at__gte=lo, refund__created_at__lt=hi)
    expenses = Expense.objects.filter(date__gte=start, date__lte=end)
    losses = StockMovement.objects.filter(
        created_at__gte=lo, created_at__lt=hi,
        kind__in=[StockMovement.Kind.LOSS, StockMovement.Kind.STOCKTAKE, StockMovement.Kind.RECOUNT],
    )
    sales = _by_day(lines, "sale__completed_at", Sum("line_total"))
    costs = _by_day(lines, "sale__completed_at", Sum(LINE_COST))
    refund_amounts = _by_day(refunds, "refund__created_at", Sum("amount"))
    refund_costs = _by_day(refunds, "refund__created_at", Sum(REFUND_COST))
    loss_values = _by_day(losses, "created_at", Sum(MOVE_VALUE))
    expense_days = {row["date"]: row["v"] for row in expenses.values("date").annotate(v=Sum("amount"))}
    days = []
    for day in days_between(start, end):
        days.append(ProfitDay(
            day=day, sales=sales.get(day, ZERO), refunds=refund_amounts.get(day, ZERO),
            cost_of_sales=q2(costs.get(day, ZERO) - refund_costs.get(day, ZERO)),
            expenses=expense_days.get(day, ZERO), stock_loss=q2(-loss_values.get(day, ZERO)),
        ))
    by_category = [
        (row["category__name"], row["v"])
        for row in expenses.values("category__name").annotate(v=Sum("amount")).order_by("-v")
    ]
    by_kind = [
        (StockMovement.Kind(row["kind"]).label, q2(-(row["v"] or ZERO)))
        for row in losses.values("kind").annotate(v=Sum(MOVE_VALUE)).order_by("kind")
    ]
    return ProfitReport(start, end, days, by_category, by_kind)


@dataclass
class SalesDay:
    day: date
    count: int = 0
    total: Decimal = ZERO
    cash: Decimal = ZERO
    mpesa: Decimal = ZERO
    credit: Decimal = ZERO
    refunds: Decimal = ZERO
    voided: int = 0

    @property
    def net(self):
        return self.total - self.refunds


def sales_report(start, end):
    """Totals per day split by cash, M-Pesa and deni."""
    lo, hi = day_bounds(start, end)
    sales = Sale.objects.filter(status__in=SOLD, completed_at__gte=lo, completed_at__lt=hi)
    counts = _by_day(sales, "completed_at", Count("id"))
    voided = _by_day(sales.filter(status=Sale.Status.VOIDED), "completed_at", Count("id"))
    totals = _by_day(sales, "completed_at", Sum("total"))
    payments = Payment.objects.filter(sale__in=sales)
    by_method = {
        method: _by_day(payments.filter(method=method), "sale__completed_at", Sum("amount"))
        for method in Payment.Method.values
    }
    refunds = _by_day(Refund.objects.filter(created_at__gte=lo, created_at__lt=hi), "created_at", Sum("total"))
    rows = [
        SalesDay(day, int(counts.get(day, 0) or 0), totals.get(day, ZERO), by_method["cash"].get(day, ZERO),
                 by_method["mpesa"].get(day, ZERO), by_method["credit"].get(day, ZERO), refunds.get(day, ZERO),
                 int(voided.get(day, 0) or 0))
        for day in days_between(start, end)
    ]
    total = SalesDay(end)
    for row in rows:
        for attr in ("count", "total", "cash", "mpesa", "credit", "refunds", "voided"):
            setattr(total, attr, getattr(total, attr) + getattr(row, attr))
    return rows, total


@dataclass
class ProductSales:
    product: Product
    quantity: Decimal
    revenue: Decimal
    profit: Decimal


def product_sales(start, end):
    """Every active product with what it sold in the period (net of returns), best first."""
    lo, hi = day_bounds(start, end)
    lines = (SaleLine.objects.filter(sale__status=Sale.Status.COMPLETED, sale__completed_at__gte=lo, sale__completed_at__lt=hi)
             .values("product").annotate(qty=Sum("quantity"), refunded=Sum("refunded_qty"), revenue=Sum("line_total"),
                                          cost=Sum(LINE_COST)))
    refunds = (RefundLine.objects.filter(sale_line__sale__status=Sale.Status.COMPLETED,
                                         sale_line__sale__completed_at__gte=lo, sale_line__sale__completed_at__lt=hi)
               .values("sale_line__product").annotate(amount=Sum("amount"), cost=Sum(REFUND_COST)))
    refund_map = {r["sale_line__product"]: r for r in refunds}
    sold = {}
    for row in lines:
        r = refund_map.get(row["product"], {})
        revenue = row["revenue"] - (r.get("amount") or ZERO)
        cost = (row["cost"] or ZERO) - (r.get("cost") or ZERO)
        sold[row["product"]] = (row["qty"] - row["refunded"], revenue, q2(revenue - cost))
    result = []
    for product in Product.objects.active().select_related("category"):
        qty, revenue, gross = sold.get(product.pk, (ZERO, ZERO, ZERO))
        result.append(ProductSales(product, qty, revenue, gross))
    return result


def best_and_slow(start, end, limit=20):
    rows = product_sales(start, end)
    by_revenue = sorted((r for r in rows if r.revenue > ZERO), key=lambda r: r.revenue, reverse=True)
    slow = sorted(rows, key=lambda r: (r.revenue, r.product.name))
    return by_revenue[:limit], slow[:limit], rows


@dataclass
class StockValueRow:
    category: str
    products: int
    at_cost: Decimal
    at_price: Decimal

    @property
    def potential_profit(self):
        return self.at_price - self.at_cost


def stock_value():
    groups = OrderedDict()
    for product in Product.objects.active().select_related("category").order_by("category__order", "category__name", "name"):
        name = product.category.name if product.category else "No category"
        row = groups.setdefault(name, StockValueRow(name, 0, ZERO, ZERO))
        row.products += 1
        if product.stock_qty > ZERO:
            row.at_cost += product.stock_qty * product.cost_price
            row.at_price += product.stock_qty * product.selling_price
    rows = list(groups.values())
    for row in rows:
        row.at_cost, row.at_price = q2(row.at_cost), q2(row.at_price)
    total = StockValueRow("Total", sum(r.products for r in rows), sum((r.at_cost for r in rows), ZERO),
                          sum((r.at_price for r in rows), ZERO))
    return rows, total


# ---------------------------------------------------------------- summary

@dataclass
class Summary:
    start: date
    end: date
    profit: ProfitDay
    sales_count: int = 0
    voided_count: int = 0
    gross_sales: Decimal = ZERO
    refunds: Decimal = ZERO
    by_method: dict = field(default_factory=dict)
    refunds_by_method: dict = field(default_factory=dict)
    deni_repaid: dict = field(default_factory=dict)
    customers_owe: Decimal = ZERO
    purchases: Decimal = ZERO
    paid_to_suppliers: Decimal = ZERO
    owed_to_suppliers: Decimal = ZERO

    @property
    def net_sales(self):
        return self.gross_sales - self.refunds

    @property
    def average_sale(self):
        return q2(self.net_sales / self.sales_count) if self.sales_count else ZERO

    def collected(self, method):
        """Money that came in by cash or M-Pesa: sales paid that way, less refunds paid out that way,
        plus deni repaid that way."""
        return (self.by_method.get(method, ZERO) - self.refunds_by_method.get(method, ZERO)
                + self.deni_repaid.get(method, ZERO))

    @property
    def collected_cash(self):
        return self.collected("cash")

    @property
    def collected_mpesa(self):
        return self.collected("mpesa")

    @property
    def collected_total(self):
        return self.collected_cash + self.collected_mpesa

    @property
    def collected_from_sales(self):
        return sum((self.by_method.get(m, ZERO) - self.refunds_by_method.get(m, ZERO) for m in ("cash", "mpesa")), ZERO)

    @property
    def deni_repaid_total(self):
        return sum(self.deni_repaid.values(), ZERO)

    @property
    def deni_given(self):
        return self.by_method.get("credit", ZERO) - self.refunds_by_method.get("credit", ZERO)


def summary(start, end):
    """Headline figures for a period: sales, payments, money collected, deni, profit and suppliers."""
    lo, hi = day_bounds(start, end)
    sales = Sale.objects.filter(status__in=SOLD, completed_at__gte=lo, completed_at__lt=hi)
    refunds = Refund.objects.filter(created_at__gte=lo, created_at__lt=hi)
    repaid = CreditEntry.objects.filter(kind=CreditEntry.Kind.REPAYMENT, method__in=["cash", "mpesa"],
                                        created_at__gte=lo, created_at__lt=hi)
    purchases = Purchase.objects.filter(date__gte=start, date__lte=end, cancelled_at=None)
    open_purchases = Purchase.objects.filter(cancelled_at=None)
    return Summary(
        start, end, profit(start, end).total,
        sales_count=sales.filter(status=Sale.Status.COMPLETED).count(),
        voided_count=sales.filter(status=Sale.Status.VOIDED).count(),
        gross_sales=sales.aggregate(t=Sum("total"))["t"] or ZERO,
        refunds=refunds.aggregate(t=Sum("total"))["t"] or ZERO,
        by_method={r["method"]: r["t"] for r in Payment.objects.filter(sale__in=sales).values("method")
                   .annotate(t=Sum("amount"))},
        refunds_by_method={r["method"]: r["t"] for r in refunds.values("method").annotate(t=Sum("total"))},
        deni_repaid={r["method"]: r["t"] for r in repaid.values("method").annotate(t=Sum("amount"))},
        customers_owe=Customer.objects.filter(balance__gt=0).aggregate(t=Sum("balance"))["t"] or ZERO,
        purchases=purchases.aggregate(t=Sum("total"))["t"] or ZERO,
        paid_to_suppliers=SupplierPayment.objects.filter(date__gte=start, date__lte=end,
                                                         purchase__cancelled_at=None)
        .aggregate(t=Sum("amount"))["t"] or ZERO,
        owed_to_suppliers=(open_purchases.aggregate(t=Sum(F("total") - F("amount_paid")))["t"] or ZERO),
    )


# ---------------------------------------------------------------- items

@dataclass
class ItemRow:
    product: Product
    quantity: Decimal
    revenue: Decimal
    profit: Decimal
    days: int = 1

    @property
    def cost(self):
        return self.revenue - self.profit

    @property
    def margin_pct(self):
        return self.profit / self.revenue * 100 if self.revenue else ZERO

    @property
    def per_day(self):
        """Average sold per calendar day of the period, not per day with sales."""
        return self.quantity / self.days

    @property
    def days_left(self):
        """How many days the current stock lasts at that pace; None if it isn't selling."""
        if self.per_day <= ZERO:
            return None
        return max(self.product.stock_qty, ZERO) / self.per_day


def sold_items(start, end):
    """Products that sold in the period, with cost, revenue and margin. Margins add up to gross profit."""
    days = (end - start).days + 1
    rows = [ItemRow(r.product, r.quantity, r.revenue, r.profit, days) for r in product_sales(start, end)]
    return [r for r in rows if r.quantity or r.revenue]


def movers(start, end):
    """Every active product ranked by sales value (kg and pieces can't be compared directly).
    Fast = top fifth of the products that sold; slow = the rest that sold; not selling = nothing sold."""
    days = (end - start).days + 1
    rows = [ItemRow(r.product, r.quantity, r.revenue, r.profit, days) for r in product_sales(start, end)]
    selling = sorted((r for r in rows if r.quantity > ZERO), key=lambda r: (-r.revenue, r.product.name))
    fast_count = max(1, len(selling) // 5) if selling else 0
    for i, row in enumerate(selling):
        row.speed = "fast" if i < fast_count else "slow"
    idle = sorted((r for r in rows if r.quantity <= ZERO), key=lambda r: r.product.name)
    for row in idle:
        row.speed = "none"
    return selling + idle


# ---------------------------------------------------------------- stock movement

MOVEMENT_COLUMNS = [
    ("added", "New stock", [StockMovement.Kind.OPENING]),
    ("purchased", "Purchased", [StockMovement.Kind.PURCHASE, StockMovement.Kind.PURCHASE_CANCEL]),
    ("conv_in", "Converted in", [StockMovement.Kind.CONVERSION_IN]),
    ("conv_out", "Converted out", [StockMovement.Kind.CONVERSION_OUT]),
    ("sold", "Sold", [StockMovement.Kind.SALE]),
    ("returned", "Returned", [StockMovement.Kind.REFUND]),
    ("lost", "Losses", [StockMovement.Kind.LOSS]),
    ("counted", "Count changes", [StockMovement.Kind.RECOUNT, StockMovement.Kind.STOCKTAKE]),
]


@dataclass
class MovementRow:
    product: Product
    opening: Decimal
    values: dict

    @property
    def closing(self):
        return self.opening + sum(self.values.values(), ZERO)

    @property
    def value(self):
        return q2(max(self.closing, ZERO) * self.product.cost_price)

    def cells(self):
        return [self.values.get(key, ZERO) for key, _, _ in MOVEMENT_COLUMNS]


def stock_movement(start, end, search=""):
    """Opening + every kind of movement = closing, per product. Opening is everything before the period,
    including opening-stock entries, so every row adds up whatever period you choose."""
    lo, hi = day_bounds(start, end)
    products = Product.objects.active().select_related("category").search(search).order_by("name")
    before = {r["product"]: r["q"] for r in StockMovement.objects.filter(created_at__lt=lo, product__in=products)
              .values("product").annotate(q=Sum("quantity"))}
    column_of = {kind: key for key, _, kinds in MOVEMENT_COLUMNS for kind in kinds}
    during = defaultdict(dict)
    for r in (StockMovement.objects.filter(created_at__gte=lo, created_at__lt=hi, product__in=products)
              .values("product", "kind").annotate(q=Sum("quantity"))):
        key = column_of.get(r["kind"], "counted")
        during[r["product"]][key] = during[r["product"]].get(key, ZERO) + r["q"]
    return [MovementRow(p, before.get(p.pk, ZERO), during.get(p.pk, {})) for p in products]


# ---------------------------------------------------------------- purchases

@dataclass
class PurchasedRow:
    product: Product
    quantity: Decimal
    cost: Decimal
    purchases: int
    suppliers: str

    @property
    def unit_cost(self):
        return q2(self.cost / self.quantity) if self.quantity else ZERO


def purchased_items(start, end):
    """What was bought from suppliers in the period (cancelled purchases left out). Conversions and opening
    stock are not purchases and never appear here."""
    lines = (PurchaseLine.objects.filter(purchase__date__gte=start, purchase__date__lte=end,
                                         purchase__cancelled_at=None)
             .select_related("product", "purchase__supplier"))
    grouped = OrderedDict()
    for line in lines.order_by("product__name"):
        row = grouped.setdefault(line.product_id, [line.product, ZERO, ZERO, set(), set()])
        row[1] += line.quantity
        row[2] += line.line_total
        row[3].add(line.purchase_id)
        if line.purchase.supplier:
            row[4].add(line.purchase.supplier.name)
    return [PurchasedRow(p, q, c, len(ids), ", ".join(sorted(names))) for p, q, c, ids, names in grouped.values()]
