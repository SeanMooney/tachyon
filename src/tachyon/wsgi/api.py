"""WSGI entrypoint for the Tachyon API."""

from tachyon.api import create_app

# WSGI servers (gunicorn/uwsgi) should load this module path:
#   tachyon.wsgi.api:application
application = create_app()
