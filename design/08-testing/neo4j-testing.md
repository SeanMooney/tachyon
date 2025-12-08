---
title: Neo4j Testing
description: Database testing patterns using testcontainers
keywords: [neo4j, testcontainers, database, isolation, container, cypher]
related:
  - 08-testing/README.md
  - 08-testing/fixtures.md
  - 05-operations/indexes-constraints.md
implements: []
section: testing
---

# Neo4j Testing

Tachyon uses [testcontainers](https://testcontainers.com/) to provide isolated Neo4j instances for testing, ensuring each test class runs against a clean database.

## Why Testcontainers?

| Approach | Pros | Cons |
|----------|------|------|
| **Mocked Database** | Fast, no dependencies | Doesn't test real queries |
| **Shared Instance** | Fast startup | Test pollution, complex cleanup |
| **Testcontainers** | True isolation, real Neo4j | Slower startup (mitigated by reuse) |

Tachyon prioritizes **correctness over speed** in functional tests, making testcontainers the right choice.

## Comparison with Reference Projects

| Pattern | Placement (oslo.db) | Neo4j Driver | Tachyon |
|---------|---------------------|--------------|---------|
| Database | SQLite in-memory | Real Neo4j server | Neo4j testcontainer |
| Schema | Alembic migrations | N/A | Cypher scripts |
| Isolation | Transaction rollback | Per-test database | Fresh container |
| Speed | Very fast | Requires server setup | Medium (container reuse) |

## Database Fixture

### Basic Implementation

```python
"""Neo4j database fixture using testcontainers."""

import fixtures
from testcontainers.neo4j import Neo4jContainer


class Neo4jDatabase(fixtures.Fixture):
    """Provides an isolated Neo4j database for testing.

    Attributes:
        driver: Neo4j driver for database operations
        uri: Bolt connection URI
    """

    # Container reuse for performance (optional)
    _shared_container = None
    _container_reuse = True

    def __init__(self, conf_fixture=None):
        super().__init__()
        self.conf_fixture = conf_fixture
        self._container = None
        self.driver = None
        self.uri = None

    def _setUp(self):
        """Start or reuse Neo4j container."""
        if self._container_reuse and Neo4jDatabase._shared_container:
            # Reuse existing container
            self._container = Neo4jDatabase._shared_container
            self._clear_database()
        else:
            # Start new container
            self._container = Neo4jContainer("neo4j:5-community")
            self._container.with_env("NEO4J_AUTH", "none")
            self._container.start()

            if self._container_reuse:
                Neo4jDatabase._shared_container = self._container

        # Get connection details
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
        """Create database schema (indexes, constraints)."""
        from tachyon.db import schema
        with self.driver.session() as session:
            for statement in schema.SCHEMA_STATEMENTS:
                session.run(statement)

    def _clear_database(self):
        """Clear all data while preserving schema."""
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(self._container.get_connection_url())
        try:
            with driver.session() as session:
                session.run("MATCH (n) DETACH DELETE n")
        finally:
            driver.close()

    def _cleanup(self):
        """Clean up database resources."""
        if self.driver:
            self.driver.close()

        # Don't stop shared container
        if not self._container_reuse and self._container:
            self._container.stop()

    @classmethod
    def stop_shared_container(cls):
        """Stop shared container (call at end of test session)."""
        if cls._shared_container:
            cls._shared_container.stop()
            cls._shared_container = None
```

### Container Configuration

```python
# Neo4j 5.x Community Edition (no license required)
container = Neo4jContainer("neo4j:5-community")

# Disable authentication for tests
container.with_env("NEO4J_AUTH", "none")

# Configure memory (optional, for resource-constrained CI)
container.with_env("NEO4J_dbms_memory_heap_initial__size", "256m")
container.with_env("NEO4J_dbms_memory_heap_max__size", "512m")

# Start container
container.start()

# Get connection URL
uri = container.get_connection_url()
# Returns: "bolt://localhost:7687" (or similar with mapped port)
```

## Schema Management

### Schema Definition

Unlike Placement's Alembic migrations, Tachyon uses Cypher scripts for schema:

```python
# tachyon/db/schema.py

SCHEMA_STATEMENTS = [
    # Uniqueness constraints (also create indexes)
    "CREATE CONSTRAINT resource_provider_uuid IF NOT EXISTS "
    "FOR (rp:ResourceProvider) REQUIRE rp.uuid IS UNIQUE",

    "CREATE CONSTRAINT consumer_uuid IF NOT EXISTS "
    "FOR (c:Consumer) REQUIRE c.uuid IS UNIQUE",

    "CREATE CONSTRAINT trait_name IF NOT EXISTS "
    "FOR (t:Trait) REQUIRE t.name IS UNIQUE",

    "CREATE CONSTRAINT resource_class_name IF NOT EXISTS "
    "FOR (rc:ResourceClass) REQUIRE rc.name IS UNIQUE",

    # Additional indexes for query performance
    "CREATE INDEX resource_provider_name IF NOT EXISTS "
    "FOR (rp:ResourceProvider) ON (rp.name)",

    "CREATE INDEX aggregate_uuid IF NOT EXISTS "
    "FOR (a:Aggregate) ON (a.uuid)",
]


def create_schema(driver):
    """Create all schema elements."""
    with driver.session() as session:
        for statement in SCHEMA_STATEMENTS:
            session.run(statement)
```

### Schema in Tests

The database fixture creates schema automatically:

```python
def _create_schema(self):
    """Create database schema."""
    from tachyon.db import schema
    with self.driver.session() as session:
        for statement in schema.SCHEMA_STATEMENTS:
            session.run(statement)
```

## Test Data Helpers

### Helper Module

Similar to Placement's `test_base.py`:

```python
# tests/tachyon_tests/functional/db/test_base.py

from oslo_utils import uuidutils


def create_resource_provider(driver, name, uuid=None, parent_uuid=None):
    """Create a resource provider.

    Args:
        driver: Neo4j driver
        name: Provider name
        uuid: Provider UUID (generated if not provided)
        parent_uuid: Parent provider UUID (optional)

    Returns:
        Dict with provider properties
    """
    uuid = uuid or uuidutils.generate_uuid()

    with driver.session() as session:
        if parent_uuid:
            result = session.run("""
                MATCH (parent:ResourceProvider {uuid: $parent_uuid})
                CREATE (rp:ResourceProvider {
                    uuid: $uuid,
                    name: $name,
                    generation: 0
                })
                CREATE (parent)-[:PARENT_OF]->(rp)
                RETURN rp
            """, uuid=uuid, name=name, parent_uuid=parent_uuid)
        else:
            result = session.run("""
                CREATE (rp:ResourceProvider {
                    uuid: $uuid,
                    name: $name,
                    generation: 0
                })
                RETURN rp
            """, uuid=uuid, name=name)

        record = result.single()
        return dict(record["rp"])


def add_inventory(driver, rp_uuid, resource_class, total, **kwargs):
    """Add inventory to a resource provider.

    Args:
        driver: Neo4j driver
        rp_uuid: Resource provider UUID
        resource_class: Resource class name (e.g., 'VCPU')
        total: Total amount of resource
        **kwargs: Optional inventory attributes

    Returns:
        Dict with inventory properties
    """
    defaults = {
        'reserved': 0,
        'min_unit': 1,
        'max_unit': total,
        'step_size': 1,
        'allocation_ratio': 1.0,
    }
    defaults.update(kwargs)

    with driver.session() as session:
        result = session.run("""
            MATCH (rp:ResourceProvider {uuid: $rp_uuid})
            CREATE (rp)-[:HAS_INVENTORY]->(inv:Inventory {
                resource_class: $resource_class,
                total: $total,
                reserved: $reserved,
                min_unit: $min_unit,
                max_unit: $max_unit,
                step_size: $step_size,
                allocation_ratio: $allocation_ratio
            })
            RETURN inv
        """, rp_uuid=rp_uuid, resource_class=resource_class,
            total=total, **defaults)

        record = result.single()
        return dict(record["inv"])


def set_traits(driver, rp_uuid, traits):
    """Set traits on a resource provider.

    Args:
        driver: Neo4j driver
        rp_uuid: Resource provider UUID
        traits: List of trait names
    """
    with driver.session() as session:
        # Clear existing traits
        session.run("""
            MATCH (rp:ResourceProvider {uuid: $rp_uuid})-[r:HAS_TRAIT]->()
            DELETE r
        """, rp_uuid=rp_uuid)

        # Add new traits
        for trait_name in traits:
            session.run("""
                MATCH (rp:ResourceProvider {uuid: $rp_uuid})
                MERGE (t:Trait {name: $trait_name})
                CREATE (rp)-[:HAS_TRAIT]->(t)
            """, rp_uuid=rp_uuid, trait_name=trait_name)


def create_consumer(driver, uuid=None, project_id=None, user_id=None):
    """Create a consumer.

    Args:
        driver: Neo4j driver
        uuid: Consumer UUID (generated if not provided)
        project_id: Project ID (generated if not provided)
        user_id: User ID (generated if not provided)

    Returns:
        Dict with consumer properties
    """
    uuid = uuid or uuidutils.generate_uuid()
    project_id = project_id or uuidutils.generate_uuid()
    user_id = user_id or uuidutils.generate_uuid()

    with driver.session() as session:
        result = session.run("""
            MERGE (p:Project {uuid: $project_id})
            MERGE (u:User {uuid: $user_id})
            CREATE (c:Consumer {
                uuid: $uuid,
                generation: 0
            })
            CREATE (c)-[:OWNED_BY]->(p)
            CREATE (c)-[:CREATED_BY]->(u)
            RETURN c
        """, uuid=uuid, project_id=project_id, user_id=user_id)

        record = result.single()
        return dict(record["c"])


def set_allocations(driver, consumer_uuid, allocations):
    """Set allocations for a consumer.

    Args:
        driver: Neo4j driver
        consumer_uuid: Consumer UUID
        allocations: List of dicts with rp_uuid, resource_class, used
    """
    with driver.session() as session:
        # Clear existing allocations
        session.run("""
            MATCH (c:Consumer {uuid: $consumer_uuid})-[r:CONSUMES]->()
            DELETE r
        """, consumer_uuid=consumer_uuid)

        # Create new allocations
        for alloc in allocations:
            session.run("""
                MATCH (c:Consumer {uuid: $consumer_uuid})
                MATCH (rp:ResourceProvider {uuid: $rp_uuid})
                      -[:HAS_INVENTORY]->(inv:Inventory {resource_class: $rc})
                CREATE (c)-[:CONSUMES {used: $used}]->(inv)
            """, consumer_uuid=consumer_uuid,
                rp_uuid=alloc['rp_uuid'],
                rc=alloc['resource_class'],
                used=alloc['used'])
```

## Test Patterns

### Unit Tests (Mocked Driver)

For unit tests, mock the Neo4j driver:

```python
from unittest import mock

from tachyon_tests.unit import base


class TestResourceProvider(base.TestCase):

    def setUp(self):
        super().setUp()
        self.mock_driver = mock.MagicMock()
        self.mock_session = mock.MagicMock()
        self.mock_driver.session.return_value.__enter__ = mock.MagicMock(
            return_value=self.mock_session
        )

    def test_create_provider(self):
        # Test with mocked database
        pass
```

### Functional Tests (Real Database)

For functional tests, use the database fixture:

```python
from tachyon_tests.functional import base
from tachyon_tests.functional.db import test_base as tb


class TestResourceProvider(base.TestCase):

    def test_create_provider(self):
        # Use real Neo4j via fixture
        rp = tb.create_resource_provider(
            self.db.driver,
            name='test-rp'
        )

        self.assertIsNotNone(rp['uuid'])

    def test_provider_hierarchy(self):
        parent = tb.create_resource_provider(
            self.db.driver,
            name='parent'
        )

        child = tb.create_resource_provider(
            self.db.driver,
            name='child',
            parent_uuid=parent['uuid']
        )

        # Verify relationship
        with self.db.driver.session() as session:
            result = session.run("""
                MATCH (parent:ResourceProvider {uuid: $parent_uuid})
                      -[:PARENT_OF]->
                      (child:ResourceProvider {uuid: $child_uuid})
                RETURN child
            """, parent_uuid=parent['uuid'], child_uuid=child['uuid'])

            self.assertEqual(result.single()["child"]["name"], "child")
```

## Performance Considerations

### Container Reuse

Starting a Neo4j container takes 5-15 seconds. Enable container reuse:

```python
class Neo4jDatabase(fixtures.Fixture):
    _shared_container = None
    _container_reuse = True  # Enable reuse
```

With reuse, only the first test class pays startup cost. Subsequent classes reuse the container and clear data.

### Clear vs Restart

| Approach | Time | Isolation |
|----------|------|-----------|
| Clear data (`MATCH (n) DETACH DELETE n`) | ~100ms | Good (same schema) |
| Restart container | ~10-15s | Perfect |

Use clearing for speed, restart only if schema changes.

### Parallel Test Execution

Each parallel test worker needs its own container. testcontainers handles this automatically with different ports.

```bash
# Run with 4 workers
tox -e functional -- --concurrency 4
```

## CI/CD Considerations

### Docker Requirement

testcontainers requires Docker. CI systems must have Docker available:

```yaml
# .zuul.yaml example
- job:
    name: tachyon-functional
    parent: openstack-tox-functional
    required-projects:
      - openstack/tachyon
    pre-run: playbooks/docker-setup.yaml  # Ensure Docker is available
```

### Resource Limits

CI runners may have limited resources. Configure Neo4j memory:

```python
container.with_env("NEO4J_dbms_memory_heap_initial__size", "256m")
container.with_env("NEO4J_dbms_memory_heap_max__size", "512m")
container.with_env("NEO4J_dbms_memory_pagecache_size", "100m")
```

### Container Cleanup

Ensure containers are stopped after tests:

```python
# conftest.py or test setup
import atexit
from tachyon_tests.local_fixtures import database

atexit.register(database.Neo4jDatabase.stop_shared_container)
```

## References

- [testcontainers-python](https://testcontainers-python.readthedocs.io/)
- [Neo4j Python Driver](https://neo4j.com/docs/python-manual/current/)
- [neo4j-python-driver tests](../../ref/src/neo4j-python-driver/tests/) - Integration test patterns
