from django.contrib import messages
from django.db import transaction
from django.db.models import DecimalField, F, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.excel import xlsx_response
from apps.core.money import ZERO
from apps.core.roles import CASHIER, STOCK_CLERK, is_owner, owner_required, role_required

from apps.inventory.services import supplier_balance

from .forms import CustomerForm, RepaymentForm, SupplierForm
from .models import CreditEntry, Customer, Supplier, recalculate_balance

MONEY = DecimalField(max_digits=14, decimal_places=2)
BALANCE_FILTERS = [("", "All"), ("owing", "Has balance"), ("overpaid", "Has overpayment"), ("clear", "No balance")]


def _total_spent(customer_ref="pk"):
    """Completed sales to the customer, cash, M-Pesa or deni, less refunds."""
    from apps.sales.models import Refund, Sale

    sold = (Sale.objects.filter(customer=OuterRef(customer_ref), status=Sale.Status.COMPLETED)
            .order_by().values("customer").annotate(t=Sum("total")).values("t"))
    refunded = (Refund.objects.filter(sale__customer=OuterRef(customer_ref), sale__status=Sale.Status.COMPLETED)
                .order_by().values("sale__customer").annotate(t=Sum("total")).values("t"))
    return (Coalesce(Subquery(sold, output_field=MONEY), ZERO, output_field=MONEY)
            - Coalesce(Subquery(refunded, output_field=MONEY), ZERO, output_field=MONEY))


@role_required(CASHIER)
def customer_list(request):
    qs = Customer.objects.annotate(spent=_total_spent())
    term = (request.GET.get("q") or "").strip()
    if term:
        qs = qs.filter(Q(name__icontains=term) | Q(phone__icontains=term) | Q(email__icontains=term))
    balance = request.GET.get("balance") or ("owing" if request.GET.get("owing") else "")
    qs = {"owing": qs.filter(balance__gt=0), "overpaid": qs.filter(balance__lt=0),
          "clear": qs.filter(balance=0)}.get(balance, qs)
    if request.GET.get("format") == "xlsx":
        rows = [[c.name, c.phone, c.email, c.kra_pin, c.balance, c.credit_limit, c.spent,
                 "Active" if c.active else "Inactive"] for c in qs]
        return xlsx_response("customers", "Customers",
                             ["Name", "Phone", "Email", "KRA PIN", "Balance (KSh)", "Credit limit (KSh)",
                              "Total spent (KSh)", "Status"], rows)
    totals = Customer.objects.aggregate(owed=Sum("balance", filter=Q(balance__gt=0)),
                                        overpaid=Sum("balance", filter=Q(balance__lt=0)))
    return render(request, "partners/customer_list.html", {
        "customers": qs, "q": term, "balance": balance, "balance_filters": BALANCE_FILTERS,
        "total_owed": totals["owed"] or 0, "total_overpaid": -(totals["overpaid"] or 0),
    })


@role_required(CASHIER)
def customer_edit(request, pk=None):
    customer = get_object_or_404(Customer, pk=pk) if pk else Customer()
    form = CustomerForm(request.POST or None, instance=customer)
    if not is_owner(request.user):
        form.fields["credit_limit"].disabled = True
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            customer = form.save()
            opening = form.cleaned_data.get("opening_balance")
            if opening:
                CreditEntry.objects.create(customer=customer, kind=CreditEntry.Kind.CHARGE, amount=opening,
                                           note="Opening balance", user=request.user)
                recalculate_balance(customer)
        messages.success(request, f"Saved {customer.name}.")
        return redirect("partners:customer_detail", pk=customer.pk)
    return render(request, "partners/form.html", {"form": form, "title": customer.name or "Add customer",
                                                  "back": "partners:customer_list"})


@role_required(CASHIER)
def customer_detail(request, pk):
    from apps.sales.services import SaleError, record_repayment

    customer = get_object_or_404(Customer, pk=pk)
    form = RepaymentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            record_repayment(customer, form.cleaned_data["amount"], form.cleaned_data["method"],
                             user=request.user, note=form.cleaned_data["note"])
        except SaleError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"Recorded repayment of KSh {form.cleaned_data['amount']:,.2f}.")
            return redirect("partners:customer_detail", pk=customer.pk)
    entries = customer.credit_entries.select_related("sale", "user")[:200]
    spent = Customer.objects.filter(pk=customer.pk).annotate(spent=_total_spent()).values_list("spent", flat=True)[0]
    sales = customer.sales.filter(completed_at__isnull=False).select_related("cashier").order_by("-completed_at")[:20]
    return render(request, "partners/customer_detail.html", {
        "customer": customer, "form": form, "entries": entries, "spent": spent, "sales": sales,
    })


@role_required(STOCK_CLERK)
def supplier_list(request):
    owed = Sum(F("purchases__total") - F("purchases__amount_paid"), filter=Q(purchases__cancelled_at=None))
    qs = Supplier.objects.annotate(owed=owed)
    term = (request.GET.get("q") or "").strip()
    if term:
        qs = qs.filter(Q(name__icontains=term) | Q(contact_person__icontains=term) | Q(phone__icontains=term))
    if request.GET.get("inactive") != "1":
        qs = qs.filter(active=True)
    balance = request.GET.get("balance", "")
    if balance == "owing":
        qs = qs.filter(owed__gt=0)
    elif balance == "clear":
        qs = qs.filter(Q(owed=0) | Q(owed=None))
    if request.GET.get("format") == "xlsx":
        rows = [[s.name, s.contact_person, s.phone, s.email, s.kra_pin, s.owed or 0,
                 "Active" if s.active else "Inactive"] for s in qs]
        return xlsx_response("suppliers", "Suppliers",
                             ["Name", "Contact", "Phone", "Email", "KRA PIN", "We owe (KSh)", "Status"], rows)
    total_owed = sum((s.owed or 0) for s in Supplier.objects.annotate(owed=owed) if (s.owed or 0) > 0)
    return render(request, "partners/supplier_list.html", {
        "suppliers": qs, "q": term, "balance": balance, "total_owed": total_owed,
        "balance_filters": [("", "All"), ("owing", "We owe them"), ("clear", "Nothing owed")],
    })


@owner_required
def supplier_edit(request, pk=None):
    supplier = get_object_or_404(Supplier, pk=pk) if pk else Supplier()
    form = SupplierForm(request.POST or None, instance=supplier)
    if request.method == "POST" and form.is_valid():
        supplier = form.save()
        messages.success(request, f"Saved {supplier.name}.")
        return redirect("partners:supplier_detail", pk=supplier.pk)
    return render(request, "partners/form.html", {"form": form, "title": supplier.name or "Add supplier",
                                                  "back": "partners:supplier_list"})


@role_required(STOCK_CLERK)
def supplier_detail(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    purchases = supplier.purchases.select_related("user").prefetch_related("lines")[:100]
    documents = supplier.documents.all()[:50] if is_owner(request.user) else []
    total = supplier.purchases.filter(cancelled_at=None).aggregate(t=Sum("total"))["t"] or 0
    return render(request, "partners/supplier_detail.html", {
        "supplier": supplier, "purchases": purchases, "documents": documents, "total": total,
        "owed": supplier_balance(supplier),
    })
