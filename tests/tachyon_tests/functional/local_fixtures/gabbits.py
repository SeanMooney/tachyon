"""Gabbi fixtures for Tachyon API functional tests.

This module provides fixtures for running Gabbi YAML tests against
the Tachyon Flask application with a real Neo4j database (via testcontainers
or an external instance).

Each test file gets its own Flask development server running in a separate
thread on a dynamically allocated port, providing complete isolation for
concurrent test execution.
"""

import os
import socket
import threading
import uuid

import fixtures
from gabbi import fixture as gabbi_fixture
from testcontainers.core.waiting_utils import wait_for_logs
from testcontainers.neo4j import Neo4jContainer
from werkzeug.serving import make_server

from tachyon.api import create_app


def get_free_port():
    """Find and return a free port on localhost.

    Uses the OS to allocate a free port by binding to port 0.
    The socket is closed immediately, making the port available.

    Returns:
        int: A free port number.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


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


class APIFixture(gabbi_fixture.GabbiFixture):
    """Gabbi fixture for API tests.

    Sets up:
    - Neo4j database (testcontainer or external)
    - Flask development server in a separate thread
    - Environment variables for test data (UUIDs, names)

    Each YAML file gets its own database container and Flask server
    for complete isolation. The port is allocated dynamically at fixture
    time and stored in TACHYON_TEST_PORT environment variable.

    Used by declaring in YAML test files:
        fixtures:
          - APIFixture
    """

    def start_fixture(self):
        """Called once before any tests in a YAML file run."""
        # Set up database - each YAML file gets its own container
        self.db_fixture = Neo4jFixture()
        self.db_fixture.setUp()

        # Allocate a free port for this fixture (runs in worker process)
        self.port = get_free_port()

        # Set environment variable so tests can discover the port
        # The monkey-patch in test_api.py reads this at request time
        os.environ['TACHYON_TEST_PORT'] = str(self.port)

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

        # Create Flask app with proper Neo4j config
        flask_config = {
            "TESTING": True,
            "AUTH_STRATEGY": "noauth2",
            "SKIP_DB_INIT": False,  # Initialize Neo4j driver during app creation
            "NEO4J_URI": self.db_fixture.uri,
            "NEO4J_USERNAME": self.db_fixture.username,
            "NEO4J_PASSWORD": self.db_fixture.password,
        }
        self.app = create_app(flask_config)

        # Start Flask development server in a separate thread on the allocated port
        self.server = make_server(
            '127.0.0.1',
            self.port,
            self.app,
            threaded=True,
        )
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.server_thread.start()

    def stop_fixture(self):
        """Called after all tests in a YAML file complete."""
        # Shutdown the Flask server
        if hasattr(self, 'server') and self.server:
            self.server.shutdown()

        # Wait for server thread to finish
        if hasattr(self, 'server_thread') and self.server_thread:
            self.server_thread.join(timeout=5)

        # Close Neo4j driver if initialized
        if hasattr(self, 'app') and self.app and "neo4j_driver" in self.app.extensions:
            try:
                self.app.extensions["neo4j_driver"].close()
            except Exception:
                pass

        # Clean up database fixture
        if hasattr(self, 'db_fixture'):
            self.db_fixture.cleanUp()

        # Clean up port environment variable
        if 'TACHYON_TEST_PORT' in os.environ:
            del os.environ['TACHYON_TEST_PORT']
