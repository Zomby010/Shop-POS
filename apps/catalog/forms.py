from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory

from apps.core.money import ZERO

from .models import Category, PriceTier, Product, QuickPreset, QuickSaleCategory
from .presets import PresetError, format_preset, parse_preset


class ProductForm(forms.ModelForm):
    opening_stock = forms.DecimalField(
        required=False, min_value=0, decimal_places=3, max_digits=14,
        help_text="New products only. Later changes go through purchases, recounts and stock takes.",
    )

    class Meta:
        model = Product
        fields = [
            "name", "barcode", "category", "sold_by", "selling_price", "cost_price",
            "low_stock_threshold", "reorder_qty", "quick_category", "quick_order", "active",
        ]
        labels = {"quick_category": "Quick-sale category", "quick_order": "Order on quick-sale panel"}
        widgets = {
            "category": forms.Select(attrs={"data-quick-add": "category"}),
            "quick_category": forms.Select(attrs={"data-quick-add": "quick_category"}),
        }

    def __init__(self, *args, can_edit_prices=True, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            del self.fields["opening_stock"]
        if not can_edit_prices:
            for name in ("selling_price", "cost_price"):
                self.fields[name].disabled = True

    def clean_barcode(self):
        barcode = (self.cleaned_data.get("barcode") or "").strip()
        return barcode or None

    def clean(self):
        data = super().clean()
        stock = data.get("opening_stock")
        if stock is not None and data.get("sold_by") == Product.SoldBy.PIECE and stock != stock.to_integral_value():
            self.add_error("opening_stock", "Products sold by the piece need a whole number.")
        if data.get("selling_price") is not None and data["selling_price"] <= ZERO:
            self.add_error("selling_price", "Selling price must be more than zero.")
        return data


class PriceTierForm(forms.ModelForm):
    class Meta:
        model = PriceTier
        fields = ["min_qty", "unit_price"]
        labels = {"min_qty": "From quantity", "unit_price": "Unit price"}


class QuickPresetForm(forms.ModelForm):
    text = forms.CharField(label="Button", max_length=30, help_text="e.g. 1/4 kg, 500 g, 1 L, KSh 50")

    class Meta:
        model = QuickPreset
        fields = ["text", "label", "order", "hidden"]

    def __init__(self, *args, unit="kg", **kwargs):
        super().__init__(*args, **kwargs)
        self.unit = unit
        self.fields["order"].required = False
        if self.instance.pk:
            self.fields["text"].initial = format_preset(self.instance.kind, self.instance.value, unit)

    def clean_text(self):
        try:
            self.parsed = parse_preset(self.cleaned_data["text"], self.unit)
        except PresetError as exc:
            raise forms.ValidationError(str(exc))
        return self.cleaned_data["text"]

    def has_changed(self):
        # An empty extra row with only its default order is still empty.
        return bool(set(self.changed_data) - {"order"})

    def clean_order(self):
        return self.cleaned_data.get("order") or 0

    def save(self, commit=True):
        self.instance.kind, self.instance.value = self.parsed
        return super().save(commit)


class TierFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        seen = set()
        for form in self.forms:
            if not hasattr(form, "cleaned_data") or not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            qty = form.cleaned_data.get("min_qty")
            if qty is None:
                continue
            if qty <= ZERO:
                form.add_error("min_qty", "Must be more than zero.")
            if qty in seen:
                form.add_error("min_qty", "Two tiers start at the same quantity.")
            seen.add(qty)


PriceTierFormSet = inlineformset_factory(
    Product, PriceTier, form=PriceTierForm, formset=TierFormSet, extra=1, can_delete=True
)
QuickPresetFormSet = inlineformset_factory(Product, QuickPreset, form=QuickPresetForm, extra=1, can_delete=True)

QuickSaleCategoryFormSet = forms.modelformset_factory(
    QuickSaleCategory, fields=["name", "order", "active"], extra=1, can_delete=True
)
CategoryFormSet = forms.modelformset_factory(
    Category, fields=["name", "description", "order"], extra=1, can_delete=True,
    widgets={"description": forms.TextInput(attrs={"placeholder": "What goes in this category"})},
)


class ImportForm(forms.Form):
    file = forms.FileField(label="Excel file (.xlsx)")
