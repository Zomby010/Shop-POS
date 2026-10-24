from django import forms

from .models import Customer, Supplier


class CustomerForm(forms.ModelForm):
    opening_balance = forms.DecimalField(
        min_value=0, decimal_places=2, max_digits=12, required=False,
        help_text="Deni they already owed before using this system. Only asked when adding a customer.",
    )

    class Meta:
        model = Customer
        fields = ["name", "phone", "email", "address", "kra_pin", "credit_limit", "opening_balance", "notes", "active"]
        labels = {"notes": "Reference / notes"}
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            del self.fields["opening_balance"]


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ["name", "contact_person", "phone", "email", "address", "kra_pin", "notes", "active"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}


class RepaymentForm(forms.Form):
    amount = forms.DecimalField(min_value=1, decimal_places=2, max_digits=12)
    method = forms.ChoiceField(choices=[("cash", "Cash"), ("mpesa", "M-Pesa")])
    note = forms.CharField(required=False, max_length=200)
