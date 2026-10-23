from .models import ShopSettings
from .roles import has_role, is_owner, CASHIER, STOCK_CLERK


def shop(request):
    user = getattr(request, "user", None)
    ctx = {"shop": ShopSettings.load()}
    if user is not None and user.is_authenticated:
        from apps.catalog.models import Product

        ctx.update(
            is_owner=is_owner(user),
            can_sell=has_role(user, CASHIER),
            can_stock=has_role(user, STOCK_CLERK),
            low_stock_count=Product.objects.low_stock().count(),
        )
    return ctx
