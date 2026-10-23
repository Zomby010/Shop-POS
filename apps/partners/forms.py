from django import forms

from .models import Customer, Supplier


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ["name", "phone", "email", "address", "credit_limit", "notes", "active"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ["name", "contact_person", "phone", "email", "address", "kra_pin", "notes", "active"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}


class RepaymentForm(forms.Form):
    amount = forms.DecimalField(min_value=1, decimal_places=2, max_digits=12)
    method = forms.ChoiceField(choices=[("cash", "Cash"), ("mpesa", "M-Pesa")])
    note = forms.CharField(required=False, max_length=200)
