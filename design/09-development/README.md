# Development Guidelines

This section documents the development practices, coding conventions, and
contribution guidelines for the Tachyon project.

## Contents

- [Coding Conventions](coding-conventions.md) - OpenStack-compliant Python
  style guide, import conventions, and best practices

## Overview

Tachyon follows OpenStack coding conventions to ensure consistency with the
broader OpenStack ecosystem. This includes:

- **Import Style**: Module-only imports (H301, H303, H304, H306)
- **License Headers**: SPDX Apache 2.0 identifier
- **oslo.\* Libraries**: oslo.config, oslo.log for configuration and logging
- **Testing**: oslotest base classes, autospec mocking (H210)
- **Docstrings**: Sphinx-style parameter documentation

## Quick Reference

### Module Template

```python
# SPDX-License-Identifier: Apache-2.0

"""Module description.

Detailed description of module purpose and functionality.
"""

from __future__ import annotations

import collections
import datetime

import flask

from tachyon.api import errors
from tachyon.api import microversion


def public_function(param):
    """Do something useful.

    :param param: Description of parameter
    :returns: Description of return value
    :raises errors.BadRequest: When param is invalid
    """
    ...
```

### Test Template

```python
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for module_name."""

from unittest import mock

from oslotest import base

from tachyon.api import app
from tachyon.db import neo4j_api


class TestClassName(base.BaseTestCase):
    """Tests for ClassName."""

    @mock.patch.object(neo4j_api, 'init_driver', autospec=True)
    def test_method_name(self, mock_driver):
        """Test description."""
        ...
```

## Related Documentation

- [Testing Overview](../08-testing/README.md) - Testing architecture and patterns
- [PTI Compliance](../08-testing/pti-compliance.md) - OpenStack testing interface
- [Technology Stack](../00-overview/technology-stack.md) - Core technology choices

