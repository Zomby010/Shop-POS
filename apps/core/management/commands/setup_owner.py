"""First-run setup: create the owner's login and PIN if nobody can log in yet."""

import getpass

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from apps.core.roles import OWNER, ensure_groups


class Command(BaseCommand):
    help = "Create the first owner account (asks for a username, password and PIN) if there are no users."

    def handle(self, *args, **options):
        User = get_user_model()
        if User.objects.exists():
            return
        ensure_groups()
        self.stdout.write("Welcome to Shop POS. Let's create the owner's login.")
        username = ""
        while not username:
            username = input("Owner username: ").strip()
        while True:
            password = getpass.getpass("Password (at least 6 characters): ")
            if len(password) >= 6 and password == getpass.getpass("Password again: "):
                break
            self.stdout.write("Passwords must match and be at least 6 characters.")
        while True:
            pin = getpass.getpass("Owner PIN for approving voids and refunds (4 to 8 digits): ")
            if pin.isdigit() and 4 <= len(pin) <= 8:
                break
        user = User.objects.create_user(username=username, password=password, is_staff=True, is_superuser=True)
        user.groups.add(Group.objects.get(name=OWNER))
        user.profile.set_pin(pin)
        user.profile.save()
        self.stdout.write(self.style.SUCCESS(f"Owner '{username}' created. Log in at http://localhost:8000/"))
