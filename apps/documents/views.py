from datetime import timedelta

from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.catalog.models import Product
from apps.core.roles import owner_required

from . import services
from .forms import DocumentForm, DocumentLineFormSet, PaymentForm
from .models import Document
from .pdf import render_document


@owner_required
def document_list(request):
    qs = Document.objects.select_related("customer", "supplier")
    kind = request.GET.get("kind", "")
    if kind:
        qs = qs.filter(kind=kind)
    term = (request.GET.get("q") or "").strip()
    if term:
        qs = qs.filter(Q(party_name__icontains=term) | Q(customer__name__icontains=term) | Q(supplier__name__icontains=term))
    return render(request, "documents/list.html", {"documents": qs[:300], "kind": kind, "q": term})


@owner_required
def document_edit(request, pk=None):
    document = get_object_or_404(Document, pk=pk) if pk else None
    if document is None:
        kind = request.GET.get("kind", Document.Kind.INVOICE)
        initial = {
            "kind": kind, "party_type": request.GET.get("party_type", Document.PartyType.CUSTOMER),
            "customer": request.GET.get("customer"), "supplier": request.GET.get("supplier"),
            "date": timezone.localdate(),
            "valid_until": timezone.localdate() + timedelta(days=14) if kind == Document.Kind.QUOTATION else None,
        }
        form = DocumentForm(request.POST or None, initial=initial)
        instance = Document(kind=kind)
    else:
        form = DocumentForm(request.POST or None, instance=document)
        instance = document
    bulk = request.POST.get("is_bulk") == "on" if request.method == "POST" else instance.is_bulk
    formset = DocumentLineFormSet(request.POST or None, instance=instance, prefix="lines", form_kwargs={"bulk": bulk})
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            doc = form.save(commit=False)
            if doc.pk is None:
                doc.number = services.next_number(doc.kind)
                doc.created_by = request.user
            doc.save()
            formset.instance = doc
            formset.save()
        messages.success(request, f"{doc.code} saved.")
        return redirect("documents:detail", pk=doc.pk)
    products = Product.objects.active().order_by("name").prefetch_related("tiers")
    return render(request, "documents/form.html", {
        "form": form, "formset": formset, "document": document, "products": products,
    })


@owner_required
def document_detail(request, pk):
    document = get_object_or_404(Document.objects.select_related("customer", "supplier"), pk=pk)
    payment_form = PaymentForm(request.POST or None)
    if request.method == "POST" and payment_form.is_valid():
        try:
            services.record_payment(document, payment_form.cleaned_data["amount"])
        except services.DocumentError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Payment recorded.")
        return redirect("documents:detail", pk=pk)
    return render(request, "documents/detail.html", {
        "document": document, "lines": document.lines.all(), "payment_form": payment_form,
    })


@owner_required
def document_pdf(request, pk):
    document = get_object_or_404(Document, pk=pk)
    response = HttpResponse(render_document(document), content_type="application/pdf")
    disposition = "attachment" if request.GET.get("download") else "inline"
    response["Content-Disposition"] = f'{disposition}; filename="{document.code}.pdf"'
    return response


@owner_required
@require_POST
def convert(request, pk):
    quotation = get_object_or_404(Document, pk=pk)
    try:
        invoice = services.convert_to_invoice(quotation, user=request.user)
    except services.DocumentError as exc:
        messages.error(request, str(exc))
        return redirect("documents:detail", pk=pk)
    messages.success(request, f"Created {invoice.code} from {quotation.code}.")
    return redirect("documents:detail", pk=invoice.pk)


@owner_required
@require_POST
def set_status(request, pk):
    document = get_object_or_404(Document, pk=pk)
    status = request.POST.get("status")
    if status in Document.Status.values:
        document.status = status
        document.save(update_fields=["status"])
    return redirect("documents:detail", pk=pk)
