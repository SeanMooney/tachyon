# SPDX-License-Identifier: Apache-2.0

"""WSGI entrypoint for the Tachyon API."""

import os
import sys

from oslo_config import cfg
from oslo_log import log as logging

from tachyon.api import app
from tachyon import conf  # noqa: F401 - registers config options

CONF = cfg.CONF
LOG = logging.getLogger(__name__)

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


def init_application() -> app.flask.Flask:
    """Initialize the Tachyon WSGI application.

    This function loads configuration from oslo.config and creates
    the Flask application with the proper settings.

    :returns: Configured Flask application
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

    # Build Flask config from oslo.config
    flask_config = {
        "AUTH_STRATEGY": CONF.api.auth_strategy,
        "MAX_LIMIT": CONF.api.max_limit,
        "NEO4J_URI": CONF.neo4j.uri,
        "NEO4J_USERNAME": CONF.neo4j.username,
        "NEO4J_PASSWORD": CONF.neo4j.password,
    }

    LOG.debug("Flask config: AUTH_STRATEGY=%s, NEO4J_URI=%s",
              flask_config["AUTH_STRATEGY"], flask_config["NEO4J_URI"])

    return app.create_app(config=flask_config)


# WSGI servers (gunicorn/uwsgi) should load this module path:
#   tachyon.wsgi.api:application
application = init_application()
