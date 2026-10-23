from django.core.management.base import BaseCommand

from apps.core.backup import backup_due, create_backup


class Command(BaseCommand):
    help = "Back up the database and logo to the backup folder in Settings."

    def add_arguments(self, parser):
        parser.add_argument("--if-due", action="store_true", help="Only back up if this evening's backup is missing")

    def handle(self, *args, if_due=False, **options):
        if if_due and not backup_due():
            self.stdout.write("Backup not due.")
            return
        path = create_backup()
        self.stdout.write(self.style.SUCCESS(f"Backup saved to {path}"))
