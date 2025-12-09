"""Gabbi fixtures for Tachyon API functional tests.

This module provides fixtures for running Gabbi YAML tests against
the Tachyon Flask application with a real Neo4j database (via testcontainers
or an external instance).

Pattern follows placement's test harness - a global CONF/APP that the fixture
controls, and setup_app() returns the cached application.
"""

import os
import uuid

import fixtures
from gabbi import fixture as gabbi_fixture
from testcontainers.core.waiting_utils import wait_for_logs
from testcontainers.neo4j import Neo4jContainer

from tachyon.api import create_app

# Global app for the current test file.
# Set by APIFixture.start_fixture(), cleared by stop_fixture().
# We cache the APP because wsgi-intercept expects a consistent WSGI app.
APP = None


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
        self.addCleanup(self._stop_container)

        self.uri = self.container.get_connection_url()
        self.username = "neo4j"
        self.password = "password"

    def _stop_container(self):
        """Stop the Neo4j container if running."""
        if self.container is not None:
            try:
                self.container.stop()
            except Exception:
                pass
            self.container = None


class LazyWSGIApp:
    """A lazy WSGI wrapper that defers to the global APP.

    This is needed because gabbi creates HTTP clients during test discovery
    (before fixtures run), but we need requests to use the app created by
    the fixture. This wrapper defers the actual app lookup to request time.
    """

    def __call__(self, environ, start_response):
        """WSGI callable that delegates to the current global APP."""
        if APP is None:
            # This shouldn't happen during normal test execution
            raise RuntimeError(
                "LazyWSGIApp called but APP is None. "
                "Fixture may not have run."
            )
        return APP(environ, start_response)


# Single lazy app instance used by all tests
_lazy_app = LazyWSGIApp()


def setup_app():
    """WSGI application factory for Gabbi.

    Called by Gabbi via wsgi-intercept to get the Flask WSGI application.
    Returns a lazy wrapper that defers to the global APP set by the fixture.

    This allows tests to be discovered before fixtures run, while still
    using the correct app configuration during execution.

    Returns:
        WSGI application callable.
    """
    return _lazy_app


class APIFixture(gabbi_fixture.GabbiFixture):
    """Gabbi fixture for API tests.

    Sets up:
    - Neo4j database (testcontainer or external)
    - Flask app configuration
    - Environment variables for test data (UUIDs, names)

    Each YAML file gets its own database container for complete isolation.
    The fixture creates and caches the Flask app with proper Neo4j config.

    Used by declaring in YAML test files:
        fixtures:
          - APIFixture
    """

    def start_fixture(self):
        """Called once before any tests in a YAML file run."""
        global APP

        # Set up database - each YAML file gets its own container
        self.db_fixture = Neo4jFixture()
        self.db_fixture.setUp()

        # Set up environment variables for test data
        os.environ['RP_UUID'] = str(uuid.uuid4())
        os.environ['RP_NAME'] = f"rp-{uuid.uuid4().hex[:8]}"
        os.environ['RP_UUID1'] = str(uuid.uuid4())
        os.environ['RP_NAME1'] = f"rp1-{uuid.uuid4().hex[:8]}"
        os.environ['RP_UUID2'] = str(uuid.uuid4())
        os.environ['RP_NAME2'] = f"rp2-{uuid.uuid4().hex[:8]}"
        os.environ['PARENT_PROVIDER_UUID'] = str(uuid.uuid4())
        os.environ['ALT_PARENT_PROVIDER_UUID'] = str(uuid.uuid4())
        os.environ['CONSUMER_UUID'] = str(uuid.uuid4())
        os.environ['CONSUMER_UUID1'] = str(uuid.uuid4())
        os.environ['PROJECT_ID'] = str(uuid.uuid4())
        os.environ['USER_ID'] = str(uuid.uuid4())
        os.environ['CUSTOM_RES_CLASS'] = 'CUSTOM_IRON_NFV'

        # Create Flask app with proper Neo4j config and cache it
        flask_config = {
            "TESTING": True,
            "AUTH_STRATEGY": "noauth2",
            "SKIP_DB_INIT": False,  # Initialize Neo4j driver during app creation
            "NEO4J_URI": self.db_fixture.uri,
            "NEO4J_USERNAME": self.db_fixture.username,
            "NEO4J_PASSWORD": self.db_fixture.password,
        }
        APP = create_app(flask_config)

    def stop_fixture(self):
        """Called after all tests in a YAML file complete."""
        global APP

        # Close Neo4j driver if initialized
        if APP is not None and "neo4j_driver" in APP.extensions:
            try:
                APP.extensions["neo4j_driver"].close()
            except Exception:
                pass

        # Clean up database fixture
        self.db_fixture.cleanUp()
        APP = None
