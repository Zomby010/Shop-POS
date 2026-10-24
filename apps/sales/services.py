"""Cart, checkout, refund and cash-up rules. Views stay thin; everything here is tested."""

from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.catalog.models import Product, StockMovement
from apps.catalog.pricing import PricingError, line_total, price_by_amount, price_by_quantity, unit_price_for
from apps.catalog.stock import record_movement
from apps.core import audit
from apps.core.models import Sequence
from apps.core.money import ZERO, q2, q3, to_decimal
from apps.partners.models import CreditEntry, Customer, recalculate_balance

from .models import CashUp, Payment, Refund, RefundLine, Sale, SaleLine


class SaleError(ValueError):
    pass


# ---------------------------------------------------------------- carts

def current_cart(user):
    cart = Sale.objects.filter(cashier=user, status=Sale.Status.OPEN).order_by("-id").first()
    return cart or Sale.objects.create(cashier=user)


def _reprice(line):
    product = line.product
    if line.entered_as == SaleLine.EnteredAs.AMOUNT:
        return
    line.unit_price, line.tier_applied = unit_price_for(product, line.quantity)
    line.line_total = line_total(product, line.quantity, line.unit_price)


@transaction.atomic
def add_to_cart(cart, product, *, quantity=None, amount=None):
    """Add a product by quantity or by amount. Repeat scans of the same product merge into one line."""
    if not cart.is_editable:
        raise SaleError("This sale is already finished.")
    if not product.active:
        raise SaleError(f"{product.name} is marked inactive.")
    try:
        if amount is not None:
            priced = price_by_amount(product, to_decimal(amount))
            entered_as = SaleLine.EnteredAs.AMOUNT
        else:
            priced = price_by_quantity(product, to_decimal(quantity, Decimal(1)))
            entered_as = SaleLine.EnteredAs.QUANTITY
    except PricingError as exc:
        raise SaleError(str(exc))

    if entered_as == SaleLine.EnteredAs.QUANTITY and not product.is_loose:
        existing = cart.lines.filter(product=product, entered_as=entered_as).first()
        if existing:
            existing.quantity = q3(existing.quantity + priced.quantity)
            _reprice(existing)
            existing.save()
            _save_totals(cart)
            return existing
    line = SaleLine.objects.create(
        sale=cart, product=product, description=product.name, unit=product.unit,
        quantity=priced.quantity, unit_price=priced.unit_price, line_total=priced.total,
        tier_applied=priced.tier_applied, entered_as=entered_as,
    )
    _save_totals(cart)
    return line


def _save_totals(cart):
    cart.recalculate()
    cart.save(update_fields=["subtotal", "total"])


def needs_approval(line, new_quantity):
    """Lowering or removing a line needs the owner's PIN; adding more does not."""
    return new_quantity < line.quantity


@transaction.atomic
def change_line_quantity(line, new_quantity, *, user, approver=None, reason=""):
    new_quantity = q3(new_quantity)
    if not line.sale.is_editable:
        raise SaleError("This sale is already finished.")
    if new_quantity < ZERO:
        raise SaleError("Quantity can't be negative.")
    if needs_approval(line, new_quantity) and approver is None:
        raise SaleError("The owner's PIN is needed to reduce or remove a line.")
    if new_quantity == ZERO:
        audit.log("void line", user=user, authorised_by=approver, obj=line, reason=reason or "Removed from cart",
                  product=line.product.name, quantity=line.quantity, amount=line.line_total)
        sale = line.sale
        line.delete()
        _save_totals(sale)
        return None
    if not line.product.is_loose and new_quantity != new_quantity.to_integral_value():
        raise SaleError(f"{line.product.name} is sold by the piece, so the quantity must be a whole number.")
    if needs_approval(line, new_quantity):
        audit.log("reduce line", user=user, authorised_by=approver, obj=line, reason=reason or "Reduced in cart",
                  product=line.product.name, old=line.quantity, new=new_quantity)
    line.quantity = new_quantity
    line.entered_as = SaleLine.EnteredAs.QUANTITY
    _reprice(line)
    line.save()
    _save_totals(line.sale)
    return line


@transaction.atomic
def hold_cart(cart, label=""):
    if not cart.lines.exists():
        raise SaleError("The cart is empty, so there is nothing to hold.")
    cart.status = Sale.Status.HELD
    cart.label = label.strip()[:80] or f"Held {timezone.localtime():%H:%M}"
    cart.save(update_fields=["status", "label"])
    return cart


@transaction.atomic
def resume_cart(sale, user):
    if sale.status != Sale.Status.HELD:
        raise SaleError("That sale is not on hold.")
    current = Sale.objects.filter(cashier=user, status=Sale.Status.OPEN)
    for cart in current:
        if cart.lines.exists():
            hold_cart(cart)
        else:
            cart.delete()
    sale.status = Sale.Status.OPEN
    sale.cashier = user
    sale.save(update_fields=["status", "cashier"])
    return sale


# ---------------------------------------------------------------- checkout

@dataclass
class PaymentPlan:
    cash: Decimal
    mpesa: Decimal
    credit: Decimal
    tendered: Decimal
    change: Decimal


def plan_payment(total, *, cash_tendered=None, mpesa=None, credit=None):
    """Split a total across cash, M-Pesa and deni. Cash covers whatever M-Pesa and deni don't."""
    mpesa = q2(to_decimal(mpesa, ZERO))
    credit = q2(to_decimal(credit, ZERO))
    if mpesa < ZERO or credit < ZERO:
        raise SaleError("Amounts can't be negative.")
    if mpesa + credit > total:
        raise SaleError(f"M-Pesa and deni add up to more than the total of {total:,.2f}.")
    cash_due = q2(total - mpesa - credit)
    tendered = to_decimal(cash_tendered)
    if tendered is None:
        tendered = cash_due
    tendered = q2(tendered)
    if tendered < cash_due:
        raise SaleError(f"Cash given ({tendered:,.2f}) is less than the cash due ({cash_due:,.2f}).")
    if cash_due == ZERO:
        tendered = ZERO
    return PaymentPlan(cash_due, mpesa, credit, tendered, q2(tendered - cash_due))


@transaction.atomic
def complete_sale(cart, *, user, cash_tendered=None, mpesa=None, credit=None, customer=None, mpesa_code=""):
    cart = Sale.objects.select_for_update().get(pk=cart.pk)
    if not cart.is_editable:
        raise SaleError("This sale is already finished.")
    lines = list(cart.lines.select_related("product"))
    if not lines:
        raise SaleError("The cart is empty.")
    total = cart.recalculate()
    plan = plan_payment(total, cash_tendered=cash_tendered, mpesa=mpesa, credit=credit)
    if plan.credit > ZERO:
        if customer is None:
            raise SaleError("Choose the customer who is taking this on deni.")
        available = customer.available_credit()
        if available is not None and plan.credit > available:
            raise SaleError(f"{customer.name} only has {available:,.2f} of credit left.")

    cart.number = Sequence.next("receipt")
    cart.status = Sale.Status.COMPLETED
    cart.completed_at = timezone.now()
    cart.cashier = user
    cart.customer = customer if plan.credit > ZERO else None
    cart.amount_tendered = plan.tendered
    cart.change_given = plan.change
    cost_total = ZERO
    for line in lines:
        movement = record_movement(
            line.product, StockMovement.Kind.SALE, -line.quantity, user=user, reference=cart.receipt_no
        )
        line.unit_cost = movement.unit_cost
        line.save(update_fields=["unit_cost"])
        cost_total += line.quantity * line.unit_cost
    cart.cost_total = q2(cost_total)
    cart.save()
    for method, amount in ((Payment.Method.CASH, plan.cash), (Payment.Method.MPESA, plan.mpesa),
                           (Payment.Method.CREDIT, plan.credit)):
        if amount > ZERO:
            reference = (mpesa_code or "").strip().upper()[:30] if method == Payment.Method.MPESA else ""
            Payment.objects.create(sale=cart, method=method, amount=amount, reference=reference)
    if plan.credit > ZERO:
        CreditEntry.objects.create(customer=customer, kind=CreditEntry.Kind.CHARGE, amount=plan.credit, sale=cart,
                                   user=user, note=f"Receipt {cart.receipt_no}")
        recalculate_balance(customer)
    return cart


# ---------------------------------------------------------------- refunds and voids

@transaction.atomic
def refund_lines(sale, quantities, *, user, approver, reason, method=Refund.Method.CASH):
    """Refund some items of a completed sale. `quantities` maps SaleLine id -> quantity to return."""
    if approver is None:
        raise SaleError("The owner's PIN is needed for a refund.")
    if not reason.strip():
        raise SaleError("Give a reason for the refund.")
    if sale.status != Sale.Status.COMPLETED:
        raise SaleError("Only completed sales can be refunded.")
    if method == Refund.Method.CREDIT and sale.customer is None:
        raise SaleError("This sale has no deni customer to credit.")
    refund = Refund.objects.create(sale=sale, user=user, authorised_by=approver, reason=reason, method=method)
    total = ZERO
    for line in sale.lines.select_for_update():
        qty = q3(to_decimal(quantities.get(line.pk) or quantities.get(str(line.pk)), ZERO))
        if qty <= ZERO:
            continue
        if qty > line.refundable_qty:
            raise SaleError(f"Only {line.refundable_qty.normalize()} {line.unit} of {line.description} can be returned.")
        amount = line.line_total if qty == line.quantity else q2(line.line_total * qty / line.quantity)
        RefundLine.objects.create(refund=refund, sale_line=line, quantity=qty, amount=amount)
        record_movement(line.product, StockMovement.Kind.REFUND, qty, unit_cost=line.unit_cost, user=user,
                        reason=reason, reference=sale.receipt_no)
        line.refunded_qty = q3(line.refunded_qty + qty)
        line.save(update_fields=["refunded_qty"])
        total += amount
    if total == ZERO:
        raise SaleError("Choose at least one item to return.")
    refund.total = total
    refund.save(update_fields=["total"])
    if method == Refund.Method.CREDIT:
        CreditEntry.objects.create(customer=sale.customer, kind=CreditEntry.Kind.REPAYMENT, amount=total, sale=sale,
                                   user=user, note=f"Refund on {sale.receipt_no}")
        recalculate_balance(sale.customer)
    audit.log("refund", user=user, authorised_by=approver, obj=sale, reason=reason, amount=total, method=method)
    return refund


@transaction.atomic
def void_sale(sale, *, user, approver, reason):
    """Cancel a whole completed sale: stock comes back and each payment is reversed the way it was paid."""
    if approver is None:
        raise SaleError("The owner's PIN is needed to void a sale.")
    if not reason.strip():
        raise SaleError("Give a reason for voiding the sale.")
    sale = Sale.objects.select_for_update().get(pk=sale.pk)
    if sale.status != Sale.Status.COMPLETED:
        raise SaleError("Only completed sales can be voided.")
    if sale.refunds.exists():
        raise SaleError("Part of this sale was already refunded. Refund the remaining items instead.")
    payments = list(sale.payments.all())
    refunds = [
        Refund.objects.create(sale=sale, user=user, authorised_by=approver, reason=reason, method=p.method,
                              total=p.amount, is_void=True)
        for p in payments
    ]
    for line in sale.lines.all():
        RefundLine.objects.create(refund=refunds[0], sale_line=line, quantity=line.quantity, amount=line.line_total)
        record_movement(line.product, StockMovement.Kind.REFUND, line.quantity, unit_cost=line.unit_cost, user=user,
                        reason=f"Void: {reason}", reference=sale.receipt_no)
        line.refunded_qty = line.quantity
        line.save(update_fields=["refunded_qty"])
    if sale.customer_id:
        for entry in sale.credit_entries.filter(kind=CreditEntry.Kind.CHARGE):
            CreditEntry.objects.create(customer=sale.customer, kind=CreditEntry.Kind.REPAYMENT, amount=entry.amount,
                                       sale=sale, user=user, note=f"Void of {sale.receipt_no}")
        recalculate_balance(sale.customer)
    sale.status = Sale.Status.VOIDED
    sale.save(update_fields=["status"])
    audit.log("void sale", user=user, authorised_by=approver, obj=sale, reason=reason, amount=sale.total)
    return sale


# ---------------------------------------------------------------- deni repayments

@transaction.atomic
def record_repayment(customer, amount, method, *, user, note=""):
    amount = q2(to_decimal(amount, ZERO))
    if amount <= ZERO:
        raise SaleError("Enter the amount repaid.")
    if method not in (CreditEntry.Method.CASH, CreditEntry.Method.MPESA):
        raise SaleError("Repayments are cash or M-Pesa.")
    entry = CreditEntry.objects.create(customer=customer, kind=CreditEntry.Kind.REPAYMENT, amount=amount,
                                       method=method, user=user, note=note)
    recalculate_balance(customer)
    return entry


# ---------------------------------------------------------------- cash-up

def start_of_day(now=None):
    now = timezone.localtime(now)
    return timezone.make_aware(datetime.combine(now.date(), time.min))


def cashup_period_start(user, now=None):
    last = CashUp.objects.filter(cashier=user).order_by("-period_end").first()
    day_start = start_of_day(now)
    if last and last.period_end > day_start:
        return last.period_end
    return day_start


@dataclass
class ExpectedTakings:
    start: datetime
    end: datetime
    sales_count: int
    cash_sales: Decimal
    mpesa_sales: Decimal
    credit_sales: Decimal
    cash_refunds: Decimal
    mpesa_refunds: Decimal
    cash_repayments: Decimal
    mpesa_repayments: Decimal
    cash_expenses: Decimal
    opening_float: Decimal = ZERO

    @property
    def expected_cash(self):
        return (self.opening_float + self.cash_sales - self.cash_refunds + self.cash_repayments
                - self.cash_expenses)

    @property
    def expected_mpesa(self):
        return self.mpesa_sales - self.mpesa_refunds + self.mpesa_repayments


def _sum(qs, field="amount"):
    return qs.aggregate(t=Sum(field))["t"] or ZERO


def expected_takings(user, start, end, opening_float=ZERO):
    from apps.finance.models import Expense

    payments = Payment.objects.filter(sale__cashier=user, sale__completed_at__gte=start, sale__completed_at__lt=end,
                                      sale__status__in=[Sale.Status.COMPLETED, Sale.Status.VOIDED])
    refunds = Refund.objects.filter(user=user, created_at__gte=start, created_at__lt=end)
    repayments = CreditEntry.objects.filter(user=user, kind=CreditEntry.Kind.REPAYMENT, method__in=["cash", "mpesa"],
                                            created_at__gte=start, created_at__lt=end)
    expenses = Expense.objects.filter(user=user, method=Expense.Method.CASH, created_at__gte=start, created_at__lt=end)
    sales_count = Sale.objects.filter(cashier=user, status=Sale.Status.COMPLETED, completed_at__gte=start,
                                      completed_at__lt=end).count()
    return ExpectedTakings(
        start=start, end=end, sales_count=sales_count,
        cash_sales=_sum(payments.filter(method=Payment.Method.CASH)),
        mpesa_sales=_sum(payments.filter(method=Payment.Method.MPESA)),
        credit_sales=_sum(payments.filter(method=Payment.Method.CREDIT)),
        cash_refunds=_sum(refunds.filter(method=Refund.Method.CASH), "total"),
        mpesa_refunds=_sum(refunds.filter(method=Refund.Method.MPESA), "total"),
        cash_repayments=_sum(repayments.filter(method="cash")),
        mpesa_repayments=_sum(repayments.filter(method="mpesa")),
        cash_expenses=_sum(expenses),
        opening_float=q2(opening_float),
    )


@transaction.atomic
def save_cashup(user, *, counted_cash, counted_mpesa, opening_float=ZERO, note="", now=None):
    end = now or timezone.now()
    start = cashup_period_start(user, end)
    expected = expected_takings(user, start, end, to_decimal(opening_float, ZERO))
    return CashUp.objects.create(
        cashier=user, period_start=start, period_end=end, opening_float=expected.opening_float,
        expected_cash=q2(expected.expected_cash), counted_cash=q2(to_decimal(counted_cash, ZERO)),
        expected_mpesa=q2(expected.expected_mpesa), counted_mpesa=q2(to_decimal(counted_mpesa, ZERO)), note=note,
    )


# ---------------------------------------------------------------- lookup

def parse_scan(text):
    """'12*6161100110016' -> (12, '6161100110016'); '6161...' -> (None, '6161...')."""
    text = (text or "").strip()
    if "*" in text:
        qty_text, _, code = text.partition("*")
        qty = to_decimal(qty_text)
        if qty is None or qty <= ZERO:
            raise SaleError(f"Can't read the quantity '{qty_text}'.")
        return qty, code.strip()
    return None, text


def find_products(code):
    """Exact barcode first, then name search among active products."""
    if not code:
        return []
    exact = Product.objects.filter(barcode=code, active=True).first()
    if exact:
        return [exact]
    return list(Product.objects.active().filter(Q(name__icontains=code)).order_by("name")[:12])
