---
title: Gabbi Tests
description: Placement API compatibility testing using Gabbi YAML tests
keywords: [gabbi, yaml, api-testing, placement, compatibility, wsgi-intercept, flask]
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

> **Note**: Gabbi integrates with Tachyon's Flask application via wsgi-intercept. For Flask application details, see [Technology Stack](../00-overview/technology-stack.md#rest-api-framework-flask).

## Why Gabbi?

1. **Declarative YAML**: Tests are readable, maintainable specifications
2. **Placement Compatibility**: Reuse existing Placement tests with minimal changes
3. **OpenStack Standard**: Used by Placement, Gnocchi, and other projects
4. **In-Process Testing**: Uses wsgi-intercept for fast, isolated tests

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
│  - intercept=setup_app → Flask app via wsgi-intercept       │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│  APIFixture (local_fixtures/gabbits.py)                     │
│  - Sets up config, database, policy                         │
│  - Populates os.environ with test UUIDs                     │
│  - Provides setup_app() returning Flask app                 │
└─────────────────────────┬───────────────────────────────────┘
                          │
             ┌────────────┴────────────┐
             │                         │
      ┌──────▼──────┐          ┌───────▼────────────────────┐
      │ Neo4j       │          │ wsgi-intercept             │
      │ Container   │          │ ┌─────────────────────────┐│
      │ (testcon-   │          │ │  Flask Application      ││
      │  tainers)   │          │ │  create_app(TESTING=T)  ││
      └─────────────┘          │ │  - Blueprints (routes)  ││
                               │ │  - Middleware           ││
                               │ └─────────────────────────┘│
                               │ Intercepts HTTP → WSGI     │
                               └────────────────────────────┘
```

### How wsgi-intercept Works

wsgi-intercept intercepts HTTP calls at the socket level and routes them directly to the WSGI application in-process:

```
HTTP Request (Gabbi)
        │
        ▼
┌───────────────────┐
│ wsgi-intercept    │
│ Patches httplib   │
│ HTTPConnection    │
└───────┬───────────┘
        │ No network I/O
        ▼
┌───────────────────┐
│ Flask WSGI App    │
│ create_app()      │
└───────────────────┘
```

This provides:
- **Speed**: No network overhead, tests run faster
- **Isolation**: No port conflicts, multiple test processes can run in parallel
- **Simplicity**: No server process to manage

## Test Loader

**File**: `tests/tachyon_tests/functional/test_api.py`

```python
"""Gabbi test loader for Tachyon API tests.

This module integrates Gabbi with Flask via wsgi-intercept, enabling
declarative YAML-based API testing without network overhead.
"""

import os

from gabbi import driver
from oslotest import output
import wsgi_intercept

from tachyon_tests.functional.local_fixtures import gabbits as fixtures
from tachyon_tests.local_fixtures import logging as capture

# Enforce native str for response headers (required for compatibility)
wsgi_intercept.STRICT_RESPONSE_HEADERS = True

TESTS_DIR = 'gabbits'


def load_tests(loader, tests, pattern):
    """Provide a TestSuite to the discovery process.
    
    This is the standard Python unittest load_tests protocol.
    Called by test runners (stestr, unittest discover).
    
    The key integration point is the `intercept` parameter, which
    receives a factory function that returns the Flask WSGI application.
    Gabbi uses wsgi-intercept to route HTTP requests to this app.
    
    Args:
        loader: unittest.TestLoader instance
        tests: Existing TestSuite (ignored, Gabbi builds its own)
        pattern: Pattern for test discovery (ignored)
    
    Returns:
        TestSuite containing Gabbi tests generated from YAML files
    """
    test_dir = os.path.join(os.path.dirname(__file__), TESTS_DIR)
    
    # Per-test fixtures (applied to each individual test)
    inner_fixtures = [
        output.CaptureOutput,
        capture.Logging,
    ]
    
    return driver.build_tests(
        test_dir,                          # Directory with YAML files
        loader,                            # unittest.TestLoader
        host=None,                         # No real host (wsgi-intercept handles routing)
        test_loader_name=__name__,         # Module name for test naming
        intercept=fixtures.setup_app,      # Flask app factory (returns WSGI callable)
        inner_fixtures=inner_fixtures,     # Per-test fixtures
        fixture_module=fixtures            # Module with GabbiFixture classes
    )
```

### Flask Integration via setup_app

The `intercept` parameter receives a factory function that returns the Flask WSGI application:

```python
# In local_fixtures/gabbits.py
def setup_app():
    """WSGI app factory for Gabbi.
    
    Called by Gabbi when a test needs to make an HTTP request.
    wsgi-intercept routes the request to this Flask app.
    
    Returns:
        Flask WSGI application callable
    """
    from tachyon.api import create_app
    
    flask_config = {
        'TESTING': True,
        'AUTH_STRATEGY': 'noauth2',
        'NEO4J_URI': DB_FIXTURE.uri if DB_FIXTURE else None,
    }
    
    return create_app(flask_config)
```
```

### Key Parameters

| Parameter | Purpose |
|-----------|---------|
| `test_dir` | Directory containing YAML files |
| `intercept` | Function returning WSGI app (uses wsgi-intercept) |
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

If tests need new UUIDs, update `APIFixture._setup_environ()`:

```python
def _setup_environ(self):
    # ... existing ...
    os.environ['MY_NEW_UUID'] = uuidutils.generate_uuid()
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
        # Create data in Neo4j
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
- [wsgi-intercept](https://github.com/cdent/wsgi-intercept) - In-process WSGI testing
- [Placement gabbits/](../../ref/src/placement/placement/tests/functional/gabbits/) - Original test files
- [Flask Testing](../../ref/src/flask/docs/testing.rst) - Flask test client documentation
- [Technology Stack](../00-overview/technology-stack.md) - Flask application factory pattern

