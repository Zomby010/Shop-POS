from .models import ShopSettings
from .roles import has_role, is_owner, CASHIER, STOCK_CLERK

# Core pages that sit under People in the top menu
PEOPLE_URLS = ("user_list", "user_edit", "user_new", "roles")


def shop(request):
    user = getattr(request, "user", None)
    ctx = {"shop": ShopSettings.load(), "people_urls": PEOPLE_URLS}
    if user is not None and user.is_authenticated:
        from apps.catalog.models import Product

        from .quick_add import allowed_kinds

        ctx.update(
            is_owner=is_owner(user),
            can_sell=has_role(user, CASHIER),
            can_stock=has_role(user, STOCK_CLERK),
            low_stock_count=Product.objects.low_stock().count(),
            quick_add_kinds=" ".join(allowed_kinds(user)),
        )
    return ctx
