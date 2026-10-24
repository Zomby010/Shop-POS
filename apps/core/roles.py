"""Role helpers. Roles are Django groups; superusers count as owners."""

from functools import wraps

from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied

OWNER = "Owner"
CASHIER = "Cashier"
STOCK_CLERK = "Stock clerk"
ALL_ROLES = [OWNER, CASHIER, STOCK_CLERK]


def ensure_groups():
    for name in ALL_ROLES:
        Group.objects.get_or_create(name=name)


def user_roles(user):
    if not user.is_authenticated:
        return set()
    if not hasattr(user, "_role_cache"):
        user._role_cache = set(user.groups.values_list("name", flat=True))
    return user._role_cache


def is_owner(user):
    return user.is_authenticated and (user.is_superuser or OWNER in user_roles(user))


def has_role(user, *roles):
    """Owners pass every role check."""
    return is_owner(user) or bool(user_roles(user) & set(roles))


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not has_role(request.user, *roles):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


owner_required = role_required(OWNER)


# What each role can do, as the views enforce it. Shown on People → Roles and privileges.
# Each row is (privilege, owner, cashier, stock clerk); "PIN" means the owner's PIN must be typed.
YES, NO, PIN, OWN, VIEW = "yes", "no", "pin", "own", "view"
PRIVILEGES = [
    ("Selling", [
        ("Sell, hold and resume sales", YES, YES, NO),
        ("Lower or remove a line in the cart", YES, PIN, NO),
        ("View sales", YES, OWN, NO),
        ("Void a sale or give a refund", YES, PIN, NO),
        ("Do a cash-up", YES, OWN, NO),
        ("See all cash-ups", YES, NO, NO),
    ]),
    ("Customers", [
        ("View, add and edit customers", YES, YES, NO),
        ("Sell on deni (within the credit limit)", YES, YES, NO),
        ("Record deni repayments", YES, YES, NO),
        ("Set a customer's credit limit", YES, NO, NO),
    ]),
    ("Invoices and quotations", [
        ("Create, edit and send invoices and quotations", YES, NO, NO),
    ]),
    ("Products and prices", [
        ("View products and selling prices", YES, YES, YES),
        ("See buying prices (cost)", YES, NO, VIEW),
        ("Edit product details, presets and alert levels", YES, NO, YES),
        ("Add products, import from Excel", YES, NO, NO),
        ("Change buying and selling prices, bulk tiers", YES, NO, NO),
        ("Manage categories and quick-sale categories", YES, NO, NO),
    ]),
    ("Stock", [
        ("Receive stock (purchases)", YES, NO, YES),
        ("Recount, convert and record losses", YES, NO, YES),
        ("Start and count stock takes", YES, NO, YES),
        ("Approve a stock take", YES, NO, NO),
        ("Cancel a purchase", YES, NO, NO),
        ("Low stock and movement history", YES, NO, YES),
    ]),
    ("Suppliers", [
        ("View suppliers and what you owe them", YES, NO, YES),
        ("Pay a supplier", YES, NO, YES),
        ("Add and edit suppliers", YES, NO, NO),
    ]),
    ("Reports and money", [
        ("Reports, profit and loss, expenses", YES, NO, NO),
        ("Loose-goods loss report", YES, NO, NO),
    ]),
    ("Users and settings", [
        ("Add, edit and disable users; set PINs", YES, NO, NO),
        ("Shop settings, printer and backups", YES, NO, NO),
        ("Audit log", YES, NO, NO),
    ]),
]
