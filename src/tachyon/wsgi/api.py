# SPDX-License-Identifier: Apache-2.0

"""WSGI entrypoint for the Tachyon API.

Assembles the middleware pipeline including authentication and creates
the final WSGI application.
"""

from __future__ import annotations

import os
import sys
from typing import Any
from typing import Callable

from oslo_config import cfg
from oslo_log import log as logging
from oslo_middleware import request_id

from tachyon import auth
from tachyon import conf  # noqa: F401 - registers config options
from tachyon import policy
from tachyon.api import app

CONF = cfg.CONF
LOG = logging.getLogger(__name__)

# Type aliases for WSGI
WSGIEnviron = dict[str, Any]
StartResponse = Callable[[str, list[tuple[str, str]]], Callable[[bytes], None]]
WSGIApp = Callable[[WSGIEnviron, StartResponse], list[bytes]]

# Default config file locations
CONFIG_FILES = [
    "/etc/tachyon/tachyon.conf",
    os.path.expanduser("~/.tachyon/tachyon.conf"),
]


def _find_config_files() -> list[str]:
    """Find available configuration files.

    :returns: List of existing config file paths
    """
    return [f for f in CONFIG_FILES if os.path.exists(f)]


def deploy(conf_obj: cfg.ConfigOpts) -> WSGIApp:
    """Assemble the middleware pipeline leading to the Tachyon app.

    :param conf_obj: Configuration options
    :returns: WSGI application with middleware pipeline
    """
    # Build Flask config from oslo.config
    flask_config = {
        "AUTH_STRATEGY": conf_obj.api.auth_strategy,
        "MAX_LIMIT": conf_obj.api.max_limit,
        "NEO4J_URI": conf_obj.neo4j.uri,
        "NEO4J_USERNAME": conf_obj.neo4j.username,
        "NEO4J_PASSWORD": conf_obj.neo4j.password,
    }

    LOG.debug(
        "Flask config: AUTH_STRATEGY=%s, NEO4J_URI=%s",
        flask_config["AUTH_STRATEGY"],
        flask_config["NEO4J_URI"],
    )

    # Create the Flask application
    flask_app = app.create_app(config=flask_config)

    # The Flask app is already a WSGI app
    application: WSGIApp = flask_app.wsgi_app

    # Select auth middleware based on configuration
    if conf_obj.api.auth_strategy == "noauth2":
        LOG.info("Using noauth2 authentication (development mode)")
        auth_middleware: type = auth.NoAuthMiddleware
    else:
        LOG.info("Using Keystone authentication")
        # For Keystone auth, we use the filter factory pattern
        # The keystonemiddleware reads config from [keystone_authtoken] section
        auth_middleware = auth.filter_factory(
            {}, oslo_config_config=conf_obj
        )

    # Context middleware creates RequestContext from Keystone headers
    context_middleware = auth.TachyonKeystoneContext

    # Request ID middleware for tracing
    request_id_middleware = request_id.RequestId

    # Build the middleware pipeline
    # Order is important - the list is from inside out:
    # 1. request_id_middleware - adds request ID (outermost, first to run)
    # 2. auth_middleware - validates tokens
    # 3. context_middleware - creates RequestContext (innermost before app)
    # 4. application (Flask app)
    for middleware in (
        context_middleware,
        auth_middleware,
        request_id_middleware,
    ):
        if middleware:
            application = middleware(application)

    return application


def init_application() -> WSGIApp:
    """Initialize the Tachyon WSGI application.

    This function loads configuration from oslo.config, initializes
    the policy enforcer, and creates the WSGI application with the
    proper middleware pipeline.

    :returns: Configured WSGI application
    """
    # Register oslo.log options before parsing config
    logging.register_options(CONF)

    # Find and parse config files
    config_files = _find_config_files()

    # Initialize oslo.config
    CONF(
        args=sys.argv[1:] if len(sys.argv) > 1 else [],
        project="tachyon",
        default_config_files=config_files,
    )

    # Setup logging (options are now registered)
    logging.setup(CONF, "tachyon")

    LOG.info("Initializing Tachyon API with config files: %s", config_files)

    # Initialize the policy enforcer
    policy.init(CONF)

    # Build and return the WSGI application with middleware
    return deploy(CONF)


# WSGI servers (gunicorn/uwsgi) should load this module path:
#   tachyon.wsgi.api:application
application = init_application()
