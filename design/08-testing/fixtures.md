---
title: Fixture Architecture
description: Test fixture design patterns using the fixtures library
keywords: [fixtures, local_fixtures, testtools, useFixture, addCleanup, composition, flask]
related:
  - 08-testing/README.md
  - 08-testing/neo4j-testing.md
  - 08-testing/gabbi-tests.md
  - 00-overview/technology-stack.md
implements: []
section: testing
---

# Fixture Architecture

Tachyon uses the [fixtures](https://pypi.org/project/fixtures/) library for test setup and teardown, following OpenStack conventions established in Nova and Placement.

> **Note**: For Flask application factory pattern details, see [Technology Stack](../00-overview/technology-stack.md#rest-api-framework-flask).

## Why Fixtures?

The `fixtures` library provides:

1. **Composable Setup/Teardown**: `useFixture()` chains fixtures with automatic cleanup
2. **Guaranteed Cleanup**: `addCleanup()` ensures resources are released even on failure
3. **Reusability**: Same fixtures used across unit and functional tests
4. **OpenStack Standard**: Familiar to OpenStack contributors

## Fixture Location

```
tests/tachyon_tests/
├── local_fixtures/              # Shared fixtures (all test types)
│   ├── __init__.py
│   ├── database.py              # Neo4j testcontainer
│   ├── config.py                # oslo.config
│   ├── logging.py               # Log capture
│   └── policy.py                # oslo.policy
└── functional/
    └── local_fixtures/          # Gabbi-specific fixtures
        ├── __init__.py
        └── gabbits.py           # APIFixture for Gabbi tests
```

### Why `local_fixtures`?

Named `local_fixtures` (not `fixtures`) to avoid import conflicts:

```python
# When tests are added to PYTHONPATH for debugging,
# a module named 'fixtures' would shadow the fixtures library

import fixtures  # The library
from tachyon_tests.local_fixtures import database  # Our fixtures - no conflict
```

## Core Fixtures

### Database Fixture

**File**: `tests/tachyon_tests/local_fixtures/database.py`

```python
"""Neo4j database fixture using testcontainers."""

import fixtures
from testcontainers.neo4j import Neo4jContainer


class Neo4jDatabase(fixtures.Fixture):
    """Provides an isolated Neo4j database for testing.
    
    Uses testcontainers to spin up a fresh Neo4j container for each
    test class, ensuring complete isolation between tests.
    
    Attributes:
        driver: Neo4j driver instance for database operations
        uri: Connection URI for the database
    """
    
    def __init__(self, conf_fixture=None):
        """Initialize the database fixture.
        
        Args:
            conf_fixture: Optional oslo.config fixture to configure
                         database connection options
        """
        super().__init__()
        self.conf_fixture = conf_fixture
        self._container = None
        self.driver = None
        self.uri = None
    
    def _setUp(self):
        """Start Neo4j container and configure connection."""
        # Start container
        self._container = Neo4jContainer("neo4j:5-community")
        self._container.with_env("NEO4J_AUTH", "none")  # Disable auth for tests
        self._container.start()
        
        # Store connection details
        self.uri = self._container.get_connection_url()
        
        # Configure oslo.config if provided
        if self.conf_fixture:
            self.conf_fixture.config(
                uri=self.uri,
                group='neo4j_database'
            )
        
        # Create driver
        from neo4j import GraphDatabase
        self.driver = GraphDatabase.driver(self.uri)
        
        # Create schema
        self._create_schema()
        
        # Register cleanup
        self.addCleanup(self._cleanup)
    
    def _create_schema(self):
        """Create database schema using Cypher."""
        from tachyon.db import schema
        with self.driver.session() as session:
            for statement in schema.SCHEMA_STATEMENTS:
                session.run(statement)
    
    def _cleanup(self):
        """Clean up database resources."""
        if self.driver:
            self.driver.close()
        if self._container:
            self._container.stop()
    
    def clear(self):
        """Clear all data while preserving schema.
        
        Useful for resetting between tests within a class.
        """
        with self.driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
```

### Configuration Fixture

**File**: `tests/tachyon_tests/local_fixtures/config.py`

```python
"""Configuration fixture for oslo.config."""

import fixtures
from oslo_config import cfg
from oslo_config import fixture as config_fixture

from tachyon import conf


class ConfFixture(fixtures.Fixture):
    """Provides isolated oslo.config configuration for tests.
    
    Creates a fresh ConfigOpts instance and registers Tachyon's
    configuration options.
    """
    
    def __init__(self):
        super().__init__()
        self.conf = None
    
    def _setUp(self):
        """Set up isolated configuration."""
        # Create fresh config
        self._config_fixture = config_fixture.Config(cfg.ConfigOpts())
        self._config_fixture.setUp()
        self.conf = self._config_fixture.conf
        
        # Register Tachyon options
        conf.register_opts(self.conf)
        
        # Set test defaults
        self._config_fixture.config(
            group='api',
            auth_strategy='noauth2'
        )
        
        # Don't read config files
        self.conf([], default_config_files=[])
        
        self.addCleanup(self._config_fixture.cleanUp)
    
    def config(self, **kwargs):
        """Convenience method to set config options.
        
        Args:
            **kwargs: Config options, with 'group' for non-default groups
        """
        self._config_fixture.config(**kwargs)
```

### Logging Fixture

**File**: `tests/tachyon_tests/local_fixtures/logging.py`

```python
"""Logging and warning capture fixtures."""

import logging
import warnings

import fixtures
from oslotest import log


class NullHandler(logging.Handler):
    """Handler that formats records but discards output.
    
    Used to detect formatting errors in debug logs even when
    logs aren't captured.
    """
    
    def handle(self, record):
        self.format(record)
    
    def emit(self, record):
        pass
    
    def createLock(self):
        self.lock = None


class Logging(log.ConfigureLogging):
    """Logging fixture with debug formatting verification.
    
    Inherits from oslotest's ConfigureLogging but adds a NullHandler
    to catch formatting errors in debug logs.
    """
    
    def __init__(self):
        super().__init__()
        if self.level is None:
            self.level = logging.INFO
    
    def setUp(self):
        super().setUp()
        # Add NullHandler to verify debug log formatting
        if self.level > logging.DEBUG:
            handler = NullHandler()
            self.useFixture(fixtures.LogHandler(handler, nuke_handlers=False))
            handler.setLevel(logging.DEBUG)


class WarningsFixture(fixtures.Fixture):
    """Filter and escalate warnings during tests.
    
    Configures warning filters to:
    - Show deprecation warnings once
    - Escalate certain warnings to errors
    - Ignore known benign warnings
    """
    
    def setUp(self):
        super().setUp()
        
        self._original_filters = warnings.filters[:]
        
        # Show deprecations once
        warnings.simplefilter("once", DeprecationWarning)
        
        # Escalate invalid UUID warnings to errors
        warnings.filterwarnings('error', message=".*invalid UUID.*")
        
        # Ignore policy scope warnings
        warnings.filterwarnings(
            'ignore',
            message="Policy .* failed scope check",
            category=UserWarning
        )
        
        self.addCleanup(self._reset)
    
    def _reset(self):
        """Restore original warning filters."""
        warnings.filters[:] = self._original_filters
```

### Policy Fixture

**File**: `tests/tachyon_tests/local_fixtures/policy.py`

```python
"""Policy fixture for oslo.policy testing."""

import copy

import fixtures

from tachyon import policies
from tachyon import policy


class PolicyFixture(fixtures.Fixture):
    """Provides policy enforcement for tests.
    
    Loads default policy rules and provides methods to override
    rules for specific tests.
    """
    
    def __init__(self, conf_fixture):
        """Initialize policy fixture.
        
        Args:
            conf_fixture: ConfFixture instance for configuration
        """
        super().__init__()
        self.conf_fixture = conf_fixture
    
    def _setUp(self):
        """Set up policy enforcement."""
        # Reset any existing policy
        policy.reset()
        
        # Initialize with default rules (deep copy to avoid mutation)
        policy.init(
            self.conf_fixture.conf,
            suppress_deprecation_warnings=True,
            rules=copy.deepcopy(policies.list_rules())
        )
        
        self.addCleanup(policy.reset)
    
    @staticmethod
    def set_rules(rules, overwrite=True):
        """Override policy rules for testing.
        
        Args:
            rules: Dict mapping action names to rule strings
            overwrite: If True, replace all rules; if False, merge
        
        Example:
            PolicyFixture.set_rules({
                'placement:resource_providers:list': 'role:admin'
            })
        """
        from oslo_policy import policy as oslo_policy
        enforcer = policy.get_enforcer()
        enforcer.set_rules(
            oslo_policy.Rules.from_dict(rules),
            overwrite=overwrite
        )
```

## Flask Application Fixtures

### FlaskAppFixture

**File**: `tests/tachyon_tests/local_fixtures/flask_app.py`

```python
"""Flask application fixture for functional tests."""

import fixtures

from tachyon.api import create_app


class FlaskAppFixture(fixtures.Fixture):
    """Provides a configured Flask application for testing.
    
    Uses Flask's application factory pattern (create_app) to create
    an isolated application instance with test configuration.
    
    Attributes:
        app: Flask application instance
        client: Flask test client for making requests
    """
    
    def __init__(self, conf_fixture=None, db_fixture=None):
        """Initialize the Flask app fixture.
        
        Args:
            conf_fixture: Optional ConfFixture for oslo.config integration
            db_fixture: Optional Neo4jDatabase fixture for database connection
        """
        super().__init__()
        self.conf_fixture = conf_fixture
        self.db_fixture = db_fixture
        self.app = None
        self.client = None
    
    def _setUp(self):
        """Create and configure the Flask application."""
        # Build Flask config
        flask_config = {
            'TESTING': True,
            'AUTH_STRATEGY': 'noauth2',
        }
        
        # Add database URI if available
        if self.db_fixture:
            flask_config['NEO4J_URI'] = self.db_fixture.uri
        
        # Create application
        self.app = create_app(flask_config)
        
        # Create test client
        self.client = self.app.test_client()
        
        # Push application context for request-independent operations
        self._ctx = self.app.app_context()
        self._ctx.push()
        
        self.addCleanup(self._cleanup)
    
    def _cleanup(self):
        """Clean up Flask application resources."""
        if self._ctx:
            self._ctx.pop()


class FlaskTestClientFixture(fixtures.Fixture):
    """Provides a Flask test client with request context.
    
    Wraps FlaskAppFixture to provide a simpler interface for tests
    that only need to make HTTP requests.
    """
    
    def __init__(self, app_fixture):
        """Initialize with an existing FlaskAppFixture.
        
        Args:
            app_fixture: FlaskAppFixture instance
        """
        super().__init__()
        self.app_fixture = app_fixture
    
    def _setUp(self):
        """Set up the test client context."""
        self.client = self.app_fixture.client
        
    def get(self, path, **kwargs):
        """Make a GET request with default test headers."""
        return self._request('get', path, **kwargs)
    
    def post(self, path, **kwargs):
        """Make a POST request with default test headers."""
        return self._request('post', path, **kwargs)
    
    def put(self, path, **kwargs):
        """Make a PUT request with default test headers."""
        return self._request('put', path, **kwargs)
    
    def delete(self, path, **kwargs):
        """Make a DELETE request with default test headers."""
        return self._request('delete', path, **kwargs)
    
    def _request(self, method, path, **kwargs):
        """Make a request with default headers."""
        headers = kwargs.pop('headers', {})
        headers.setdefault('X-Auth-Token', 'admin')
        headers.setdefault('Accept', 'application/json')
        headers.setdefault('OpenStack-API-Version', 'placement latest')
        kwargs['headers'] = headers
        return getattr(self.client, method)(path, **kwargs)
```

### Using Flask Fixtures

```python
# In a functional test
class TestResourceProviders(base.TestCase):
    def setUp(self):
        super().setUp()
        
        # Set up configuration
        self.conf_fixture = self.useFixture(config.ConfFixture())
        
        # Set up database
        self.db = self.useFixture(database.Neo4jDatabase(self.conf_fixture))
        
        # Set up Flask app with database connection
        self.flask_app = self.useFixture(
            flask_app.FlaskAppFixture(self.conf_fixture, self.db)
        )
        
        # Convenience client wrapper
        self.api = self.useFixture(
            flask_app.FlaskTestClientFixture(self.flask_app)
        )
    
    def test_create_resource_provider(self):
        response = self.api.post('/resource_providers',
            json={'name': 'test-rp', 'uuid': str(uuid.uuid4())})
        self.assertEqual(200, response.status_code)
        self.assertIn('uuid', response.json)
```

## Gabbi Fixtures

### APIFixture

**File**: `tests/tachyon_tests/functional/local_fixtures/gabbits.py`

```python
"""Gabbi fixtures for API testing."""

import os

from gabbi import fixture
from oslo_config import cfg
from oslo_config import fixture as config_fixture
from oslo_log.fixture import logging_error
from oslo_utils import uuidutils
from oslotest import output

from tachyon import conf
from tachyon import deploy
from tachyon_tests.local_fixtures import database
from tachyon_tests.local_fixtures import logging as log_fixtures
from tachyon_tests.local_fixtures import policy as policy_fixtures

# Global config for setup_app workaround
CONF = None
DB_FIXTURE = None


def setup_app():
    """WSGI application factory for Gabbi.
    
    Called by Gabbi via wsgi-intercept to get the Flask WSGI application.
    Uses global CONF and DB_FIXTURE due to Gabbi's fixture limitations.
    
    The Flask application factory pattern (create_app) is used here,
    integrating with wsgi-intercept for in-process HTTP testing.
    
    Returns:
        Flask WSGI application callable.
    """
    global CONF, DB_FIXTURE
    from tachyon.api import create_app
    
    flask_config = {
        'TESTING': True,
        'AUTH_STRATEGY': CONF.api.auth_strategy if CONF else 'noauth2',
    }
    
    if DB_FIXTURE:
        flask_config['NEO4J_URI'] = DB_FIXTURE.uri
    
    return create_app(flask_config)


class APIFixture(fixture.GabbiFixture):
    """Base fixture for Gabbi API tests.
    
    Sets up:
    - Configuration (oslo.config)
    - Database (Neo4j testcontainer)
    - Policy enforcement
    - Logging capture
    - Environment variables for test data
    """
    
    def start_fixture(self):
        """Called once before any tests in a YAML file run."""
        global CONF, DB_FIXTURE
        
        # Set up logging/output capture
        self.logging_fixture = log_fixtures.Logging()
        self.logging_fixture.setUp()
        self.output_fixture = output.CaptureOutput()
        self.output_fixture.setUp()
        self.logging_error_fixture = logging_error.get_logging_handle_error_fixture()
        self.logging_error_fixture.setUp()
        self.warnings_fixture = log_fixtures.WarningsFixture()
        self.warnings_fixture.setUp()
        
        # Set up config
        self.conf_fixture = config_fixture.Config(cfg.ConfigOpts())
        self.conf_fixture.setUp()
        conf.register_opts(self.conf_fixture.conf)
        self.conf_fixture.config(group='api', auth_strategy='noauth2')
        self.conf_fixture.conf([], default_config_files=[])
        
        # Set up database
        self.db_fixture = database.Neo4jDatabase(self.conf_fixture)
        self.db_fixture.setUp()
        
        # Set up policy
        self.policy_fixture = policy_fixtures.PolicyFixture(self.conf_fixture)
        self.policy_fixture.setUp()
        
        # Populate environment variables for YAML tests
        self._setup_environ()
        
        # Store config and db globally for setup_app()
        CONF = self.conf_fixture.conf
        DB_FIXTURE = self.db_fixture
    
    def _setup_environ(self):
        """Set up environment variables for test data."""
        # Resource providers
        os.environ['RP_UUID'] = uuidutils.generate_uuid()
        os.environ['RP_NAME'] = uuidutils.generate_uuid()
        os.environ['RP_UUID1'] = uuidutils.generate_uuid()
        os.environ['RP_NAME1'] = uuidutils.generate_uuid()
        os.environ['RP_UUID2'] = uuidutils.generate_uuid()
        os.environ['RP_NAME2'] = uuidutils.generate_uuid()
        os.environ['PARENT_PROVIDER_UUID'] = uuidutils.generate_uuid()
        os.environ['ALT_PARENT_PROVIDER_UUID'] = uuidutils.generate_uuid()
        
        # Consumers and ownership
        os.environ['CONSUMER_UUID'] = uuidutils.generate_uuid()
        os.environ['PROJECT_ID'] = uuidutils.generate_uuid()
        os.environ['USER_ID'] = uuidutils.generate_uuid()
        os.environ['ALT_USER_ID'] = uuidutils.generate_uuid()
        
        # Resource classes
        os.environ['CUSTOM_RES_CLASS'] = 'CUSTOM_IRON_NFV'
    
    def stop_fixture(self):
        """Called after all tests in a YAML file complete."""
        global CONF, DB_FIXTURE
        
        # Clean up in reverse order
        self.policy_fixture.cleanUp()
        self.db_fixture.cleanUp()
        self.conf_fixture.cleanUp()
        self.warnings_fixture.cleanUp()
        self.logging_error_fixture.cleanUp()
        self.output_fixture.cleanUp()
        self.logging_fixture.cleanUp()
        
        CONF = None
        DB_FIXTURE = None


class AllocationFixture(APIFixture):
    """APIFixture with pre-created allocations.
    
    Pre-creates:
    - Resource provider with VCPU and DISK_GB inventory
    - User and project
    - Consumers with allocations
    """
    
    def start_fixture(self):
        """Set up base infrastructure and pre-create test data."""
        super().start_fixture()
        
        # Create additional environment variables
        os.environ['CONSUMER_0'] = uuidutils.generate_uuid()
        os.environ['CONSUMER_ID'] = uuidutils.generate_uuid()
        
        # Create test data using driver
        self._create_test_data()
    
    def _create_test_data(self):
        """Create pre-populated test data in Neo4j."""
        driver = self.db_fixture.driver
        
        with driver.session() as session:
            # Create resource provider
            session.run("""
                CREATE (rp:ResourceProvider {
                    uuid: $uuid,
                    name: $name,
                    generation: 0
                })
            """, uuid=os.environ['RP_UUID'], name=os.environ['RP_NAME'])
            
            # Create inventory
            session.run("""
                MATCH (rp:ResourceProvider {uuid: $rp_uuid})
                CREATE (rp)-[:HAS_INVENTORY]->(inv:Inventory {
                    resource_class: 'VCPU',
                    total: 10,
                    reserved: 0,
                    min_unit: 1,
                    max_unit: 10,
                    step_size: 1,
                    allocation_ratio: 1.0
                })
            """, rp_uuid=os.environ['RP_UUID'])
            
            session.run("""
                MATCH (rp:ResourceProvider {uuid: $rp_uuid})
                CREATE (rp)-[:HAS_INVENTORY]->(inv:Inventory {
                    resource_class: 'DISK_GB',
                    total: 2048,
                    reserved: 0,
                    min_unit: 10,
                    max_unit: 1000,
                    step_size: 10,
                    allocation_ratio: 1.0
                })
            """, rp_uuid=os.environ['RP_UUID'])
            
            # Create consumers with allocations
            # (Additional setup as needed)
```

## Fixture Patterns

### Composition with `useFixture()`

Fixtures can use other fixtures, creating a hierarchy:

```python
class TestCase(testtools.TestCase):
    def setUp(self):
        super().setUp()
        
        # Configuration first
        self.conf_fixture = self.useFixture(ConfFixture())
        
        # Database needs config
        self.db = self.useFixture(Neo4jDatabase(self.conf_fixture))
        
        # Policy needs config
        self.useFixture(PolicyFixture(self.conf_fixture))
        
        # Logging is independent
        self.useFixture(Logging())
```

### Cleanup Ordering

Cleanups run in reverse order of `addCleanup()` calls:

```python
def _setUp(self):
    self.resource1 = create_resource1()
    self.addCleanup(self.resource1.close)  # Runs last
    
    self.resource2 = create_resource2(self.resource1)
    self.addCleanup(self.resource2.close)  # Runs first
```

### Context Manager Support

Fixtures support `with` statements:

```python
with Neo4jDatabase(conf_fixture) as db:
    # db is set up
    result = db.driver.session().run("MATCH (n) RETURN n")
# db is automatically cleaned up
```

### Reset for Reuse

Some fixtures support `reset()` for faster test isolation:

```python
class DatabaseFixture(fixtures.Fixture):
    def reset(self):
        """Clear data without restarting container."""
        self.clear()  # Faster than full cleanup/setup
```

## Base Test Classes

### Unit Test Base

```python
# tests/tachyon_tests/unit/base.py
from oslo_config import fixture as config_fixture
from oslotest import base

from tachyon_tests.local_fixtures import config
from tachyon_tests.local_fixtures import logging


class TestCase(base.BaseTestCase):
    """Base class for unit tests."""
    
    def setUp(self):
        super().setUp()
        self.conf_fixture = self.useFixture(config.ConfFixture())
        self.useFixture(logging.Logging())
```

### Functional Test Base

```python
# tests/tachyon_tests/functional/base.py
from oslo_config import fixture as config_fixture
from oslotest import base

from tachyon_tests.local_fixtures import config
from tachyon_tests.local_fixtures import database
from tachyon_tests.local_fixtures import logging
from tachyon_tests.local_fixtures import policy


class TestCase(base.BaseTestCase):
    """Base class for functional tests."""
    
    USES_DB = True
    
    def setUp(self):
        super().setUp()
        
        self.conf_fixture = self.useFixture(config.ConfFixture())
        
        if self.USES_DB:
            self.db = self.useFixture(database.Neo4jDatabase(self.conf_fixture))
        
        self.useFixture(logging.Logging())
        self.useFixture(logging.WarningsFixture())
        self.useFixture(policy.PolicyFixture(self.conf_fixture))
```

## References

- [fixtures library documentation](https://pypi.org/project/fixtures/)
- [Placement fixtures](../../placement-gabbi-tests.md) - Patterns for Gabbi integration
- [Nova fixtures](../../funtional-testing.md) - Multi-fixture composition patterns

