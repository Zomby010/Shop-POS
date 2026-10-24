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
    from waitress import create_server

    from shoppos.wsgi import application

    try:
        server = create_server(application, host=HOST, port=PORT, threads=8)
    except OSError as exc:
        print(f"Port {PORT} is already used by another program ({exc}).")
        print("Put a free port number such as 8001 in a file called port.txt next to start_pos.bat, then start again.")
        return 1
    print(f"Shop POS is running at http://localhost:{PORT}/")
    print("Keep this window open while the shop is using the POS. Close it to stop.")
    server.run()

if __name__ == "__main__":
    sys.exit(main())
