"""The "+ New" option inside dropdowns: create a category, supplier, customer or product without leaving the form.

Each kind names the small form its pop-up shows, who may use it, and how the new record shows in the
dropdown. A GET returns the form's fields as HTML for the pop-up; a POST saves and returns the new record
as JSON, or the fields again with errors. Pages learn which kinds the user may add from `quick_add_kinds`.
"""

from django import forms
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods

from apps.catalog.models import Category, Product, QuickSaleCategory
from apps.finance.models import ExpenseCategory
from apps.partners.models import Customer, Supplier

from .money import ZERO
from .roles import CASHIER, OWNER, STOCK_CLERK, has_role


class NameForm(forms.Form):
    name = forms.CharField(max_length=60)

    model = None

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if self.model.objects.filter(name__iexact=name).exists():
            raise forms.ValidationError(f"'{name}' already exists. Pick it from the list.")
        return name

    def save(self):
        return self.model.objects.create(name=self.cleaned_data["name"])


class CategoryForm(NameForm):
    model = Category


class QuickCategoryForm(NameForm):
    model = QuickSaleCategory

    def save(self):
        last = QuickSaleCategory.objects.order_by("-order").first()
        return QuickSaleCategory.objects.create(name=self.cleaned_data["name"], order=(last.order + 1) if last else 0)


class ExpenseCategoryForm(NameForm):
    model = ExpenseCategory


class SupplierForm(NameForm):
    name = forms.CharField(max_length=120)
    phone = forms.CharField(max_length=50, required=False)
    model = Supplier

    def save(self):
        return Supplier.objects.create(name=self.cleaned_data["name"], phone=self.cleaned_data["phone"])


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ["name", "phone"]


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ["name", "barcode", "sold_by", "selling_price", "cost_price", "category"]

    def clean_barcode(self):
        return (self.cleaned_data.get("barcode") or "").strip() or None

    def clean_selling_price(self):
        price = self.cleaned_data["selling_price"]
        if price <= ZERO:
            raise forms.ValidationError("Selling price must be more than zero.")
        return price


def _product_data(p):
    return {"name": p.name, "unit": p.unit, "price": float(p.selling_price), "tiers": []}


KINDS = {
    "category": {"form": CategoryForm, "role": OWNER},
    "quick_category": {"form": QuickCategoryForm, "role": OWNER},
    "expense_category": {"form": ExpenseCategoryForm, "role": OWNER},
    "supplier": {"form": SupplierForm, "role": STOCK_CLERK},
    "customer": {"form": CustomerForm, "role": CASHIER},
    "product": {"form": ProductForm, "role": OWNER,
                "label": lambda p: f"{p.name} ({p.unit})", "data": _product_data},
}


def allowed_kinds(user):
    return [kind for kind, spec in KINDS.items() if has_role(user, spec["role"])]


def _fields_html(form, status=200):
    return HttpResponse(form.as_div(), status=status)


@require_http_methods(["GET", "POST"])
def quick_add(request, kind):
    spec = KINDS.get(kind)
    if spec is None:
        raise Http404
    if not has_role(request.user, spec["role"]):
        raise PermissionDenied
    if request.method == "GET":
        return _fields_html(spec["form"]())
    form = spec["form"](request.POST)
    if not form.is_valid():
        return _fields_html(form, status=400)
    obj = form.save()
    return JsonResponse({
        "id": obj.pk,
        "label": spec.get("label", str)(obj),
        "data": spec["data"](obj) if "data" in spec else None,
    })
