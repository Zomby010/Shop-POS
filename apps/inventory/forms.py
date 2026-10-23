from django import forms

from apps.catalog.models import Category, Product
from apps.partners.models import Supplier

from .services import LOSS_REASONS


class ProductChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.name} ({obj.unit})"


class PurchaseForm(forms.Form):
    supplier = forms.ModelChoiceField(Supplier.objects.filter(active=True), required=False,
                                      widget=forms.Select(attrs={"data-quick-add": "supplier"}))
    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    supplier_reference = forms.CharField(required=False, max_length=60, label="Their invoice / delivery no.")
    note = forms.CharField(required=False, max_length=200)


class PurchaseLineForm(forms.Form):
    product = ProductChoiceField(Product.objects.active().order_by("name"),
                                 widget=forms.Select(attrs={"data-quick-add": "product"}))
    packs = forms.DecimalField(min_value=0.001, decimal_places=3, max_digits=12, initial=1, label="Packs")
    pack_size = forms.DecimalField(min_value=0.001, decimal_places=3, max_digits=12, initial=1,
                                   label="Units per pack", help_text="e.g. 50 for a 50 kg sack, 1 for single items")
    pack_cost = forms.DecimalField(min_value=0, decimal_places=2, max_digits=12, label="Cost per pack")

    def has_changed(self):
        # A row with only the default pack numbers filled in is still an empty row.
        return bool(set(self.changed_data) - {"packs", "pack_size"})


PurchaseLineFormSet = forms.formset_factory(PurchaseLineForm, extra=5, min_num=1, validate_min=True)


class LossForm(forms.Form):
    product = ProductChoiceField(Product.objects.active().order_by("name"))
    quantity = forms.DecimalField(min_value=0.001, decimal_places=3, max_digits=12)
    reason = forms.CharField(max_length=40, initial=LOSS_REASONS[0],
                             widget=forms.TextInput(attrs={"list": "loss-reasons", "autocomplete": "off"}),
                             help_text="Pick one or type your own")
    note = forms.CharField(required=False, max_length=150)


class StockTakeStartForm(forms.Form):
    category = forms.ModelChoiceField(Category.objects.all(), required=False,
                                      empty_label="All products", help_text="Count everything, or one category at a time")
    note = forms.CharField(required=False, max_length=200)
