from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from .models import ShopSettings
from .roles import ALL_ROLES


class ShopSettingsForm(forms.ModelForm):
    class Meta:
        model = ShopSettings
        fields = [
            "business_name", "logo", "address", "phone", "kra_pin", "receipt_footer",
            "printer_connection", "printer_address", "paper_width_mm",
            "low_stock_default", "backup_folder", "backups_to_keep",
        ]


class UserForm(forms.Form):
    username = forms.CharField(max_length=150)
    first_name = forms.CharField(max_length=150, required=False, label="Name")
    role = forms.ChoiceField(choices=[(r, r) for r in ALL_ROLES])
    password = forms.CharField(
        widget=forms.PasswordInput, required=False, min_length=6,
        help_text="At least 6 characters. Leave blank to keep the current password.",
    )
    pin = forms.RegexField(
        regex=r"^\d{4,8}$", required=False, label="Owner PIN",
        widget=forms.PasswordInput, help_text="4 to 8 digits. Owners use it to approve voids and refunds.",
    )
    is_active = forms.BooleanField(required=False, initial=True, label="Can log in")

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        super().__init__(*args, **kwargs)
        if instance is None:
            self.fields["password"].required = True
            self.fields["password"].help_text = "At least 6 characters."

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        qs = get_user_model().objects.filter(username__iexact=username)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("That username is taken.")
        return username

    def save(self):
        User = get_user_model()
        user = self.instance or User()
        data = self.cleaned_data
        user.username = data["username"]
        user.first_name = data["first_name"]
        user.is_active = data["is_active"]
        if data["password"]:
            user.set_password(data["password"])
        user.save()
        user.groups.set([Group.objects.get_or_create(name=data["role"])[0]])
        if data["pin"]:
            user.profile.set_pin(data["pin"])
            user.profile.save()
        return user
