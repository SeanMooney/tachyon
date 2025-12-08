---
title: Project Structure
description: src layout and directory organization for Tachyon
keywords: [src-layout, project-structure, directory, pyproject, tox, pbr]
related:
  - 08-testing/README.md
  - 08-testing/pti-compliance.md
implements: []
section: testing
---

# Project Structure

Tachyon uses the **src layout** pattern as recommended by [Python packaging guidelines](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/) and demonstrated in OpenStack's [grian-ui](../../ref/src/grian-ui) project.

## Directory Layout

```
tachyon/
├── src/
│   └── tachyon/                    # Main package (importable as 'tachyon')
│       ├── __init__.py
│       ├── api/                    # WSGI API application
│       │   ├── __init__.py
│       │   ├── app.py              # Pecan/WSGI app setup
│       │   └── controllers/        # API controllers
│       ├── conf/                   # Configuration options (oslo.config)
│       │   ├── __init__.py
│       │   └── database.py         # Neo4j connection options
│       ├── db/                     # Database layer
│       │   ├── __init__.py
│       │   ├── neo4j_api.py        # Neo4j context manager
│       │   └── schema.py           # Cypher schema definitions
│       ├── objects/                # Versioned objects
│       │   ├── __init__.py
│       │   ├── resource_provider.py
│       │   ├── inventory.py
│       │   └── consumer.py
│       ├── policies/               # oslo.policy definitions
│       │   └── __init__.py
│       └── deploy.py               # WSGI app factory
│
├── tests/
│   └── tachyon_tests/              # Test package (separate from src)
│       ├── __init__.py
│       ├── local_fixtures/         # Shared fixtures
│       │   ├── __init__.py
│       │   ├── database.py         # Neo4j testcontainer fixture
│       │   ├── config.py           # oslo.config fixture
│       │   ├── logging.py          # Logging/warnings capture
│       │   └── policy.py           # Policy fixture
│       ├── unit/                   # Unit tests
│       │   ├── __init__.py
│       │   ├── base.py             # Unit test base class
│       │   ├── api/
│       │   ├── db/
│       │   └── objects/
│       └── functional/             # Functional tests
│           ├── __init__.py
│           ├── base.py             # Functional test base class
│           ├── test_api.py         # Gabbi test loader
│           ├── local_fixtures/     # Gabbi-specific fixtures
│           │   ├── __init__.py
│           │   └── gabbits.py      # APIFixture, setup_app()
│           └── gabbits/            # YAML test files
│               ├── basic-http.yaml
│               ├── resource-provider.yaml
│               ├── inventory.yaml
│               ├── allocations.yaml
│               └── ...
│
├── doc/                            # Sphinx documentation
│   ├── requirements.txt
│   └── source/
│       ├── conf.py
│       └── index.rst
│
├── releasenotes/                   # reno release notes
│   └── source/
│
├── pyproject.toml                  # PEP 518 build configuration
├── setup.cfg                       # pbr configuration
├── setup.py                        # Minimal setup.py for pbr
├── tox.ini                         # Tox environments
├── requirements.txt                # Runtime dependencies
├── test-requirements.txt           # Test dependencies
└── .stestr.conf                    # stestr configuration (optional, can use pyproject.toml)
```

## Why src Layout?

### Benefits

1. **Prevents Accidental Imports**
   - Tests cannot accidentally import from the source directory
   - Must use the installed package, catching packaging issues early

2. **Clear Separation**
   - Obvious distinction between installable code (`src/`) and non-installable (`tests/`, `doc/`)
   - Simplifies `.gitignore` and build tooling

3. **Debugging Safety**
   - When tests are added to PYTHONPATH for debugging, source code isn't accidentally shadowed

4. **OpenStack Convention**
   - Matches modern OpenStack projects (grian-ui)
   - Familiar to OpenStack contributors

### Key Configuration

**`pyproject.toml`** must specify the package directory:

```toml
[build-system]
requires = ["pbr>=6.0.0", "setuptools>=64.0.0"]
build-backend = "pbr.build"

[project]
name = "tachyon"
dynamic = ["version"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.stestr]
test_path = "./tests/tachyon_tests/unit"
top_dir = "./"
group_regex = "tachyon_tests\\.functional\\.test_api(?:\\.|_)([^_]+)"
```

## Package Naming Conventions

### Source Package: `tachyon`

- Located at `src/tachyon/`
- Imported as `import tachyon` or `from tachyon import ...`
- Uses underscores in module names (Python convention)

### Test Package: `tachyon_tests`

- Located at `tests/tachyon_tests/`
- **Not** installed with the package
- Uses `tachyon_tests` (not `tachyon.tests`) to avoid confusion with source package

### Fixture Module: `local_fixtures`

Named `local_fixtures` (not `fixtures`) to avoid shadowing the `fixtures` library:

```python
# Correct - no conflict
from tachyon_tests.local_fixtures import database

# Would conflict with fixtures library if named 'fixtures'
# from tachyon_tests.fixtures import database  # BAD
```

## Test Discovery

### PYTHONPATH Configuration

Tests are not part of the installed package, so `tox.ini` must add them to PYTHONPATH:

```ini
[testenv]
setenv =
    PYTHONPATH = {toxinidir}/tests:{envdir}
```

### stestr Configuration

stestr discovers tests via the `test_path` setting:

```toml
# In pyproject.toml
[tool.stestr]
test_path = "./tests/tachyon_tests/unit"
```

For functional tests, override at runtime:

```bash
stestr --test-path=./tests/tachyon_tests/functional run
```

### Gabbi Test Grouping

Gabbi tests within a YAML file must run sequentially (test ordering), but different YAML files can run in parallel. The `group_regex` ensures proper grouping:

```toml
group_regex = "tachyon_tests\\.functional\\.test_api(?:\\.|_)([^_]+)"
```

This captures the YAML filename from the test name, grouping tests from the same file.

## Configuration Files

### `pyproject.toml`

Modern Python project configuration:

```toml
[build-system]
requires = ["pbr>=6.0.0", "setuptools>=64.0.0"]
build-backend = "pbr.build"

[project]
name = "tachyon"
description = "Neo4j-backed scheduling and resource management for OpenStack"
readme = "README.rst"
authors = [
  {name = "OpenStack", email = "openstack-discuss@lists.openstack.org"},
]
requires-python = ">=3.10"
license = "Apache-2.0"
classifiers = [
    "Environment :: OpenStack",
    "Intended Audience :: Information Technology",
    "Operating System :: POSIX :: Linux",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
]
dynamic = ["version"]

[project.urls]
Homepage = "https://opendev.org/openstack/tachyon"

[tool.setuptools.packages.find]
where = ["src"]

[tool.stestr]
test_path = "./tests/tachyon_tests/unit"
top_dir = "./"
group_regex = "tachyon_tests\\.functional\\.test_api(?:\\.|_)([^_]+)"
```

### `setup.cfg`

pbr-specific configuration:

```ini
[metadata]
name = tachyon

[files]
packages = tachyon

[entry_points]
wsgi_scripts =
    tachyon-api = tachyon.deploy:loadapp
```

### `setup.py`

Minimal for pbr:

```python
import setuptools
setuptools.setup(pbr=True)
```

## Import Patterns

### From Application Code

```python
# Import from tachyon package
from tachyon.api import app
from tachyon.db import neo4j_api
from tachyon.objects import resource_provider
```

### From Test Code

```python
# Import fixtures
from tachyon_tests.local_fixtures import database, config

# Import application code (works because package is installed in editable mode)
from tachyon.objects import resource_provider

# Import functional fixtures
from tachyon_tests.functional.local_fixtures import gabbits
```

## Development Installation

For development, install in editable mode:

```bash
pip install -e .
```

Or via tox (which uses `usedevelop = True`):

```bash
tox -e py312
```

This installs the `src/tachyon` package in editable mode, allowing code changes without reinstallation.
