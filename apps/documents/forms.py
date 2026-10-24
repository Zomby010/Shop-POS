from django import forms

from apps.catalog.models import Product
from apps.core.money import ZERO
from apps.partners.models import Customer, Supplier

from .models import Document, DocumentLine
from .services import line_amount, suggested_price


class DocumentForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = [
            "kind", "party_type", "customer", "supplier", "party_name", "party_details", "date", "valid_until",
            "due_date", "is_bulk", "discount", "status", "notes",
        ]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "valid_until": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "due_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "notes": forms.Textarea(attrs={"rows": 3, "placeholder": "Payment details, delivery terms..."}),
            "customer": forms.Select(attrs={"data-quick-add": "customer"}),
            "supplier": forms.Select(attrs={"data-quick-add": "supplier"}),
        }
        labels = {"is_bulk": "Bulk order (use bulk tier prices)", "party_name": "One-off name",
                  "party_details": "One-off contact details"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.filter(active=True)
        self.fields["supplier"].queryset = Supplier.objects.filter(active=True)
        if self.instance.pk:
            self.fields["kind"].disabled = True

    def clean(self):
        data = super().clean()
        party_type = data.get("party_type")
        if party_type == Document.PartyType.CUSTOMER and not data.get("customer"):
            self.add_error("customer", "Choose the customer.")
        if party_type == Document.PartyType.SUPPLIER and not data.get("supplier"):
            self.add_error("supplier", "Choose the supplier.")
        if party_type == Document.PartyType.OTHER and not data.get("party_name"):
            self.add_error("party_name", "Type who this is for.")
        if party_type != Document.PartyType.CUSTOMER:
            data["customer"] = None
        if party_type != Document.PartyType.SUPPLIER:
            data["supplier"] = None
        if data.get("discount") is not None and data["discount"] < ZERO:
            self.add_error("discount", "Discount can't be negative.")
        return data


class DocumentLineForm(forms.ModelForm):
    product = forms.ModelChoiceField(Product.objects.active().order_by("name"), required=False,
                                     widget=forms.Select(attrs={"data-quick-add": "product"}))
    description = forms.CharField(max_length=200, required=False)
    unit_price = forms.DecimalField(max_digits=12, decimal_places=2, required=False,
                                    help_text="Blank uses the product's price")

    class Meta:
        model = DocumentLine
        fields = ["product", "description", "quantity", "unit", "unit_price"]

    def __init__(self, *args, bulk=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.bulk = bulk
        self.fields["unit"].required = False

    def clean(self):
        data = super().clean()
        product, qty = data.get("product"), data.get("quantity")
        if not product and not data.get("description"):
            self.add_error("description", "Choose a product or type a description.")
        if qty is not None and qty <= ZERO:
            self.add_error("quantity", "Must be more than zero.")
        if product:
            data["description"] = data.get("description") or product.name
            data["unit"] = data.get("unit") or product.unit
            if data.get("unit_price") is None and qty:
                data["unit_price"] = suggested_price(product, qty, self.bulk)
        if data.get("unit_price") is None:
            self.add_error("unit_price", "Enter a price.")
        return data

    def save(self, commit=True):
        line = super().save(commit=False)
        line.description = self.cleaned_data["description"]
        line.unit = self.cleaned_data.get("unit") or ""
        line.unit_price = self.cleaned_data["unit_price"]
        line.line_total = line_amount(line.quantity, line.unit_price)
        if commit:
            line.save()
        return line


DocumentLineFormSet = forms.inlineformset_factory(
    Document, DocumentLine, form=DocumentLineForm, extra=4, can_delete=True, min_num=1, validate_min=True
)


class PaymentForm(forms.Form):
    amount = forms.DecimalField(min_value=0.01, max_digits=12, decimal_places=2)
