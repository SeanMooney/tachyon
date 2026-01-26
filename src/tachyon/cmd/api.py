# SPDX-License-Identifier: Apache-2.0

"""CLI entrypoint for Tachyon API development server.

This is primarily for development/testing. In production, use a WSGI server
like uWSGI or gunicorn with the tachyon.wsgi.api:application entry point.

Usage:
    tachyon-api  # Start development server on default port
"""

from __future__ import annotations

import sys

from oslo_config import cfg
from oslo_log import log as logging

from tachyon import conf  # noqa: F401 - registers config options
from tachyon.api import app

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


def main() -> int:
    """Run the Tachyon API development server.

    :returns: exit code (0 for success, non-zero for failure)
    """
    # Register logging options and parse config
    logging.register_options(CONF)
    try:
        CONF(sys.argv[1:], project="tachyon")
    except cfg.ConfigFilesNotFoundError:
        # Config file is optional for development
        CONF(sys.argv[1:], project="tachyon", default_config_files=[])

    logging.setup(CONF, "tachyon")

    LOG.info("Starting Tachyon API development server")

    # Build Flask config from oslo.config
    flask_config = {
        "AUTH_STRATEGY": CONF.api.auth_strategy,
        "MAX_LIMIT": CONF.api.max_limit,
        "NEO4J_URI": CONF.neo4j.uri,
        "NEO4J_USERNAME": CONF.neo4j.username,
        "NEO4J_PASSWORD": CONF.neo4j.password,
    }

    flask_app = app.create_app(config=flask_config)

    # Run Flask development server
    # Note: This is NOT suitable for production use
    flask_app.run(
        host="0.0.0.0",
        port=8778,
        debug=CONF.debug,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
