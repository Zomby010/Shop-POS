"""Zip backups of the SQLite database and uploaded files (logo), kept in a folder of the owner's choice."""

import logging
import sqlite3
import tempfile
import threading
import time as _time
import zipfile
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.utils import timezone

log = logging.getLogger(__name__)
PREFIX = "shoppos-backup-"
DAILY_BACKUP_HOUR = 18  # backups made from 18:00 count as "this evening's"


def backup_folder(shop=None):
    from .models import ShopSettings

    shop = shop or ShopSettings.load()
    folder = Path(shop.backup_folder) if shop.backup_folder else Path(settings.DATA_DIR) / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def list_backups(folder=None):
    folder = folder or backup_folder()
    return sorted(folder.glob(f"{PREFIX}*.zip"), reverse=True)


def create_backup(folder=None, keep=None):
    """Make a consistent copy of the database with SQLite's backup API, zip it with media, prune old ones."""
    from .models import ShopSettings

    shop = ShopSettings.load()
    folder = Path(folder) if folder else backup_folder(shop)
    folder.mkdir(parents=True, exist_ok=True)
    keep = keep or shop.backups_to_keep
    stamp = timezone.localtime().strftime("%Y-%m-%d-%H%M%S")
    target = folder / f"{PREFIX}{stamp}.zip"
    db_path = settings.DATABASES["default"]["NAME"]
    with tempfile.TemporaryDirectory() as tmp:
        copy_path = Path(tmp) / "shoppos.sqlite3"
        if connection.vendor == "sqlite" and str(db_path) != ":memory:" and "memory" not in str(db_path):
            source = sqlite3.connect(str(db_path))
        else:  # tests use an in-memory database
            connection.ensure_connection()
            source = connection.connection
        dest = sqlite3.connect(copy_path)
        with dest:
            source.backup(dest)
        dest.close()
        if source is not connection.connection:
            source.close()
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(copy_path, "shoppos.sqlite3")
            media = Path(settings.MEDIA_ROOT)
            if media.exists():
                for path in media.rglob("*"):
                    if path.is_file():
                        archive.write(path, Path("media") / path.relative_to(media))
    for old in list_backups(folder)[keep:]:
        old.unlink(missing_ok=True)
    return target


def backup_due(now=None, folder=None):
    """True after 18:00 when there is no backup from this evening yet."""
    now = timezone.localtime(now)
    if now.hour < DAILY_BACKUP_HOUR:
        return False
    tonight = now.strftime("%Y-%m-%d")
    for path in list_backups(folder):
        stamp = path.stem[len(PREFIX):]
        try:
            made = datetime.strptime(stamp, "%Y-%m-%d-%H%M%S")
        except ValueError:
            continue
        if stamp.startswith(tonight) and made.hour >= DAILY_BACKUP_HOUR:
            return False
    return True


_last_check = 0.0
_lock = threading.Lock()


def maybe_run_daily_backup():
    """Called on requests; checks at most every 10 minutes and backs up in a thread when due."""
    global _last_check
    if _time.monotonic() - _last_check < 600:
        return
    with _lock:
        if _time.monotonic() - _last_check < 600:
            return
        _last_check = _time.monotonic()
    try:
        if backup_due():
            threading.Thread(target=_safe_backup, daemon=True).start()
    except Exception:
        log.exception("Daily backup check failed")


def _safe_backup():
    try:
        create_backup()
    except Exception:
        log.exception("Daily backup failed")
