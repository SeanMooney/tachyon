---
title: Gabbi Tests
description: Placement API compatibility testing using Gabbi YAML tests
keywords: [gabbi, yaml, api-testing, placement, compatibility, flask, werkzeug]
related:
  - 08-testing/README.md
  - 08-testing/fixtures.md
  - 06-migration/api-mapping.md
  - 00-overview/technology-stack.md
implements: []
section: testing
---

# Gabbi Tests

Tachyon uses [Gabbi](https://gabbi.readthedocs.io/) for declarative HTTP API testing, reusing Placement's test suite to verify API compatibility.

> **Note**: Gabbi makes real HTTP requests to a Flask development server running in a separate thread. For Flask application details, see [Technology Stack](../00-overview/technology-stack.md#rest-api-framework-flask).

## Why Gabbi?

1. **Declarative YAML**: Tests are readable, maintainable specifications
2. **Placement Compatibility**: Reuse existing Placement tests with minimal changes
3. **OpenStack Standard**: Used by Placement, Gnocchi, and other projects
4. **Real HTTP Testing**: Tests go through the actual HTTP stack for realistic behavior

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Gabbi YAML Test Files (gabbits/*.yaml)                     │
│  - Declarative HTTP test definitions                        │
│  - Environment variable substitution ($ENVIRON['...'])      │
│  - Sequential test ordering within files                    │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│  Test Loader (test_api.py)                                  │
│  - gabbi.driver.build_tests()                               │
│  - Discovers YAML files in gabbits/                         │
│  - Creates Python test cases                                │
│  - host='127.0.0.1', port=TEST_PORT → Flask server          │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│  APIFixture (local_fixtures/gabbits.py)                     │
│  - Starts Neo4j container (testcontainers)                  │
│  - Creates Flask app with Neo4j config                      │
│  - Starts Flask server in separate thread                   │
│  - Populates os.environ with test UUIDs                     │
└─────────────────────────┬───────────────────────────────────┘
                          │
             ┌────────────┴────────────┐
             │                         │
      ┌──────▼──────┐          ┌───────▼────────────────────┐
      │ Neo4j       │          │ Flask Dev Server (Thread)  │
      │ Container   │          │ ┌─────────────────────────┐│
      │ (testcon-   │          │ │  Flask Application      ││
      │  tainers)   │          │ │  create_app(TESTING=T)  ││
      └─────────────┘          │ │  - Blueprints (routes)  ││
                               │ │  - Middleware           ││
                               │ └─────────────────────────┘│
                               │ werkzeug.serving.make_server│
                               │ Listens on 127.0.0.1:PORT   │
                               └────────────────────────────┘
```

### How the Threaded Server Works

Each test file gets its own Flask development server running in a separate thread:

```
Test Discovery (module load)
        │
        ▼
┌───────────────────┐
│ get_free_port()   │
│ Allocate TEST_PORT│
└───────┬───────────┘
        │
        ▼
┌───────────────────┐
│ build_tests()     │
│ host='127.0.0.1'  │
│ port=TEST_PORT    │
└───────┬───────────┘
        │
Test Execution (fixture runs)
        │
        ▼
┌───────────────────┐
│ APIFixture        │
│ .start_fixture()  │
│ - Start Neo4j     │
│ - Create Flask app│
│ - Start server    │
│   in thread       │
└───────┬───────────┘
        │
        ▼
┌───────────────────┐
│ HTTP Requests     │
│ (Gabbi tests)     │
│ → 127.0.0.1:PORT  │
└───────────────────┘
```

This provides:
- **Isolation**: Each stestr worker process gets its own port
- **Realistic Testing**: Tests go through actual HTTP stack
- **Concurrent Safety**: No shared global state between test files
- **Simplicity**: No interception or monkey-patching required

## Test Loader

**File**: `tests/tachyon_tests/functional/test_api.py`

```python
"""Gabbi test loader for Tachyon API."""

import os

from gabbi import driver
from oslotest import output

from tachyon_tests.functional.local_fixtures import gabbits as fixtures
from tachyon_tests.local_fixtures import logging as capture

TESTS_DIR = "gabbits"


def load_tests(loader, tests, pattern):
    """Provide a TestSuite to the discovery process.

    This is the standard Python unittest load_tests protocol.
    Called by test runners (stestr, unittest discover).

    Tests are directed to a Flask server running on 127.0.0.1:TEST_PORT.
    The TEST_PORT is allocated at module import time, ensuring each
    stestr worker process gets its own unique port.

    Args:
        loader: unittest.TestLoader instance
        tests: Existing TestSuite (ignored, Gabbi builds its own)
        pattern: Pattern for test discovery (ignored)

    Returns:
        TestSuite containing Gabbi tests generated from YAML files
    """
    test_dir = os.path.join(os.path.dirname(__file__), TESTS_DIR)

    inner_fixtures = [
        output.CaptureOutput,
        capture.Logging,
    ]

    return driver.build_tests(
        test_dir,
        loader,
        host='127.0.0.1',
        port=fixtures.TEST_PORT,
        test_loader_name=__name__,
        inner_fixtures=inner_fixtures,
        fixture_module=fixtures,
    )
```

### Flask Server Integration via APIFixture

The `APIFixture` class manages the Flask server lifecycle:

```python
# In local_fixtures/gabbits.py
from werkzeug.serving import make_server

class APIFixture(gabbi_fixture.GabbiFixture):
    def start_fixture(self):
        """Start Neo4j and Flask server before tests run."""
        # Start Neo4j container
        self.db_fixture = Neo4jFixture()
        self.db_fixture.setUp()

        # Create Flask app with Neo4j config
        self.app = create_app({
            "TESTING": True,
            "NEO4J_URI": self.db_fixture.uri,
            # ...
        })

        # Start Flask in a separate thread
        self.server = make_server('127.0.0.1', TEST_PORT, self.app, threaded=True)
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()

    def stop_fixture(self):
        """Shutdown server and cleanup after tests complete."""
        self.server.shutdown()
        self.server_thread.join(timeout=5)
        self.db_fixture.cleanUp()
```

### Key Parameters

| Parameter | Purpose |
|-----------|---------|
| `test_dir` | Directory containing YAML files |
| `host` | Hostname of Flask server (127.0.0.1) |
| `port` | Port of Flask server (dynamically allocated) |
| `fixture_module` | Module containing `GabbiFixture` subclasses |
| `inner_fixtures` | Applied to each individual test |
| `test_loader_name` | Used to name generated test methods |

## YAML Test Structure

### Basic Structure

```yaml
# File: gabbits/resource-provider.yaml

fixtures:
    - APIFixture  # Uses APIFixture from local_fixtures/gabbits.py

defaults:
    request_headers:
        x-auth-token: admin
        accept: application/json
        openstack-api-version: placement latest

tests:

- name: list empty resource providers
  GET: /resource_providers
  status: 200
  response_json_paths:
      $.resource_providers: []

- name: create resource provider
  POST: /resource_providers
  request_headers:
      content-type: application/json
  data:
      name: $ENVIRON['RP_NAME']
      uuid: $ENVIRON['RP_UUID']
  status: 200
  response_json_paths:
      $.uuid: $ENVIRON['RP_UUID']
      $.name: $ENVIRON['RP_NAME']

- name: get created provider
  GET: $LOCATION  # Uses Location header from previous test
  status: 200
  response_json_paths:
      $.uuid: $ENVIRON['RP_UUID']
```

### YAML Elements

| Element | Purpose |
|---------|---------|
| `fixtures` | List of `GabbiFixture` class names to use |
| `defaults` | Default headers/settings for all tests |
| `tests` | List of test cases (run sequentially) |

### Test Case Elements

| Element | Purpose |
|---------|---------|
| `name` | Descriptive name (required) |
| `GET`, `POST`, etc. | HTTP method and URL |
| `request_headers` | Headers to send |
| `data` | Request body (JSON or string) |
| `status` | Expected HTTP status code |
| `response_headers` | Expected response headers (regex allowed) |
| `response_json_paths` | JSONPath assertions on response body |
| `response_strings` | Strings expected in response body |

### Special Substitutions

| Substitution | Purpose |
|--------------|---------|
| `$ENVIRON['VAR']` | Environment variable value |
| `$LOCATION` | Location header from previous response |
| `$RESPONSE['$.path']` | JSONPath into previous response |
| `$HISTORY['test-name'].<attr>` | Data from named earlier test |
| `/regex/` | Regex pattern in assertions |

## Placement Test Adaptation

### Source Files

Placement has 79 Gabbi YAML test files in `placement/tests/functional/gabbits/`. Tachyon adapts these in phases.

### Phase 1: Core API (Priority: High)

| File | Tests | Adaptations |
|------|-------|-------------|
| `basic-http.yaml` | HTTP behavior, errors | Minimal - same API surface |
| `resource-provider.yaml` | RP CRUD, parent/child | Graph model for hierarchy |
| `inventory.yaml` | Inventory management | HAS_INVENTORY relationships |
| `traits.yaml` | Trait CRUD | May use Neo4j labels |
| `allocations.yaml` | Allocation workflows | CONSUMES relationships |
| `resource-classes.yaml` | Resource class CRUD | ResourceClass nodes |

### Phase 2: Advanced Features (Priority: Medium)

| File | Tests | Adaptations |
|------|-------|-------------|
| `aggregate.yaml` | Aggregate management | MEMBER_OF relationships |
| `usage.yaml` | Usage reporting | Aggregate from CONSUMES |
| `allocation-candidates.yaml` | Scheduling queries | Cypher translation |
| `traits-*.yaml` | Trait filtering | Graph pattern matching |

### Phase 3: RBAC and Edge Cases (Priority: Lower)

| File | Tests | Adaptations |
|------|-------|-------------|
| `*-legacy-rbac.yaml` | Legacy policy tests | Same policy rules |
| `*-secure-rbac.yaml` | Secure RBAC tests | Same policy rules |
| `*-policy.yaml` | Policy enforcement | Same policy rules |
| `microversion*.yaml` | API versioning | Same microversion handling |

### Adaptation Patterns

#### 1. Keep YAML Structure Identical

Preserve test structure where possible to maintain compatibility:

```yaml
# Original Placement test
- name: create resource provider
  POST: /resource_providers
  data:
      name: $ENVIRON['RP_NAME']
      uuid: $ENVIRON['RP_UUID']
  status: 200

# Tachyon test - IDENTICAL
- name: create resource provider
  POST: /resource_providers
  data:
      name: $ENVIRON['RP_NAME']
      uuid: $ENVIRON['RP_UUID']
  status: 200
```

#### 2. Update Fixture Data Creation

Fixtures use Neo4j instead of SQLAlchemy:

```python
# Placement fixture
def start_fixture(self):
    rp = rp_obj.ResourceProvider(self.context, name=name, uuid=uuid)
    rp.create()

# Tachyon fixture
def start_fixture(self):
    with self.db_fixture.driver.session() as session:
        session.run("""
            CREATE (rp:ResourceProvider {uuid: $uuid, name: $name, generation: 0})
        """, uuid=uuid, name=name)
```

#### 3. Document Graph-Specific Deviations

When responses differ due to graph model, document in comments:

```yaml
- name: get provider with root_provider_uuid
  GET: /resource_providers/$ENVIRON['RP_UUID']
  response_json_paths:
      $.uuid: $ENVIRON['RP_UUID']
      # Tachyon: root_provider_uuid computed via graph traversal
      $.root_provider_uuid: $ENVIRON['RP_UUID']
```

#### 4. Leverage Graph for Complex Queries

Allocation candidates benefit from graph queries:

```yaml
# Same test, but Tachyon uses Cypher internally
- name: get allocation candidates
  GET: /allocation_candidates?resources=VCPU:1
  response_json_paths:
      $.allocation_requests.`len`: 1
```

## Test Execution

### Running Gabbi Tests

```bash
# All Gabbi tests
tox -e functional

# Specific YAML file (by generated class name)
tox -e functional -- tachyon_tests.functional.test_api.ResourceProviderGabbits

# Specific test within file
tox -e functional -- tachyon_tests.functional.test_api.ResourceProviderGabbits.test_010_create_resource_provider
```

### Test Naming Convention

Gabbi generates test names from YAML:

```
{module}.{YamlFileClass}.test_{index}_{sanitized_name}

Example:
tachyon_tests.functional.test_api.ResourceProviderGabbits.test_010_create_resource_provider
```

### Parallel Execution

Tests within a YAML file run sequentially (order matters). Different YAML files run in parallel.

stestr's `group_regex` ensures proper grouping:

```toml
# pyproject.toml
[tool.stestr]
group_regex = "tachyon_tests\\.functional\\.test_api(?:\\.|_)([^_]+)"
```

This captures the YAML filename, grouping tests from the same file.

### Concurrent Safety

The threaded server approach provides isolation for concurrent execution:

- **Port Allocation**: Each stestr worker process allocates its own `TEST_PORT` at module import time
- **No Global State**: Each fixture manages its own server instance
- **Sequential Within File**: Tests in a YAML file share a server, running sequentially
- **Parallel Across Files**: Different YAML files can run in separate processes

## Creating New Tests

### 1. Create YAML File

```yaml
# tests/tachyon_tests/functional/gabbits/my-feature.yaml

fixtures:
    - APIFixture

defaults:
    request_headers:
        x-auth-token: admin
        accept: application/json

tests:

- name: test my feature
  POST: /my-endpoint
  data:
      key: value
  status: 201
```

### 2. Add Required Environment Variables

If tests need new UUIDs, update `APIFixture.start_fixture()`:

```python
def start_fixture(self):
    # ... existing setup ...
    os.environ['MY_NEW_UUID'] = str(uuid.uuid4())
```

### 3. Create Specialized Fixture (if needed)

For tests requiring pre-populated data:

```python
class MyFeatureFixture(APIFixture):
    """Fixture with pre-created data for my-feature tests."""

    def start_fixture(self):
        super().start_fixture()
        self._create_my_data()

    def _create_my_data(self):
        # Create data in Neo4j via app context
        with self.app.app_context():
            # ... create data ...
            pass
```

### 4. Reference in YAML

```yaml
fixtures:
    - MyFeatureFixture
```

## Debugging Gabbi Tests

### Enable Debug Logging

```bash
OS_LOG_CAPTURE=0 OS_DEBUG=1 tox -e functional -- test_api.ResourceProviderGabbits
```

### Inspect Request/Response

Add `verbose: all` to a test:

```yaml
- name: debug this test
  verbose: all
  GET: /resource_providers
```

### Run Single Test

```bash
tox -e functional -- test_api.ResourceProviderGabbits.test_010_create_resource_provider
```

## References

- [Gabbi Documentation](https://gabbi.readthedocs.io/)
- [Placement Gabbi Tests](../../placement-gabbi-tests.md) - Comprehensive analysis
- [Werkzeug Development Server](https://werkzeug.palletsprojects.com/en/latest/serving/) - Server used by Flask
- [Placement gabbits/](../../ref/src/placement/placement/tests/functional/gabbits/) - Original test files
- [Flask Testing](../../ref/src/flask/docs/testing.rst) - Flask test client documentation
- [Technology Stack](../00-overview/technology-stack.md) - Flask application factory pattern
