# Coding Conventions

This document defines the coding conventions for Tachyon, based on OpenStack's
Python style guidelines. All code contributions must follow these standards.

## License Headers

All Python source files must begin with the SPDX license identifier:

```python
# SPDX-License-Identifier: Apache-2.0
```

This compact format is preferred over the full Apache 2.0 boilerplate header.

## Import Style

### Module-Only Imports (H301, H303, H304, H306)

Tachyon uses **strict module-only imports**. Do not import objects directly
from modules:

```python
# CORRECT - Import modules only
import flask
from tachyon.api import errors
from tachyon.api import microversion

# Then use: flask.Blueprint, flask.jsonify, errors.NotFound, etc.

# INCORRECT - Do not import objects directly
from flask import Blueprint, Response, jsonify, request
from tachyon.api.errors import NotFound, BadRequest
```

**Rationale**: Module-only imports make code more readable by showing where
each symbol comes from, reduce merge conflicts, and simplify mocking in tests.

### Import Order

Imports must be grouped in the following order, with blank lines between groups:

1. `__future__` imports
2. Standard library modules
3. Third-party library modules
4. Local application modules

```python
# SPDX-License-Identifier: Apache-2.0

"""Module docstring."""

from __future__ import annotations

import collections
import datetime
import uuid

import flask
import neo4j

from tachyon.api import app
from tachyon.api import errors
from tachyon.api import microversion
```

### Deferred Imports

When circular import issues arise, defer imports inside functions:

```python
def _driver():
    """Get the Neo4j driver from the Flask app."""
    from tachyon.api import app
    return app.get_driver()
```

## Line Length and Formatting

- **Maximum line length**: 79 characters (PEP 8 standard)
- **Indentation**: 4 spaces (no tabs)
- **Line endings**: UNIX-style (LF only)
- **Trailing whitespace**: None allowed

## Docstrings

### Module Docstrings

Every module must have a docstring describing its purpose:

```python
# SPDX-License-Identifier: Apache-2.0

"""Resource Providers API blueprint.

Implements Placement-compatible CRUD operations for ResourceProvider nodes.
"""
```

### Function/Method Docstrings (H404, H405)

Use imperative mood for the first line. Multi-line docstrings must have
a summary on the first line, followed by a blank line:

```python
def create_resource_provider(name):
    """Create a new resource provider.

    Request Body:
        name: Required. Provider name (must be unique).
        uuid: Optional. Provider UUID (generated if not provided).

    :param name: The resource provider name
    :returns: Tuple of (response, status_code)
    :raises errors.BadRequest: If name is missing or invalid
    :raises errors.Conflict: If name already exists
    """
```

### Docstring Format

Use Sphinx-style `:param:`, `:returns:`, `:raises:` for documenting parameters:

```python
def _validate_uuid(value, field):
    """Validate and normalize UUID strings.

    :param value: UUID string to validate (accepts dashless input)
    :param field: Field name for error messages
    :returns: Normalized UUID string with dashes
    :raises errors.BadRequest: If UUID format is invalid
    """
```

## String Formatting

### Delayed String Interpolation (H702)

Use `%s` formatting for log messages to defer interpolation:

```python
# CORRECT - Deferred interpolation
LOG.debug("Processing provider %s", provider_uuid)
LOG.warning("Failed to create %s: %s", name, exc)

# INCORRECT - Eager interpolation
LOG.debug(f"Processing provider {provider_uuid}")
LOG.debug("Processing provider {}".format(provider_uuid))
```

### User-Facing Messages

For user-facing messages (errors, responses), `%` formatting is preferred
for consistency, but f-strings are acceptable:

```python
# Both acceptable for error messages
raise errors.NotFound("Resource provider %s not found." % rp_uuid)
raise errors.NotFound(f"Resource provider {rp_uuid} not found.")
```

## Exception Handling

### Specific Exceptions (H201)

Always catch specific exceptions, never bare `except:`:

```python
# CORRECT
try:
    uuid_obj = uuid.UUID(value)
except (ValueError, TypeError, AttributeError):
    raise errors.BadRequest("Invalid UUID format")

# INCORRECT
try:
    uuid_obj = uuid.UUID(value)
except:
    raise errors.BadRequest("Invalid UUID format")
```

### Exception Classes

Define exception classes with descriptive defaults:

```python
class NotFound(APIError):
    """Resource not found (404)."""

    status_code = 404
    title = "Not Found"
```

## Testing Conventions

### Mock with autospec (H210)

Always use `autospec=True` when creating mocks to catch signature mismatches:

```python
# CORRECT
@mock.patch.object(neo4j_api, 'init_driver', autospec=True)
def test_create_app(self, mock_init_driver):
    ...

# INCORRECT
@mock.patch.object(neo4j_api, 'init_driver')
def test_create_app(self, mock_init_driver):
    ...
```

### Use unittest.mock (H216)

Use `unittest.mock` from the standard library, not the standalone `mock` package:

```python
# CORRECT
from unittest import mock

# INCORRECT
import mock
```

### Test Base Classes

Tests should inherit from `oslotest.base.BaseTestCase` for consistent behavior:

```python
from oslotest import base


class TestResourceProviders(base.BaseTestCase):
    """Tests for resource provider operations."""

    def test_create_provider(self):
        ...
```

## oslo.* Library Usage

### Configuration (oslo.config)

Use `oslo.config` for all configuration options:

```python
from oslo_config import cfg

CONF = cfg.CONF

api_opts = [
    cfg.StrOpt(
        "auth_strategy",
        default="keystone",
        choices=["keystone", "noauth2"],
        help="Authentication strategy",
    ),
]


def register_opts(conf):
    conf.register_opts(api_opts, group="api")
```

### Logging (oslo.log)

Use `oslo.log` for consistent logging across OpenStack projects:

```python
from oslo_log import log

LOG = log.getLogger(__name__)


def create_resource_provider(name):
    LOG.debug("Creating resource provider %s", name)
    ...
    LOG.info("Created resource provider %s with uuid %s", name, rp_uuid)
```

## Type Hints

Type hints are encouraged but optional. When used, use `from __future__ import annotations` for forward references:

```python
from __future__ import annotations

def _format_provider(
    rp: dict,
    mv: microversion.Microversion,
    root_uuid: str | None = None,
) -> dict:
    ...
```

## Flask Conventions

### Blueprint Registration

Blueprints should be defined at module level and imported in the app factory:

```python
# In blueprints/resource_providers.py
bp = flask.Blueprint("resource_providers", __name__, url_prefix="/resource_providers")

# In app.py
from tachyon.api.blueprints import resource_providers
app.register_blueprint(resource_providers.bp)
```

### Response Format

Return tuples of `(response, status_code)` for consistency:

```python
@bp.route("", methods=["GET"])
def list_resource_providers():
    ...
    return flask.jsonify({"resource_providers": providers}), 200
```

### Error Handling

Use custom APIError subclasses that format responses consistently:

```python
class NotFound(APIError):
    status_code = 404
    title = "Not Found"

# Usage
raise errors.NotFound("Resource provider %s not found." % rp_uuid)
```

## Neo4j/Cypher Conventions

### Query Formatting

Use multi-line strings for Cypher queries with consistent indentation:

```python
result = session.run(
    """
    MATCH (rp:ResourceProvider {uuid: $uuid})
    OPTIONAL MATCH (parent:ResourceProvider)-[:PARENT_OF]->(rp)
    RETURN rp, parent.uuid AS parent_uuid
    """,
    uuid=rp_uuid,
)
```

### Parameter Binding

Always use parameterized queries, never string interpolation:

```python
# CORRECT
session.run("MATCH (rp:ResourceProvider {uuid: $uuid}) RETURN rp", uuid=rp_uuid)

# INCORRECT - Security risk
session.run(f"MATCH (rp:ResourceProvider {{uuid: '{rp_uuid}'}}) RETURN rp")
```

## Commit Messages

Follow OpenStack commit message format:

```
Short summary (50 chars or less)

More detailed explanatory text. Wrap at 72 characters. The blank
line separating the summary from the body is critical.

Change-Id: I1234567890abcdef...
```

For bug fixes, include the bug reference:

```
Fix resource provider generation conflict

The generation check was not being performed correctly when
updating resource providers without a generation field.

Closes-Bug: #1234567
Change-Id: I1234567890abcdef...
```

## References

- [OpenStack Hacking Style Guide](https://docs.openstack.org/hacking/latest/)
- [PEP 8 Style Guide](https://peps.python.org/pep-0008/)
- [oslo.config Documentation](https://docs.openstack.org/oslo.config/latest/)
- [oslo.log Documentation](https://docs.openstack.org/oslo.log/latest/)
