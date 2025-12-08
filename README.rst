Tachyon (MVP)
=============

Tachyon is a Neo4j-backed scheduling and resource management system providing
Placement API compatibility with a graph-native data model.

This MVP implements core Placement API resources with generation-based optimistic
concurrency, tested via Gabbi functional tests following OpenStack PTI conventions.

Features
--------

- **Resource Providers**: CRUD with hierarchical parent/child relationships
- **Inventories**: Per-provider resource inventories with capacity tracking
- **Traits**: Qualitative capabilities for providers (CUSTOM_*, standard traits)
- **Resource Classes**: Standard (VCPU, MEMORY_MB) and custom resource types
- **Allocations**: Consumer allocations with generation-based concurrency
- **Usages**: Per-provider and per-project usage aggregation

API Compatibility
-----------------

Responses follow Placement API format including:

- Structured error responses (``{"errors": [{"status": N, "title": "...", "detail": "..."}]}``)
- ``root_provider_uuid`` and ``parent_provider_uuid`` in resource provider responses
- Generation-based optimistic concurrency (409 Conflict on mismatch)

Getting Started
---------------

**Prerequisites**: Python 3.10+, Docker (for Neo4j testcontainers)

1. Create a virtualenv and install dependencies::

      python -m venv .venv
      source .venv/bin/activate
      pip install -r requirements.txt -r test-requirements.txt -e .

2. Run unit tests::

      tox -e py3

3. Run functional tests (requires Docker)::

      tox -e functional

4. Run with external Neo4j (skip testcontainers)::

      export TACHYON_NEO4J_URI=bolt://localhost:7687
      export TACHYON_NEO4J_USERNAME=neo4j
      export TACHYON_NEO4J_PASSWORD=password
      tox -e functional

5. Run style checks::

      tox -e pep8

WSGI Deployment
---------------

For production deployment with gunicorn or uWSGI, use the module path::

    # gunicorn
    gunicorn -w 4 -b 0.0.0.0:8778 tachyon.wsgi.api:application

    # uWSGI
    [uwsgi]
    module = tachyon.wsgi.api:application

Known Limitations
-----------------

- **Allocation Candidates**: The ``GET /allocation_candidates`` endpoint is
  intentionally out of scope for this MVP.
- **Authentication**: Defaults to ``noauth2``; Keystone integration planned.
- **Aggregates**: Aggregate endpoints are stubbed but not fully implemented.

Project Structure
-----------------

::

    src/tachyon/           # Main package
    ├── api/               # Flask blueprints and middleware
    ├── db/                # Neo4j adapter and schema
    ├── conf/              # Configuration module
    └── wsgi/              # WSGI application module

    tests/tachyon_tests/   # Test package
    ├── unit/              # Unit tests
    ├── functional/        # Gabbi functional tests
    └── local_fixtures/    # Test fixtures

License
-------

Apache License, Version 2.0. See ``LICENSE`` file.
