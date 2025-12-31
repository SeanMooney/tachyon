# SPDX-License-Identifier: Apache-2.0

"""WSGI entrypoint for the Tachyon API."""

from tachyon.api import app

# WSGI servers (gunicorn/uwsgi) should load this module path:
#   tachyon.wsgi.api:application
application = app.create_app()
