"""Load example products (including the rice, beans and oil quick-sale setup) and optional demo users."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog.models import Category, PriceTier, Product, QuickPreset, QuickSaleCategory, StockMovement
from apps.catalog.presets import parse_preset_list
from apps.catalog.stock import record_movement
from apps.core.models import ShopSettings
from apps.core.roles import CASHIER, OWNER, STOCK_CLERK, ensure_groups
from apps.partners.models import Customer, Supplier

W, V, P = Product.SoldBy.WEIGHT, Product.SoldBy.VOLUME, Product.SoldBy.PIECE

# name, barcode, category, sold by, price, cost, stock, quick category, presets, tiers
PRODUCTS = [
    ("Pishori Rice", None, "Rice", W, 200, 170, 50, "Rice", "1/4 kg; 1/2 kg; 1 kg; 2 kg", []),
    ("Basmati Rice", None, "Rice", W, 220, 185, 50, "Rice", "1/4 kg; 1/2 kg; 1 kg", []),
    ("Kamande", None, "Pulses", W, 160, 130, 25, "Rice", "1/2 kg; 1 kg", []),
    ("Rosecoco Beans", None, "Pulses", W, 160, 135, 45, "Beans", "1/4 kg; 1/2 kg; 1 kg", []),
    ("Yellow Beans", None, "Pulses", W, 170, 140, 30, "Beans", "1/4 kg; 1/2 kg; 1 kg", []),
    ("Green Grams (Ndengu)", None, "Pulses", W, 180, 150, 20, "Beans", "1/4 kg; 1/2 kg; 1 kg", []),
    ("Cooking Oil (loose)", None, "Cooking oil", V, 300, 260, 20, "Cooking oil", "KSh 20; KSh 50; KSh 100; 1/2 L; 1 L", []),
    ("Sugar (loose)", None, "Sugar", W, 180, 160, 50, "Sugar", "1/4 kg; 1/2 kg; 1 kg; 2 kg", [(10, 170)]),
    ("Paraffin", None, "Fuel", V, 190, 175, 40, "Other loose", "KSh 50; KSh 100; 1 L", []),
    ("Menengai Bar Soap 800g", "6161100110016", "Cleaning", P, 210, 185, 24, None, "", [(12, 200)]),
    ("Exe Maize Flour 2kg", "6164000250013", "Flour", P, 175, 158, 40, None, "", [(12, 168)]),
    ("Brookside Milk 500ml", "6161101560012", "Dairy", P, 60, 52, 30, None, "", []),
    ("Coca-Cola 500ml", "5449000000996", "Drinks", P, 70, 55, 48, None, "", [(24, 65)]),
    ("Supa Loaf Bread 400g", "6164001234567", "Bakery", P, 65, 57, 15, None, "", []),
    ("Royco Mchuzi Mix 75g", "6001087340014", "Spices", P, 45, 38, 3, None, "", []),
]


class Command(BaseCommand):
    help = "Load example products and quick-sale buttons. Use --users to add demo owner and cashier logins."

    def add_arguments(self, parser):
        parser.add_argument("--users", action="store_true", help="Create owner/owner123 (PIN 1234) and cashier/cashier123")

    @transaction.atomic
    def handle(self, *args, users=False, **options):
        ensure_groups()
        shop = ShopSettings.load()
        if shop.business_name == "My Minimart":
            shop.business_name = "Demo Minimart"
            shop.phone = "0700 000 000"
            shop.save()
        for order, name in enumerate(["Rice", "Beans", "Cooking oil", "Sugar", "Other loose"]):
            QuickSaleCategory.objects.update_or_create(name=name, defaults={"order": order})
        created = 0
        for i, (name, barcode, cat, sold_by, price, cost, stock, quick, presets, tiers) in enumerate(PRODUCTS):
            if Product.objects.filter(name=name).exists():
                continue
            product = Product.objects.create(
                name=name, barcode=barcode, category=Category.objects.get_or_create(name=cat)[0],
                sold_by=sold_by, selling_price=Decimal(price), cost_price=Decimal(cost),
                quick_category=QuickSaleCategory.objects.get(name=quick) if quick else None, quick_order=i,
            )
            for order, (kind, value) in enumerate(parse_preset_list(presets, product.unit)):
                QuickPreset.objects.create(product=product, kind=kind, value=value, order=order)
            for min_qty, tier_price in tiers:
                PriceTier.objects.create(product=product, min_qty=min_qty, unit_price=tier_price)
            record_movement(product, StockMovement.Kind.OPENING, stock, unit_cost=Decimal(cost), reason="Demo data")
            created += 1
        Supplier.objects.get_or_create(name="Mwea Rice Wholesalers", defaults={"phone": "0711 111 111", "contact_person": "Peter"})
        Supplier.objects.get_or_create(name="Bidco Distributor", defaults={"phone": "0722 222 222"})
        Customer.objects.get_or_create(name="Mama Wanjiku", defaults={"phone": "0733 333 333", "credit_limit": Decimal(5000)})
        if users:
            self._user("owner", "owner123", OWNER, pin="1234", first_name="Shop Owner")
            self._user("cashier", "cashier123", CASHIER, first_name="Cashier")
            self._user("stock", "stock123", STOCK_CLERK, first_name="Stock Clerk")
        self.stdout.write(self.style.SUCCESS(f"Demo data loaded ({created} new products)."))

    def _user(self, username, password, role, pin=None, first_name=""):
        User = get_user_model()
        user, made = User.objects.get_or_create(username=username, defaults={"first_name": first_name})
        if made:
            user.set_password(password)
            if role == OWNER:
                user.is_staff = True
                user.is_superuser = True
            user.save()
            user.groups.set([Group.objects.get(name=role)])
            if pin:
                user.profile.set_pin(pin)
                user.profile.save()
            self.stdout.write(f"  user {username} / {password}" + (f" (PIN {pin})" if pin else ""))
