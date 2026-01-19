# SPDX-License-Identifier: Apache-2.0

"""Flask application factory for Tachyon API."""

from __future__ import annotations

from typing import Any

import flask

from oslo_log import log

from tachyon.api import errors
from tachyon.api import middleware
from tachyon.api.blueprints import aggregates
from tachyon.api.blueprints import allocation_candidates
from tachyon.api.blueprints import allocations
from tachyon.api.blueprints import inventories
from tachyon.api.blueprints import resource_classes
from tachyon.api.blueprints import resource_providers
from tachyon.api.blueprints import root
from tachyon.api.blueprints import traits
from tachyon.api.blueprints import usages
from tachyon.db import neo4j_api
from tachyon.db import schema

LOG = log.getLogger(__name__)


def create_app(config: dict[str, Any] | None = None) -> flask.Flask:
    """Create and configure the Flask application.

    :param config: Optional configuration dictionary to override defaults
    :returns: Configured Flask application instance
    """
    LOG.debug("Creating Flask application")
    app = flask.Flask(__name__)

    # Defaults
    app.config.setdefault("AUTH_STRATEGY", "noauth2")
    app.config.setdefault("MAX_LIMIT", 1000)
    app.config.setdefault("NEO4J_URI", "bolt://localhost:7687")
    app.config.setdefault("NEO4J_USERNAME", "neo4j")
    app.config.setdefault("NEO4J_PASSWORD", "password")
    app.config.setdefault("AUTO_APPLY_SCHEMA", True)
    app.config.setdefault("SKIP_DB_INIT", False)

    if config:
        app.config.update(config)
        LOG.debug("Applied custom configuration")

    # Register middleware and errors
    middleware.register(app)
    errors.register_handlers(app)

    # Initialize Neo4j driver and schema (unless skipped for test discovery)
    if not app.config.get("SKIP_DB_INIT"):
        _init_neo4j(app)

    # Register blueprints
    app.register_blueprint(root.bp)
    app.register_blueprint(resource_providers.bp)
    app.register_blueprint(inventories.bp)
    app.register_blueprint(aggregates.bp)
    app.register_blueprint(allocation_candidates.bp)
    app.register_blueprint(traits.bp)
    app.register_blueprint(traits.provider_traits_bp)
    app.register_blueprint(resource_classes.bp)
    app.register_blueprint(allocations.bp)
    app.register_blueprint(usages.bp)

    LOG.info("Flask application created successfully")
    return app


def _init_neo4j(app: flask.Flask) -> None:
    """Initialize Neo4j driver and apply schema.

    :param app: Flask application instance
    """
    LOG.debug("Initializing Neo4j driver with URI %s", app.config["NEO4J_URI"])
    driver = neo4j_api.init_driver(
        app.config["NEO4J_URI"],
        app.config.get("NEO4J_USERNAME"),
        app.config.get("NEO4J_PASSWORD"),
    )
    app.extensions["neo4j_driver"] = driver

    if app.config.get("AUTO_APPLY_SCHEMA", True):
        LOG.debug("Applying database schema")
        with driver.session() as session:
            schema.apply_schema(session)
    LOG.info("Neo4j driver initialized")


def get_driver() -> neo4j_api.Neo4jClient:
    """Get the Neo4j driver, initializing lazily if needed.

    This supports the functional test pattern where the app is created
    during test discovery (without DB), and the driver is configured
    later when the test fixture sets up the database.

    :returns: Neo4j driver instance
    """
    if "neo4j_driver" not in flask.current_app.extensions:
        LOG.debug("Lazy-initializing Neo4j driver")
        # Get the actual Flask app object from the proxy
        app: flask.Flask = flask.current_app._get_current_object()
        _init_neo4j(app)
    driver: neo4j_api.Neo4jClient = flask.current_app.extensions["neo4j_driver"]
    return driver
