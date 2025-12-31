from __future__ import annotations

from flask import Flask, current_app

from tachyon.api import errors, middleware
from tachyon.api.blueprints import (
    aggregates,
    allocation_candidates,
    allocations,
    inventories,
    resource_classes,
    resource_providers,
    root,
    traits,
    usages,
)
from tachyon.db.neo4j_api import init_driver
from tachyon.db.schema import apply_schema


def create_app(config: dict | None = None) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)

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

    return app


def _init_neo4j(app: Flask) -> None:
    """Initialize Neo4j driver and apply schema."""
    driver = init_driver(
        app.config["NEO4J_URI"],
        app.config.get("NEO4J_USERNAME"),
        app.config.get("NEO4J_PASSWORD"),
    )
    app.extensions["neo4j_driver"] = driver

    if app.config.get("AUTO_APPLY_SCHEMA", True):
        with driver.session() as session:
            apply_schema(session)


def get_driver():
    """Get the Neo4j driver, initializing lazily if needed.

    This supports the functional test pattern where the app is created
    during test discovery (without DB), and the driver is configured
    later when the test fixture sets up the database.
    """
    if "neo4j_driver" not in current_app.extensions:
        _init_neo4j(current_app._get_current_object())
    return current_app.extensions["neo4j_driver"]
