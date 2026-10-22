from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.catalog.models import PriceTier, Product, StockMovement
from apps.core.models import AuditLog
from apps.partners.models import CreditEntry, Customer
from apps.sales import services
from apps.sales.models import Payment, Refund, Sale
from apps.sales.services import SaleError


@pytest.fixture
def cart(cashier):
    return services.current_cart(cashier)


@pytest.mark.django_db
def test_current_cart_is_reused(cashier):
    assert services.current_cart(cashier) == services.current_cart(cashier)


@pytest.mark.django_db
def test_scanning_same_item_merges_and_applies_tier(cart, soap):
    PriceTier.objects.create(product=soap, min_qty=12, unit_price=200)
    services.add_to_cart(cart, soap)
    line = services.add_to_cart(cart, soap, quantity=Decimal(11))
    assert cart.lines.count() == 1
    assert line.quantity == Decimal("12.000") and line.unit_price == Decimal("200") and line.tier_applied
    cart.refresh_from_db()
    assert cart.total == Decimal("2400.00")


@pytest.mark.django_db
def test_loose_lines_by_quantity_and_amount(cart, rice, oil):
    services.add_to_cart(cart, rice, quantity=Decimal("0.25"))
    services.add_to_cart(cart, rice, quantity=Decimal("0.5"))
    oil_line = services.add_to_cart(cart, oil, amount=Decimal("50"))
    assert cart.lines.count() == 3  # loose scoops stay separate lines
    assert oil_line.quantity == Decimal("0.167") and oil_line.line_total == Decimal("50.00")
    cart.refresh_from_db()
    assert cart.total == Decimal("200.00")  # 50 + 100 + 50


@pytest.mark.django_db
def test_piece_quantity_must_be_whole(cart, soap):
    with pytest.raises(SaleError):
        services.add_to_cart(cart, soap, quantity=Decimal("1.5"))


@pytest.mark.django_db
def test_lowering_a_line_needs_owner(cart, soap, cashier, owner):
    line = services.add_to_cart(cart, soap, quantity=Decimal(3))
    services.change_line_quantity(line, Decimal(5), user=cashier)  # raising is fine
    with pytest.raises(SaleError):
        services.change_line_quantity(line, Decimal(2), user=cashier)
    services.change_line_quantity(line, Decimal(0), user=cashier, approver=owner, reason="Mis-scan")
    assert cart.lines.count() == 0
    log = AuditLog.objects.get(action="void line")
    assert log.authorised_by == owner and log.user == cashier


@pytest.mark.django_db
def test_hold_and_resume(cashier, soap, rice):
    cart = services.current_cart(cashier)
    services.add_to_cart(cart, soap)
    services.hold_cart(cart, "Mama Wanjiku")
    soap.refresh_from_db()
    assert soap.stock_qty == Decimal("24.000")  # held carts don't touch stock
    new_cart = services.current_cart(cashier)
    assert new_cart != cart and new_cart.status == Sale.Status.OPEN
    services.add_to_cart(new_cart, rice, quantity=Decimal(1))
    services.resume_cart(cart, cashier)
    cart.refresh_from_db()
    new_cart.refresh_from_db()
    assert cart.status == Sale.Status.OPEN
    assert new_cart.status == Sale.Status.HELD  # the busy cart was parked, not lost


@pytest.mark.django_db
def test_hold_empty_cart_fails(cart):
    with pytest.raises(SaleError):
        services.hold_cart(cart)


@pytest.mark.parametrize("kwargs,expected", [
    ({}, ("1000.00", "0.00", "0.00", "1000.00", "0.00")),
    ({"cash_tendered": "1500"}, ("1000.00", "0.00", "0.00", "1500.00", "500.00")),
    ({"mpesa": "1000"}, ("0.00", "1000.00", "0.00", "0.00", "0.00")),
    ({"mpesa": "600", "cash_tendered": "500"}, ("400.00", "600.00", "0.00", "500.00", "100.00")),
    ({"mpesa": "300", "credit": "700"}, ("0.00", "300.00", "700.00", "0.00", "0.00")),
])
def test_plan_payment(kwargs, expected):
    plan = services.plan_payment(Decimal("1000.00"), **kwargs)
    assert (plan.cash, plan.mpesa, plan.credit, plan.tendered, plan.change) == tuple(Decimal(x) for x in expected)


@pytest.mark.parametrize("kwargs", [{"cash_tendered": "900"}, {"mpesa": "1200"}, {"mpesa": "600", "credit": "500"},
                                    {"mpesa": "-5"}])
def test_plan_payment_rejects(kwargs):
    with pytest.raises(SaleError):
        services.plan_payment(Decimal("1000.00"), **kwargs)


@pytest.mark.django_db
def test_complete_sale_moves_stock_and_records_payments(cart, cashier, rice, soap):
    services.add_to_cart(cart, rice, quantity=Decimal("0.25"))
    services.add_to_cart(cart, soap, quantity=Decimal(2))
    sale = services.complete_sale(cart, user=cashier, cash_tendered="500", mpesa="100")
    assert sale.receipt_no == "R000001" and sale.status == Sale.Status.COMPLETED
    assert sale.total == Decimal("470.00")
    assert sale.paid_by(Payment.Method.CASH) == Decimal("370.00")
    assert sale.paid_by(Payment.Method.MPESA) == Decimal("100.00")
    assert sale.change_given == Decimal("130.00")
    assert sale.cost_total == Decimal("412.50")  # 0.25*170 + 2*185
    rice.refresh_from_db()
    soap.refresh_from_db()
    assert rice.stock_qty == Decimal("49.750") and soap.stock_qty == Decimal("22.000")
    assert StockMovement.objects.filter(kind="sale", reference="R000001").count() == 2
    assert services.current_cart(cashier) != sale


@pytest.mark.django_db
def test_receipt_numbers_are_sequential(cashier, soap):
    numbers = []
    for _ in range(3):
        cart = services.current_cart(cashier)
        services.add_to_cart(cart, soap)
        numbers.append(services.complete_sale(cart, user=cashier).number)
    assert numbers == [1, 2, 3]


@pytest.mark.django_db
def test_deni_sale_and_credit_limit(cart, cashier, soap):
    customer = Customer.objects.create(name="Mama Wanjiku", credit_limit=Decimal("500"))
    services.add_to_cart(cart, soap, quantity=Decimal(3))  # 630
    with pytest.raises(SaleError):
        services.complete_sale(cart, user=cashier, credit="630", customer=customer)
    with pytest.raises(SaleError):
        services.complete_sale(cart, user=cashier, credit="400")  # no customer
    sale = services.complete_sale(cart, user=cashier, credit="400", mpesa="230", customer=customer)
    customer.refresh_from_db()
    assert customer.balance == Decimal("400.00")
    assert sale.customer == customer
    services.record_repayment(customer, "150", "mpesa", user=cashier)
    customer.refresh_from_db()
    assert customer.balance == Decimal("250.00")


@pytest.mark.django_db
def test_empty_cart_cannot_complete(cart, cashier):
    with pytest.raises(SaleError):
        services.complete_sale(cart, user=cashier)


@pytest.mark.django_db
def test_partial_refund_returns_stock(cart, cashier, owner, soap):
    services.add_to_cart(cart, soap, quantity=Decimal(3))
    sale = services.complete_sale(cart, user=cashier)
    line = sale.lines.get()
    with pytest.raises(SaleError):
        services.refund_lines(sale, {line.pk: "1"}, user=cashier, approver=None, reason="Damaged")
    refund = services.refund_lines(sale, {line.pk: "1"}, user=cashier, approver=owner, reason="Damaged")
    assert refund.total == Decimal("210.00")
    soap.refresh_from_db()
    assert soap.stock_qty == Decimal("22.000")
    with pytest.raises(SaleError):
        services.refund_lines(sale, {line.pk: "3"}, user=cashier, approver=owner, reason="Too many")
    assert AuditLog.objects.filter(action="refund").count() == 1


@pytest.mark.django_db
def test_void_sale_reverses_everything(cart, cashier, owner, soap):
    customer = Customer.objects.create(name="Otieno")
    services.add_to_cart(cart, soap, quantity=Decimal(2))  # 420
    sale = services.complete_sale(cart, user=cashier, cash_tendered="200", credit="220", customer=customer)
    services.void_sale(sale, user=cashier, approver=owner, reason="Customer changed mind")
    sale.refresh_from_db()
    soap.refresh_from_db()
    customer.refresh_from_db()
    assert sale.status == Sale.Status.VOIDED
    assert soap.stock_qty == Decimal("24.000")
    assert customer.balance == Decimal("0.00")
    assert {(r.method, r.total) for r in sale.refunds.all()} == {("cash", Decimal("200.00")), ("credit", Decimal("220.00"))}
    with pytest.raises(SaleError):
        services.void_sale(sale, user=cashier, approver=owner, reason="again")


@pytest.mark.django_db
def test_cashup_expected_amounts(cashier, owner, soap):
    from apps.finance.models import Expense

    start = timezone.now() - timedelta(seconds=1)
    for kwargs in ({}, {"mpesa": "210"}, {"cash_tendered": "100", "mpesa": "110"}):
        cart = services.current_cart(cashier)
        services.add_to_cart(cart, soap)
        services.complete_sale(cart, user=cashier, **kwargs)
    last = Sale.objects.order_by("-number").first()
    services.refund_lines(last, {last.lines.get().pk: 1}, user=cashier, approver=owner, reason="x", method="cash")
    customer = Customer.objects.create(name="A")
    services.record_repayment(customer, "50", "cash", user=cashier)
    Expense.objects.create(category="transport", amount=Decimal("30"), method="cash", user=cashier)
    record = services.save_cashup(cashier, counted_cash="320", counted_mpesa="320", opening_float="1000")
    # cash: 1000 float + 210 + 100 - 210 refund + 50 repaid - 30 expense = 1120
    assert record.expected_cash == Decimal("1120.00")
    assert record.expected_mpesa == Decimal("320.00")
    assert record.cash_difference == Decimal("-800.00")
    assert record.period_start >= start - timedelta(days=1)
    # The next cash-up starts where this one ended
    assert services.cashup_period_start(cashier) == record.period_end


def test_parse_scan():
    assert services.parse_scan("12*6161") == (Decimal("12"), "6161")
    assert services.parse_scan(" 6161 ") == (None, "6161")
    with pytest.raises(SaleError):
        services.parse_scan("x*6161")
