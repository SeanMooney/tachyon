---
title: Technology Stack
description: Core technology choices - Flask, pbr, Neo4j, oslo.* ecosystem, and future uv consideration
keywords: [flask, pbr, uv, packaging, api, wsgi, build-system, pyproject, neo4j, oslo, middleware, keystone, authentication, policy, rbac, logging, context, concurrency, stevedore, plugins]
related:
  - 00-overview/design-principles.md
  - 08-testing/README.md
  - 06-migration/api-mapping.md
implements: []
section: overview
---

# Technology Stack

This document describes Tachyon's core technology choices and their rationale. These decisions form the foundation for the project's architecture, development workflow, and deployment patterns.

## Overview

| Component | Technology | Purpose |
|-----------|------------|---------|
| REST API Framework | Flask | HTTP API endpoints, Placement API compatibility |
| Build/Packaging | pbr | OpenStack-standard packaging, version management |
| Database | Neo4j | Graph-based resource modeling |
| OpenStack Libraries | oslo.* ecosystem | Cross-cutting concerns (config, logging, auth, policy) |
| Future Tooling | uv | Faster dependency resolution (planned) |

## REST API Framework: Flask

Tachyon uses [Flask](https://flask.palletsprojects.com/) as its REST API framework, providing Placement API compatibility with a modern, well-maintained foundation.

### Why Flask?

| Factor | Flask | Pecan | FastAPI |
|--------|-------|-------|---------|
| **Maintenance** | Actively maintained, large community | Limited maintenance | Actively maintained |
| **OpenStack Fit** | Synchronous, WSGI-native | Synchronous, WSGI-native | Async (ASGI) - poor oslo.* fit |
| **Simplicity** | Minimal boilerplate | More complex setup | More complex for sync workloads |
| **Testing** | Excellent built-in test client | Requires WebTest | Requires TestClient |
| **Learning Curve** | Gentle | Moderate | Moderate |

**Decision**: Flask provides the best balance of simplicity, maintenance, and OpenStack ecosystem compatibility. Its synchronous model aligns with oslo.* libraries, and its testing utilities integrate well with our fixture architecture.

### Application Factory Pattern

Tachyon uses Flask's application factory pattern for testability and configuration flexibility:

```python
# src/tachyon/api/app.py
from flask import Flask

def create_app(config=None):
    """Create and configure the Flask application.

    Args:
        config: Optional dict of configuration overrides.
                Typically used for testing (e.g., {'TESTING': True}).

    Returns:
        Configured Flask application instance.
    """
    app = Flask(__name__)

    # Load default configuration
    app.config.from_object('tachyon.api.config.DefaultConfig')

    # Apply overrides
    if config:
        app.config.update(config)

    # Register blueprints
    from tachyon.api.blueprints import (
        resource_providers,
        inventory,
        allocations,
        traits,
        aggregates,
        resource_classes,
    )
    app.register_blueprint(resource_providers.bp)
    app.register_blueprint(inventory.bp)
    app.register_blueprint(allocations.bp)
    app.register_blueprint(traits.bp)
    app.register_blueprint(aggregates.bp)
    app.register_blueprint(resource_classes.bp)

    # Register error handlers
    from tachyon.api import errors
    errors.register_handlers(app)

    # Register middleware
    from tachyon.api import middleware
    middleware.register(app)

    return app
```

### Blueprint Organization

API routes are organized using Flask Blueprints, mapping to Placement API resources:

```
src/tachyon/api/
├── __init__.py
├── app.py                      # create_app() factory
├── config.py                   # Flask configuration
├── errors.py                   # Error handlers
├── middleware.py               # Authentication, microversioning
├── blueprints/
│   ├── __init__.py
│   ├── resource_providers.py   # /resource_providers
│   ├── inventory.py            # /resource_providers/{uuid}/inventories
│   ├── allocations.py          # /allocations, /resource_providers/{uuid}/allocations
│   ├── traits.py               # /traits
│   ├── aggregates.py           # /resource_providers/{uuid}/aggregates
│   └── resource_classes.py     # /resource_classes
└── views/
    ├── __init__.py
    └── common.py               # Shared view utilities
```

Example blueprint:

```python
# src/tachyon/api/blueprints/resource_providers.py
from flask import Blueprint, request, jsonify

bp = Blueprint('resource_providers', __name__, url_prefix='/resource_providers')

@bp.route('', methods=['GET'])
def list_resource_providers():
    """List resource providers with optional filtering."""
    # Implementation
    pass

@bp.route('', methods=['POST'])
def create_resource_provider():
    """Create a new resource provider."""
    # Implementation
    pass

@bp.route('/<uuid:uuid>', methods=['GET'])
def get_resource_provider(uuid):
    """Get a specific resource provider."""
    # Implementation
    pass
```

### Middleware

Tachyon implements Placement-compatible middleware for:

1. **Authentication**: noauth2 for testing, Keystone for production
2. **Microversioning**: `OpenStack-API-Version: placement X.Y` header handling
3. **Request Context**: oslo.context integration

```python
# src/tachyon/api/middleware.py
from flask import request, g

def register(app):
    """Register middleware with the Flask application."""

    @app.before_request
    def authenticate():
        """Validate authentication and set request context."""
        auth_strategy = app.config.get('AUTH_STRATEGY', 'keystone')
        if auth_strategy == 'noauth2':
            g.context = create_noauth_context(request)
        else:
            g.context = validate_keystone_token(request)

    @app.before_request
    def check_microversion():
        """Parse and validate microversion header."""
        header = request.headers.get('OpenStack-API-Version', '')
        g.microversion = parse_microversion(header)
```

### WSGI Deployment

For production, Tachyon exposes a WSGI application callable:

```python
# src/tachyon/deploy.py
from oslo_config import cfg

def loadapp(conf=None):
    """Load the WSGI application for deployment.

    Args:
        conf: oslo.config ConfigOpts instance. If None, uses global CONF.

    Returns:
        WSGI application callable.
    """
    from tachyon.api import create_app

    # Build Flask config from oslo.config
    flask_config = {
        'AUTH_STRATEGY': conf.api.auth_strategy if conf else 'keystone',
        # Additional config mapping
    }

    return create_app(flask_config)

# WSGI callable for gunicorn/uwsgi
application = loadapp(cfg.CONF)
```

Deployment with gunicorn:

```bash
gunicorn -w 4 -b 0.0.0.0:8778 tachyon.deploy:application
```

### Testing with Flask

Flask's test client integrates seamlessly with our fixture architecture:

```python
# Direct test client usage
def test_create_resource_provider(self):
    with self.app.test_client() as client:
        response = client.post('/resource_providers',
            json={'name': 'test-rp', 'uuid': str(uuid.uuid4())},
            headers={'X-Auth-Token': 'admin'})
        assert response.status_code == 200
        assert 'uuid' in response.json

# With wsgi-intercept for Gabbi tests
def setup_app():
    """WSGI app factory for Gabbi."""
    from tachyon.api import create_app
    app = create_app({'TESTING': True})
    return app
```

## Build/Packaging: pbr

Tachyon uses [pbr](https://docs.openstack.org/pbr/latest/) (Python Build Reasonableness) for packaging, the OpenStack-standard build tool required for PTI compliance.

### Why pbr?

1. **OpenStack Standard**: Required for PTI compliance, familiar to contributors
2. **Git-Based Versioning**: Automatic version from tags, no manual version updates
3. **Metadata Generation**: AUTHORS, ChangeLog, MANIFEST.in from git history
4. **requirements.txt Integration**: Direct use of requirements files
5. **Release Notes**: Integration with reno for release note generation

### Configuration

#### pyproject.toml

```toml
[build-system]
requires = ["pbr>=6.1.1", "setuptools>=64.0.0"]
build-backend = "pbr.build"

[project]
name = "tachyon"
description = "Neo4j-backed scheduling and resource management for OpenStack"
readme = "README.rst"
authors = [
    {name = "OpenStack", email = "openstack-discuss@lists.openstack.org"},
]
requires-python = ">=3.10"
license = {text = "Apache-2.0"}
classifiers = [
    "Environment :: OpenStack",
    "Intended Audience :: Information Technology",
    "Intended Audience :: System Administrators",
    "Operating System :: POSIX :: Linux",
    "Programming Language :: Python",
    "Programming Language :: Python :: 3 :: Only",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
]
dynamic = ["version"]

[project.urls]
Homepage = "https://opendev.org/openstack/tachyon"
Documentation = "https://docs.openstack.org/tachyon/latest/"
Repository = "https://opendev.org/openstack/tachyon"

[project.scripts]
tachyon-api = "tachyon.cmd.api:main"
tachyon-manage = "tachyon.cmd.manage:main"

[project.entry-points."oslo.config.opts"]
tachyon = "tachyon.conf:list_opts"

[project.entry-points."oslo.policy.policies"]
tachyon = "tachyon.policies:list_rules"

[tool.setuptools.packages.find]
where = ["src"]
```

#### setup.py

Minimal setup.py required by pbr:

```python
#!/usr/bin/env python
import setuptools

setuptools.setup(pbr=True)
```

#### setup.cfg

```ini
[metadata]
name = tachyon
summary = Neo4j-backed scheduling and resource management for OpenStack

[pbr]
# Automatic features (all enabled by default)
skip_changelog = false
skip_authors = false
skip_reno = false
```

### Version Management

pbr automatically determines version from git tags:

```bash
# Tagged release (v1.0.0)
$ python -c "import pbr.version; print(pbr.version.VersionInfo('tachyon'))"
1.0.0

# Development after tag (3 commits after v1.0.0)
$ python -c "import pbr.version; print(pbr.version.VersionInfo('tachyon'))"
1.0.1.dev3

# Semantic versioning via commit messages
$ git commit -m "Add new feature

Sem-Ver: feature"  # Bumps minor version
```

### Generated Files

pbr automatically generates:

| File | Source | Contents |
|------|--------|----------|
| `AUTHORS` | Git history | All commit authors |
| `ChangeLog` | Git history | Formatted commit log |
| `MANIFEST.in` | Git tracked files | Files for sdist |
| `RELEASENOTES.txt` | reno notes | Compiled release notes |

### Building Packages

```bash
# Source distribution
python -m build -s .
# Creates dist/tachyon-X.Y.Z.tar.gz

# Wheel
python -m build -w .
# Creates dist/tachyon-X.Y.Z-py3-none-any.whl
```

## Future Consideration: uv

[uv](https://github.com/astral-sh/uv) is a modern, Rust-based Python package manager offering significant performance improvements. Tachyon plans a phased adoption while maintaining pbr for OpenStack compatibility.

### Why Consider uv?

| Aspect | pip | uv |
|--------|-----|-----|
| **Installation Speed** | ~30s for deps | ~3s (10x faster) |
| **Resolution Speed** | ~10s | ~0.5s (20x faster) |
| **Lock Files** | requirements.txt | uv.lock (deterministic) |
| **Virtual Environments** | Separate step | Integrated |

### Migration Path

#### Phase 1: Local Development (Current)

Use uv alongside existing tooling for faster local development:

```bash
# Create virtualenv with uv
uv venv

# Install in editable mode (fast)
uv pip install -e .

# Install from requirements
uv pip sync requirements.txt test-requirements.txt
```

#### Phase 2: CI Optimization

Add uv to CI for faster test setup:

```yaml
# .zuul.yaml
- job:
    name: tachyon-unit-fast
    pre-run:
      - name: Install uv
        shell: bash
        run: curl -LsSf https://astral.sh/uv/install.sh | sh
      - name: Create venv and install deps
        run: |
          uv venv .venv
          uv pip sync requirements.txt test-requirements.txt
```

#### Phase 3: Full Integration (Future)

Monitor uv's PEP517 build backend development:

```toml
# Future pyproject.toml (when uv supports build backend)
[build-system]
requires = ["uv>=0.3.0"]
build-backend = "uv.build"
```

### Compatibility Considerations

| Requirement | pbr Solution | uv Compatibility |
|-------------|--------------|------------------|
| PTI Compliance | Required | Works with pbr |
| Git Versioning | Built-in | Use pbr for version |
| requirements.txt | Native | Native |
| OpenStack CI | Standard | Can supplement |

**Strategy**: Use uv for speed where possible, retain pbr for versioning and OpenStack ecosystem integration.

## Database: Neo4j

Tachyon uses Neo4j as its graph database for resource modeling. See [01-schema/](../01-schema/) for detailed schema documentation.

### Python Driver

```python
from neo4j import GraphDatabase

driver = GraphDatabase.driver(
    "bolt://localhost:7687",
    auth=("neo4j", "password")
)

with driver.session() as session:
    result = session.run(
        "MATCH (rp:ResourceProvider {uuid: $uuid}) RETURN rp",
        uuid="abc-123"
    )
```

### Configuration

```ini
# tachyon.conf
[neo4j_database]
uri = bolt://localhost:7687
username = neo4j
password = secret
max_connection_pool_size = 50
connection_timeout = 30
```

## OpenStack Common Libraries

Tachyon leverages the OpenStack oslo.* library ecosystem for cross-cutting concerns. These battle-tested libraries provide standardized implementations for configuration, logging, authentication, policy enforcement, and more. Not all libraries are required, but they will be used as appropriate.

### Core Infrastructure

| Library | Purpose |
|---------|---------|
| [oslo.config](https://opendev.org/openstack/oslo.config) | Configuration management (CLI args, .ini files) |
| [oslo.log](https://opendev.org/openstack/oslo.log) | Structured logging with context |
| [oslo.context](https://opendev.org/openstack/oslo.context) | Request context object passed through call stack |
| [oslo.utils](https://opendev.org/openstack/oslo.utils) | Common utility functions (time, import, etc.) |
| [oslo.serialization](https://opendev.org/openstack/oslo.serialization) | JSON/msgpack serialization |
| [stevedore](https://opendev.org/openstack/stevedore) | Plugin loading via entry points |

### API and Authentication

| Library | Purpose |
|---------|---------|
| [oslo.middleware](https://opendev.org/openstack/oslo.middleware) | WSGI middleware (request ID, CORS, healthcheck) |
| [keystonemiddleware](https://opendev.org/openstack/keystonemiddleware) | Keystone token validation middleware |
| [keystoneauth](https://opendev.org/openstack/keystoneauth) | Authentication session/plugin handling |
| [oslo.policy](https://opendev.org/openstack/oslo.policy) | RBAC policy enforcement |
| [openstacksdk](https://opendev.org/openstack/openstacksdk) | Client SDK for OpenStack service interactions |

### Concurrency and Service Runtime

| Library | Purpose |
|---------|---------|
| [oslo.service](https://opendev.org/openstack/oslo.service) | Service launcher, periodic tasks |
| [cotyledon](https://github.com/sileht/cotyledon) | Threaded/forked service backend |
| [oslo.concurrency](https://opendev.org/openstack/oslo.concurrency) | Locking, process utilities |
| [futurist](https://opendev.org/openstack/futurist) | Executors, futures, periodic workers |

### Testing

| Library | Purpose |
|---------|---------|
| [oslotest](https://opendev.org/openstack/oslotest) | Base test classes, testtools integration |

### Optional (As Needed)

| Library | Purpose |
|---------|---------|
| [oslo.versionedobjects](https://opendev.org/openstack/oslo.versionedobjects) | Versioned object serialization for RPC |

### Plugin Architecture with stevedore

All scheduler filters and weighers are defined as plugins using stevedore's entry point mechanism, even though implementations are defined in-tree. This follows OpenStack conventions and enables future extensibility.

```toml
# pyproject.toml entry points for filters and weighers
[project.entry-points."tachyon.scheduler.filters"]
ComputeFilter = "tachyon.scheduler.filters.compute:ComputeFilter"
ImagePropertiesFilter = "tachyon.scheduler.filters.image:ImagePropertiesFilter"
NUMATopologyFilter = "tachyon.scheduler.filters.numa:NUMATopologyFilter"
PciPassthroughFilter = "tachyon.scheduler.filters.pci:PciPassthroughFilter"

[project.entry-points."tachyon.scheduler.weighers"]
RAMWeigher = "tachyon.scheduler.weighers.ram:RAMWeigher"
CPUWeigher = "tachyon.scheduler.weighers.cpu:CPUWeigher"
DiskWeigher = "tachyon.scheduler.weighers.disk:DiskWeigher"
```

Loading plugins at runtime:

```python
from stevedore import driver
from stevedore import ExtensionManager

# Load all enabled filters
filter_manager = ExtensionManager(
    namespace='tachyon.scheduler.filters',
    invoke_on_load=True,
    on_load_failure_callback=log_load_failure,
)

# Load a specific weigher by name
weigher = driver.DriverManager(
    namespace='tachyon.scheduler.weighers',
    name='RAMWeigher',
    invoke_on_load=True,
).driver
```

### oslo.config Integration with Flask

oslo.config serves as the single source of truth for configuration, with Flask receiving a subset of values:

```python
# src/tachyon/conf/__init__.py
from oslo_config import cfg

CONF = cfg.CONF

api_opts = [
    cfg.StrOpt('auth_strategy',
               default='keystone',
               choices=['keystone', 'noauth2'],
               help='Authentication strategy'),
    cfg.IntOpt('max_limit',
               default=1000,
               help='Maximum number of items in a single response'),
]

CONF.register_opts(api_opts, group='api')

def list_opts():
    """Return oslo.config option definitions for sample config generation."""
    return [('api', api_opts)]
```

```python
# src/tachyon/api/app.py
from oslo_config import cfg
from tachyon.conf import CONF

def create_app(config=None):
    """Create Flask application with oslo.config integration."""
    app = Flask(__name__)

    # Map oslo.config values to Flask config
    app.config['AUTH_STRATEGY'] = CONF.api.auth_strategy
    app.config['MAX_LIMIT'] = CONF.api.max_limit

    # Allow test overrides
    if config:
        app.config.update(config)

    return app
```

### oslo.middleware Integration with Flask

oslo.middleware components wrap the Flask WSGI application:

```python
# src/tachyon/api/app.py
from oslo_middleware import cors
from oslo_middleware import healthcheck
from oslo_middleware import request_id

def create_app(config=None):
    app = Flask(__name__)
    # ... blueprint registration ...

    # Wrap with oslo middleware (applied in reverse order)
    app.wsgi_app = request_id.RequestId(app.wsgi_app)
    app.wsgi_app = cors.CORS(app.wsgi_app, CONF)
    app.wsgi_app = healthcheck.Healthcheck(app.wsgi_app, CONF)

    return app
```

For Keystone authentication:

```python
# src/tachyon/api/app.py
from keystonemiddleware import auth_token

def create_app(config=None):
    app = Flask(__name__)
    # ... setup ...

    if CONF.api.auth_strategy == 'keystone':
        app.wsgi_app = auth_token.AuthProtocol(app.wsgi_app, {})

    return app
```

### oslo.context Request Flow

oslo.context provides the request context that flows through all function calls:

```python
# src/tachyon/api/middleware.py
from oslo_context import context as oslo_context
from flask import g, request

class TachyonContext(oslo_context.RequestContext):
    """Tachyon-specific request context."""

    def __init__(self, user_id=None, project_id=None, roles=None, **kwargs):
        super().__init__(user_id=user_id, project_id=project_id,
                         roles=roles or [], **kwargs)

def before_request():
    """Create context from request headers (set by keystonemiddleware)."""
    g.context = TachyonContext(
        user_id=request.headers.get('X-User-Id'),
        project_id=request.headers.get('X-Project-Id'),
        roles=request.headers.get('X-Roles', '').split(','),
        request_id=request.headers.get('X-Request-Id'),
    )

# In blueprints, access via flask.g
@bp.route('/<uuid:uuid>', methods=['GET'])
def get_resource_provider(uuid):
    context = g.context  # oslo.context instance
    # Pass context to all downstream calls
    return get_provider(context, uuid)
```

## Test Framework

Testing infrastructure is detailed in [08-testing/](../08-testing/). Key technologies:

| Component | Technology | Purpose |
|-----------|------------|---------|
| Test Runner | stestr | PTI compliance, parallel execution |
| Framework | testtools + fixtures | OpenStack standard |
| API Testing | Gabbi + wsgi-intercept | Declarative HTTP tests |
| Database | testcontainers | Isolated Neo4j per test |
| Coverage | coverage.py | PTI requirement |

## References

- [Flask Documentation](https://flask.palletsprojects.com/)
- [Flask Application Factories](https://flask.palletsprojects.com/en/3.0.x/patterns/appfactories/)
- [pbr Documentation](https://docs.openstack.org/pbr/latest/)
- [uv Documentation](https://github.com/astral-sh/uv)
- [Neo4j Python Driver](https://neo4j.com/docs/python-manual/current/)
- [oslo.config Documentation](https://docs.openstack.org/oslo.config/latest/)
- [oslo.middleware Documentation](https://docs.openstack.org/oslo.middleware/latest/)
- [oslo.context Documentation](https://docs.openstack.org/oslo.context/latest/)
- [oslo.policy Documentation](https://docs.openstack.org/oslo.policy/latest/)
- [oslo.log Documentation](https://docs.openstack.org/oslo.log/latest/)
- [keystonemiddleware Documentation](https://docs.openstack.org/keystonemiddleware/latest/)
- [stevedore Documentation](https://docs.openstack.org/stevedore/latest/)
- [oslotest Documentation](https://docs.openstack.org/oslotest/latest/)
