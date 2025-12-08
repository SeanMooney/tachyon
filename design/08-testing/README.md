---
title: Testing Overview
description: Testing philosophy, architecture, and infrastructure for Tachyon
keywords: [testing, unit-tests, functional-tests, gabbi, stestr, pti, fixtures, flask, wsgi-intercept]
related:
  - 06-migration/api-mapping.md
  - 00-overview/design-principles.md
  - 00-overview/technology-stack.md
implements: []
section: testing
---

# Testing Overview

This section documents Tachyon's testing infrastructure, designed to ensure correctness, maintain Placement API compatibility, and comply with OpenStack's Project Testing Interface (PTI).

> **Note**: For core technology choices (Flask API framework, pbr packaging, future uv adoption), see [Technology Stack](../00-overview/technology-stack.md).

## Testing Philosophy

Tachyon follows a layered testing approach with clear separation of concerns:

| Test Type | Purpose | Mocking Level | Database | Speed |
|-----------|---------|---------------|----------|-------|
| **Unit** | Test individual functions/classes | Extensive | None/Mocked | Fast |
| **Functional** | Test component integration | Minimal | Neo4j container | Medium |
| **Integration** | Test full system | None | Real Neo4j | Slow |

### Key Principle: Minimize Mocks, Maximize Reality

In functional tests:
- ✅ Use real Tachyon code (API, database operations)
- ✅ Use real database operations (Neo4j testcontainer)
- ✅ Use real WSGI application (wsgi-intercept)
- ❌ Mock external services (Keystone, etc.)
- ❌ Mock network I/O to external systems

## Design Decisions

### 1. src Layout

Tachyon uses the [src layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/) pattern following OpenStack modern conventions (grian-ui):

- Source code in `src/tachyon/`
- Tests in separate `tests/tachyon_tests/` package
- Prevents accidental imports from source directory during testing
- Clear separation between installable code and test code

### 2. Fixture Naming: `local_fixtures`

Test fixtures are named `local_fixtures` (not `fixtures`) to avoid import conflicts:
- When debugging, tests are added to PYTHONPATH
- A module named `fixtures` would shadow the `fixtures` library
- `local_fixtures` is explicit and avoids this conflict

### 3. Placement API Compatibility Testing

Tachyon reuses Placement's Gabbi YAML tests to verify API compatibility:
- Tests copied and adapted for Neo4j graph backend
- Same test structure ensures behavioral compatibility
- Deviations documented explicitly in test comments

### 4. Neo4j Testcontainers

Database isolation achieved via testcontainers:
- Fresh Neo4j container per test class
- Community edition (no license required for CI)
- Schema created via Cypher scripts (not migrations)

## Test Technology Stack

See [Technology Stack](../00-overview/technology-stack.md) for core project technologies (Flask, pbr, Neo4j).

| Component | Technology | Purpose |
|-----------|------------|---------|
| API Framework | [Flask](https://flask.palletsprojects.com/) | REST API (see [technology-stack.md](../00-overview/technology-stack.md)) |
| Test Runner | [stestr](https://stestr.readthedocs.io/) | PTI compliance, parallel execution |
| Framework | [testtools](https://testtools.readthedocs.io/) + [fixtures](https://pypi.org/project/fixtures/) | OpenStack standard, cleanup management |
| API Testing | [Gabbi](https://gabbi.readthedocs.io/) + [wsgi-intercept](https://github.com/cdent/wsgi-intercept) | Declarative YAML HTTP tests |
| Database | [testcontainers](https://testcontainers.com/) | Isolated Neo4j containers |
| Coverage | [coverage.py](https://coverage.readthedocs.io/) | PTI requirement |
| Linting | [pre-commit](https://pre-commit.com/) (ruff, mypy) | PEP8 compliance |

## Section Contents

| Document | Description |
|----------|-------------|
| [project-structure.md](project-structure.md) | src layout and directory organization |
| [fixtures.md](fixtures.md) | Fixture architecture and patterns |
| [gabbi-tests.md](gabbi-tests.md) | Placement API compatibility testing |
| [neo4j-testing.md](neo4j-testing.md) | Database testing with testcontainers |
| [pti-compliance.md](pti-compliance.md) | OpenStack PTI requirements mapping |

## Reference Materials

This testing design is informed by patterns from:

| Reference | Key Patterns Adopted |
|-----------|---------------------|
| [Placement Gabbi Tests](../../placement-gabbi-tests.md) | Gabbi fixture structure, test loader, environment variables |
| [Nova Functional Tests](../../funtional-testing.md) | Multi-fixture composition, service lifecycle |
| [Watcher Plan](../../watcher-functional-testing-plan.md) | Phased approach, API testing |
| [grian-ui](../../ref/src/grian-ui) | src layout, tox configuration |
| [neo4j-python-driver](../../ref/src/neo4j-python-driver) | pytest fixtures, testkit patterns |
| [Flask Testing](../../ref/src/flask/docs/testing.rst) | Test client, application factory |
| [wsgi-intercept](../../ref/src/wsgi-intercept) | In-process WSGI interception for Gabbi |

## Quick Start

### Running Tests

```bash
# Unit tests
tox -e py312

# Functional tests (requires Docker for Neo4j container)
tox -e functional

# All tests with coverage
tox -e cover

# Specific test
tox -e functional -- tachyon_tests.functional.test_api.ResourceProviderGabbits
```

### Writing Tests

1. **Unit tests**: Place in `tests/tachyon_tests/unit/`, use extensive mocking
2. **Functional tests**: Place in `tests/tachyon_tests/functional/`, use real database
3. **Gabbi tests**: Add YAML files to `tests/tachyon_tests/functional/gabbits/`

See [fixtures.md](fixtures.md) for fixture usage patterns.

