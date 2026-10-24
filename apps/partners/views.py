from django.contrib import messages
from django.db.models import F, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.roles import CASHIER, STOCK_CLERK, is_owner, owner_required, role_required

from apps.inventory.services import supplier_balance

from .forms import CustomerForm, RepaymentForm, SupplierForm
from .models import Customer, Supplier


@role_required(CASHIER)
def customer_list(request):
    qs = Customer.objects.all()
    term = (request.GET.get("q") or "").strip()
    if term:
        qs = qs.filter(Q(name__icontains=term) | Q(phone__icontains=term))
    if request.GET.get("owing"):
        qs = qs.filter(balance__gt=0)
    total_owed = Customer.objects.filter(balance__gt=0).aggregate(t=Sum("balance"))["t"] or 0
    return render(request, "partners/customer_list.html", {"customers": qs, "q": term, "total_owed": total_owed})


@role_required(CASHIER)
def customer_edit(request, pk=None):
    customer = get_object_or_404(Customer, pk=pk) if pk else Customer()
    form = CustomerForm(request.POST or None, instance=customer)
    if not is_owner(request.user):
        form.fields["credit_limit"].disabled = True
    if request.method == "POST" and form.is_valid():
        customer = form.save()
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
    return render(request, "partners/customer_detail.html", {"customer": customer, "form": form, "entries": entries})


@role_required(STOCK_CLERK)
def supplier_list(request):
    owed = Sum(F("purchases__total") - F("purchases__amount_paid"), filter=Q(purchases__cancelled_at=None))
    qs = Supplier.objects.annotate(owed=owed)
    term = (request.GET.get("q") or "").strip()
    if term:
        qs = qs.filter(Q(name__icontains=term) | Q(contact_person__icontains=term) | Q(phone__icontains=term))
    if request.GET.get("inactive") != "1":
        qs = qs.filter(active=True)
    return render(request, "partners/supplier_list.html", {"suppliers": qs, "q": term})


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
