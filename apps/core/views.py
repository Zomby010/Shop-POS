from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import ShopSettingsForm, UserForm
from .models import AuditLog, ShopSettings, UserProfile
from .roles import ALL_ROLES, OWNER, PRIVILEGES, is_owner, owner_required, user_roles


def dashboard(request):
    from apps.catalog.models import Product
    from apps.sales.models import Payment, Sale

    today = timezone.localdate()
    start = timezone.make_aware(timezone.datetime.combine(today, timezone.datetime.min.time()))
    sales = Sale.objects.filter(status=Sale.Status.COMPLETED, completed_at__gte=start)
    totals = sales.aggregate(total=Sum("total"), count=Count("id"))
    by_method = {
        row["method"]: row["t"]
        for row in Payment.objects.filter(sale__in=sales).values("method").annotate(t=Sum("amount"))
    }
    context = {
        "today_total": totals["total"] or 0,
        "today_count": totals["count"],
        "today_cash": by_method.get("cash", 0),
        "today_mpesa": by_method.get("mpesa", 0),
        "today_credit": by_method.get("credit", 0),
        "low_stock": Product.objects.low_stock().select_related("category")[:15],
        "held_count": Sale.objects.filter(status=Sale.Status.HELD).count(),
    }
    return render(request, "core/dashboard.html", context)


@owner_required
def settings_view(request):
    shop = ShopSettings.load()
    form = ShopSettingsForm(request.POST or None, request.FILES or None, instance=shop)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Settings saved.")
        return redirect("settings")
    groups = [
        ("Business", ["business_name", "logo", "address", "phone", "kra_pin", "receipt_footer"]),
        ("Receipt printer", ["printer_connection", "printer_address", "paper_width_mm"]),
        ("Stock and backups", ["low_stock_default", "backup_folder", "backups_to_keep"]),
    ]
    sections = [(title, [form[name] for name in names]) for title, names in groups]
    return render(request, "core/settings.html", {"form": form, "sections": sections})


@owner_required
def user_list(request):
    from apps.sales.models import Sale
    from apps.sales.services import start_of_day

    User = get_user_model()
    today = Sale.objects.filter(status=Sale.Status.COMPLETED, completed_at__gte=start_of_day())
    users = (User.objects.order_by("username").select_related("profile").prefetch_related("groups")
             .annotate(sales_today=Count("sales", filter=Q(sales__in=today)),
                       takings_today=Sum("sales__total", filter=Q(sales__in=today))))
    rows = [(u, ", ".join(sorted(user_roles(u))) or ("Owner (superuser)" if u.is_superuser else "None")) for u in users]
    return render(request, "core/user_list.html", {"rows": rows})


@owner_required
def roles_view(request):
    return render(request, "core/roles.html", {"privileges": PRIVILEGES, "roles": ALL_ROLES})


@owner_required
def user_edit(request, pk=None):
    User = get_user_model()
    instance = get_object_or_404(User, pk=pk) if pk else None
    initial = {}
    if instance:
        roles = user_roles(instance)
        initial = {
            "username": instance.username,
            "first_name": instance.first_name,
            "email": instance.email,
            "role": next(iter(roles), OWNER if instance.is_superuser else ""),
            "is_active": instance.is_active,
        }
    form = UserForm(request.POST or None, instance=instance, initial=initial)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        UserProfile.objects.get_or_create(user=user)
        messages.success(request, f"Saved {user.username}.")
        return redirect("user_list")
    return render(request, "core/user_form.html", {"form": form, "instance": instance})


@owner_required
def audit_log(request):
    entries = AuditLog.objects.select_related("user", "authorised_by")[:300]
    return render(request, "core/audit_log.html", {"entries": entries})
