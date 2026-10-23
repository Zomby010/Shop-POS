"""Run Shop POS for the shop: a production web server on this laptop only.

start_pos.bat runs this. For development use `python manage.py runserver` instead.
"""

import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "shoppos.settings")
os.environ.setdefault("SHOPPOS_DEBUG", "0")

HOST = os.environ.get("SHOPPOS_HOST", "127.0.0.1")
PORT = int(os.environ.get("SHOPPOS_PORT", "8000"))


def main():
    from waitress import serve

    from shoppos.wsgi import application

    print(f"Shop POS is running at http://localhost:{PORT}/")
    print("Keep this window open while the shop is using the POS. Close it to stop.")
    serve(application, host=HOST, port=PORT, threads=8)


if __name__ == "__main__":
    sys.exit(main())
