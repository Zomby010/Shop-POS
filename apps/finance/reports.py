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


def parse_range(request, default_days=0):
    today = timezone.localdate()
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
