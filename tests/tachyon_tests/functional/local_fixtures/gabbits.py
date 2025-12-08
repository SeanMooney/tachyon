"""Gabbi fixtures for Tachyon API functional tests.

This module provides fixtures for running Gabbi YAML tests against
the Tachyon Flask application with a real Neo4j database (via testcontainers
or an external instance).
"""

import os
import uuid

import fixtures
from gabbi import fixture as gabbi_fixture
from testcontainers.core.waiting_utils import wait_for_logs
from testcontainers.neo4j import Neo4jContainer

from tachyon.api import create_app

# Global reference to database fixture for setup_app() access
DB_FIXTURE = None


class TachyonNeo4jContainer(Neo4jContainer):
    """Custom Neo4j container that waits for the correct log pattern.

    Neo4j 5.x changed the startup log from "Remote interface available at"
    to "Bolt enabled on", so we need to override the wait behavior.
    """

    def _connect(self) -> None:
        # Wait for Neo4j 5.x log pattern instead of the old one
        wait_for_logs(self, "Bolt enabled on", timeout=120)


class Neo4jFixture(fixtures.Fixture):
    """Provides a Neo4j database instance for testing.

    Uses testcontainers to spin up a fresh Neo4j container unless
    TACHYON_NEO4J_URI environment variable is set, in which case
    it uses the external database.

    Attributes:
        uri: Bolt connection URI.
        username: Database username.
        password: Database password.
    """

    def __init__(self):
        super().__init__()
        self.container = None
        self.uri = None
        self.username = None
        self.password = None

    def _setUp(self):
        """Set up the database connection."""
        external_uri = os.environ.get("TACHYON_NEO4J_URI")
        if external_uri:
            # Use external database
            self.uri = external_uri
            self.username = os.environ.get("TACHYON_NEO4J_USERNAME", "neo4j")
            self.password = os.environ.get("TACHYON_NEO4J_PASSWORD", "password")
            return

        # Start testcontainer
        # Use custom container class that waits for Neo4j 5.x log pattern
        self.container = TachyonNeo4jContainer(
            image="neo4j:5-community",
            password="password",
        )
        # Reduce memory for CI environments
        self.container.with_env("NEO4J_dbms_memory_heap_initial__size", "256m")
        self.container.with_env("NEO4J_dbms_memory_heap_max__size", "512m")
        self.container.start()
        self.addCleanup(self.container.stop)

        self.uri = self.container.get_connection_url()
        self.username = "neo4j"
        self.password = "password"


class APIFixture(gabbi_fixture.GabbiFixture):
    """Gabbi fixture for API tests.

    Sets up:
    - Neo4j database (testcontainer or external)
    - Environment variables for test data (UUIDs, names)
    - Updates the cached Flask app's Neo4j configuration

    The Neo4j driver is initialized lazily on first request via get_driver().

    Used by declaring in YAML test files:
        fixtures:
          - APIFixture
    """

    def start_fixture(self):
        """Called once before any tests in a YAML file run."""
        global DB_FIXTURE, _CACHED_APP

        # Set up database
        DB_FIXTURE = Neo4jFixture()
        DB_FIXTURE.setUp()

        # Set up environment variables for test data
        self._setup_environ()

        # Update the cached app's config with the real database URI
        # This must happen before any test makes a request
        if _CACHED_APP is not None:
            _CACHED_APP.config["NEO4J_URI"] = DB_FIXTURE.uri
            _CACHED_APP.config["NEO4J_USERNAME"] = DB_FIXTURE.username
            _CACHED_APP.config["NEO4J_PASSWORD"] = DB_FIXTURE.password

    def stop_fixture(self):
        """Called after all tests in a YAML file complete."""
        global DB_FIXTURE, _CACHED_APP

        # Close the Neo4j driver if it was initialized
        if _CACHED_APP is not None and "neo4j_driver" in _CACHED_APP.extensions:
            try:
                _CACHED_APP.extensions["neo4j_driver"].close()
            except Exception:
                pass
            del _CACHED_APP.extensions["neo4j_driver"]

        if DB_FIXTURE:
            DB_FIXTURE.cleanUp()
            DB_FIXTURE = None

    def _setup_environ(self):
        """Set up environment variables for YAML test substitution."""
        # Resource providers
        os.environ["RP_UUID"] = str(uuid.uuid4())
        os.environ["RP_NAME"] = f"rp-{uuid.uuid4().hex[:8]}"
        os.environ["RP_UUID1"] = str(uuid.uuid4())
        os.environ["RP_NAME1"] = f"rp1-{uuid.uuid4().hex[:8]}"
        os.environ["RP_UUID2"] = str(uuid.uuid4())
        os.environ["RP_NAME2"] = f"rp2-{uuid.uuid4().hex[:8]}"
        os.environ["PARENT_PROVIDER_UUID"] = str(uuid.uuid4())

        # Consumers and ownership
        os.environ["CONSUMER_UUID"] = str(uuid.uuid4())
        os.environ["CONSUMER_UUID1"] = str(uuid.uuid4())
        os.environ["PROJECT_ID"] = str(uuid.uuid4())
        os.environ["USER_ID"] = str(uuid.uuid4())

        # Resource classes
        os.environ["CUSTOM_RES_CLASS"] = "CUSTOM_IRON_NFV"


# Module-level cached app instance for wsgi-intercept
_CACHED_APP = None


def setup_app():
    """WSGI application factory for Gabbi.

    Called by Gabbi via wsgi-intercept to get the Flask WSGI application.
    Uses the global DB_FIXTURE for database configuration.

    During test discovery (when DB_FIXTURE is None), we create the app
    with routes registered but skip Neo4j initialization. The driver is
    initialized lazily on first request via get_driver().

    We cache the app instance so that when the fixture updates DB_FIXTURE,
    subsequent calls can update the cached app's config.

    Returns:
        Flask WSGI application callable.
    """
    global _CACHED_APP

    if _CACHED_APP is None:
        # First call - create the app (during discovery, DB_FIXTURE is None)
        flask_config = {
            "TESTING": True,
            "AUTH_STRATEGY": "noauth2",
            "SKIP_DB_INIT": True,  # Skip DB init, driver init is lazy
        }
        _CACHED_APP = create_app(flask_config)

    # Update config with current DB_FIXTURE settings if available
    if DB_FIXTURE is not None:
        _CACHED_APP.config["NEO4J_URI"] = DB_FIXTURE.uri
        _CACHED_APP.config["NEO4J_USERNAME"] = DB_FIXTURE.username
        _CACHED_APP.config["NEO4J_PASSWORD"] = DB_FIXTURE.password

    return _CACHED_APP
