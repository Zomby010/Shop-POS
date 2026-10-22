from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.core.roles import STOCK_CLERK, is_owner, owner_required, role_required

from . import excel
from .forms import (
    CategoryFormSet, ImportForm, PriceTierFormSet, ProductForm, QuickPresetFormSet, QuickSaleCategoryFormSet,
)
from .models import Category, Product, StockMovement
from .stock import record_movement

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def product_list(request):
    qs = Product.objects.select_related("category", "quick_category").with_threshold()
    term = request.GET.get("q", "")
    qs = qs.search(term)
    if request.GET.get("category"):
        qs = qs.filter(category_id=request.GET["category"])
    if request.GET.get("low"):
        qs = Product.objects.low_stock().select_related("category", "quick_category")
    if request.GET.get("inactive") != "1":
        qs = qs.filter(active=True)
    page = Paginator(qs.order_by("name"), 50).get_page(request.GET.get("page"))
    return render(request, "catalog/product_list.html", {
        "page": page, "q": term, "categories": Category.objects.all(),
        "selected_category": request.GET.get("category", ""), "low": request.GET.get("low"),
    })


def _unit_for(request, product):
    sold_by = request.POST.get("sold_by") or product.sold_by
    return Product.UNIT_LABELS.get(sold_by, "pcs")


@role_required(STOCK_CLERK)
def product_edit(request, pk=None):
    product = get_object_or_404(Product, pk=pk) if pk else Product()
    owner = is_owner(request.user)
    if pk is None and not owner:
        messages.error(request, "Only the owner can add products.")
        return redirect("catalog:product_list")
    data = request.POST if request.method == "POST" else None
    form = ProductForm(data, instance=product, can_edit_prices=owner,
                       initial={"barcode": request.GET.get("barcode", "")})
    tiers = PriceTierFormSet(data, instance=product, prefix="tiers")
    presets = QuickPresetFormSet(data, instance=product, prefix="presets", form_kwargs={"unit": _unit_for(request, product)})
    if not owner:
        for tier_form in tiers.forms:
            for field in tier_form.fields.values():
                field.disabled = True
    if request.method == "POST" and form.is_valid() and tiers.is_valid() and presets.is_valid():
        with transaction.atomic():
            product = form.save()
            if owner:
                tiers.instance = product
                tiers.save()
            presets.instance = product
            presets.save()
            opening = form.cleaned_data.get("opening_stock")
            if opening:
                record_movement(product, StockMovement.Kind.OPENING, opening, unit_cost=product.cost_price,
                                user=request.user, reason="Opening stock")
        messages.success(request, f"Saved {product.name}.")
        if "add_another" in request.POST:
            return redirect("catalog:product_new")
        return redirect("catalog:product_list")
    movements = product.movements.select_related("user")[:20] if product.pk else []
    return render(request, "catalog/product_form.html", {
        "form": form, "tiers": tiers, "presets": presets, "product": product, "movements": movements,
    })


@owner_required
def quick_categories(request):
    formset = QuickSaleCategoryFormSet(request.POST or None, prefix="qc")
    if request.method == "POST" and formset.is_valid():
        formset.save()
        messages.success(request, "Quick-sale categories saved.")
        return redirect("catalog:quick_categories")
    return render(request, "catalog/simple_formset.html", {
        "formset": formset, "title": "Quick-sale categories",
        "help": "These are the tabs on the sell screen's quick-sale panel. The first eight by order get the keys F1 to F8. "
                "Put a product in a category from its edit page or the Excel sheet.",
    })


@owner_required
def categories(request):
    formset = CategoryFormSet(request.POST or None, prefix="cat")
    if request.method == "POST" and formset.is_valid():
        formset.save()
        messages.success(request, "Categories saved.")
        return redirect("catalog:categories")
    return render(request, "catalog/simple_formset.html", {
        "formset": formset, "title": "Product categories",
        "help": "Categories group products in lists and reports.",
    })


@owner_required
def import_products(request):
    form = ImportForm(request.POST or None, request.FILES or None)
    rows = None
    if request.method == "POST" and "confirm" in request.POST:
        stored = request.session.pop("product_import", None)
        if not stored:
            messages.error(request, "The preview expired. Upload the file again.")
            return redirect("catalog:import")
        created, updated = excel.apply_rows(excel.rows_from_session(stored), request.user)
        messages.success(request, f"Import done: {created} new product{'s' if created != 1 else ''}, {updated} updated.")
        return redirect("catalog:product_list")
    if request.method == "POST" and form.is_valid():
        try:
            rows = excel.parse_workbook(form.cleaned_data["file"])
        except ValueError as exc:
            form.add_error("file", str(exc))
        else:
            request.session["product_import"] = [r.to_session() for r in rows]
    good = sum(1 for r in rows or [] if r.ok)
    return render(request, "catalog/import.html", {
        "form": form, "rows": rows, "good": good, "bad": len(rows or []) - good, "columns": excel.COLUMNS,
    })


@owner_required
def import_template(request):
    response = HttpResponse(excel.build_template(), content_type=XLSX)
    response["Content-Disposition"] = 'attachment; filename="shop-pos-products-template.xlsx"'
    return response


@owner_required
def export_products(request):
    response = HttpResponse(excel.export_products(Product.objects.order_by("name")), content_type=XLSX)
    response["Content-Disposition"] = f'attachment; filename="products-{timezone.localdate():%Y-%m-%d}.xlsx"'
    return response
