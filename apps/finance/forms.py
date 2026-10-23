from django import forms

from .models import Expense


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ["date", "category", "amount", "method", "note"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise forms.ValidationError("Must be more than zero.")
        return amount
