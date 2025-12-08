---
title: PTI Compliance
description: OpenStack Project Testing Interface requirements and implementation
keywords: [pti, openstack, tox, stestr, coverage, pep8, sphinx, pbr]
related:
  - 08-testing/README.md
  - 08-testing/project-structure.md
  - 00-overview/technology-stack.md
implements: []
section: testing
---

# PTI Compliance

Tachyon follows the OpenStack [Project Testing Interface (PTI) for Python](../../ref/src/governance/reference/pti/python.rst), ensuring consistent testing patterns across OpenStack projects.

> **Note**: For pbr packaging configuration details (versioning, pyproject.toml, setup.cfg), see [Technology Stack](../00-overview/technology-stack.md#buildpackaging-pbr).

## Required Commands

The PTI specifies these commands must work in a clean tree:

| Command | Purpose | Tachyon Implementation |
|---------|---------|------------------------|
| `tox -e pep8` | Code style checks | pre-commit with ruff |
| `tox -e py3x` | Unit tests | stestr run |
| `tox -e cover` | Coverage report | coverage.py with HTML/XML |
| `python -m build -s .` | Source tarball | pbr sdist |
| `python -m build -w .` | Wheel package | pbr wheel |
| `sphinx-build -W -b html doc/source doc/build` | Documentation | Sphinx |

## tox.ini Configuration

```ini
[tox]
minversion = 4.6.0
envlist = py3,py310,py311,py312,functional,pep8,cover
# Skip missing interpreters for local development
skip_missing_interpreters = true

[testenv]
usedevelop = True
allowlist_externals =
    bash
    find
    rm
install_command = python -I -m pip install -c{env:TOX_CONSTRAINTS_FILE:https://releases.openstack.org/constraints/upper/master} {opts} {packages}
setenv =
    VIRTUAL_ENV={envdir}
    LANGUAGE=en_US
    LC_ALL=en_US.utf-8
    OS_STDOUT_CAPTURE=1
    OS_STDERR_CAPTURE=1
    OS_LOG_CAPTURE=1
    OS_TEST_TIMEOUT=160
    PYTHONDONTWRITEBYTECODE=1
    # Tests are not part of the package, add to PYTHONPATH
    PYTHONPATH={toxinidir}/tests:{envdir}
deps =
    -r{toxinidir}/requirements.txt
    -r{toxinidir}/test-requirements.txt
passenv =
    OS_DEBUG
    OS_LOG_CAPTURE
    TRACE_FAILONLY
commands =
    stestr run {posargs}
    stestr slowest

# Python version specific environments
[testenv:{py3,py310,py311,py312,py313}]
description = Run unit tests with Python {basepython}
commands =
    stestr run {posargs}
    stestr slowest

# Functional tests (requires Docker for Neo4j container)
[testenv:functional{,-py310,-py311,-py312,-py313}]
description = Run functional tests with real Neo4j database
commands =
    stestr --test-path={toxinidir}/tests/tachyon_tests/functional run {posargs}
    stestr slowest

# Code style checks
[testenv:{pep8,lint}]
description = Run style checks with pre-commit
skip_install = true
deps = pre-commit
commands = pre-commit run --all-files --show-diff-on-failure

# Coverage reporting
[testenv:cover]
description = Generate test coverage report
setenv =
    {[testenv]setenv}
    PYTHON=coverage run --source src/tachyon --parallel-mode
commands =
    coverage erase
    stestr run {posargs}
    coverage combine
    coverage html -d cover
    coverage xml -o cover/coverage.xml
    coverage report

# Documentation
[testenv:docs]
description = Build documentation
deps = -r{toxinidir}/doc/requirements.txt
commands =
    rm -rf doc/build
    sphinx-build -W --keep-going -b html -j auto doc/source doc/build/html

# Release notes
[testenv:releasenotes]
description = Generate release notes
deps = -r{toxinidir}/doc/requirements.txt
commands =
    sphinx-build -a -W -E -d releasenotes/build/doctrees -b html \
        releasenotes/source releasenotes/build/html

# Development environment
[testenv:venv]
description = Virtual environment with all dependencies
deps =
    {[testenv]deps}
    -r{toxinidir}/doc/requirements.txt
commands = {posargs}
```

## stestr Configuration

Configure stestr in `pyproject.toml`:

```toml
[tool.stestr]
test_path = "./tests/tachyon_tests/unit"
top_dir = "./"
# Group Gabbi tests by YAML file for proper test ordering
group_regex = "tachyon_tests\\.functional\\.test_api(?:\\.|_)([^_]+)"
```

### Test Grouping for Gabbi

Gabbi tests within a YAML file must run sequentially (tests depend on prior state). The `group_regex` captures the YAML filename from the test name:

```
Test name: tachyon_tests.functional.test_api.ResourceProviderGabbits.test_010_create
Captured:  ResourceProviderGabbits
```

All tests with the same capture group run in the same process, preserving order.

## Coverage Configuration

Create `.coveragerc` or configure in `pyproject.toml`:

```toml
# pyproject.toml
[tool.coverage.run]
source = ["src/tachyon"]
parallel = true
branch = true
omit = [
    "*/tests/*",
    "*/__pycache__/*",
]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "raise NotImplementedError",
    "if TYPE_CHECKING:",
]
fail_under = 80
show_missing = true

[tool.coverage.html]
directory = "cover"

[tool.coverage.xml]
output = "cover/coverage.xml"
```

### PTI Coverage Requirements

The PTI requires:
- HTML output in `cover/` directory
- XML output at `cover/coverage.xml`
- Both are mandatory artifacts

## pre-commit Configuration

Create `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
      - id: debug-statements

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.11.0
    hooks:
      - id: mypy
        additional_dependencies:
          - types-requests
        args: [--ignore-missing-imports]
```

### ruff Configuration

```toml
# pyproject.toml
[tool.ruff]
line-length = 79
target-version = "py310"

[tool.ruff.lint]
select = [
    "E",   # pycodestyle errors
    "W",   # pycodestyle warnings
    "F",   # pyflakes
    "I",   # isort
    "B",   # flake8-bugbear
    "C4",  # flake8-comprehensions
    "UP",  # pyupgrade
]
ignore = [
    "E501",  # line too long (handled by formatter)
]

[tool.ruff.lint.isort]
known-first-party = ["tachyon"]
```

## Requirements Files

### requirements.txt

Runtime dependencies:

```
pbr>=6.0.0

# Oslo libraries
oslo.config>=9.0.0
oslo.log>=5.0.0
oslo.policy>=4.0.0
oslo.utils>=6.0.0

# Neo4j
neo4j>=5.0.0

# API (Flask - see technology-stack.md for rationale)
Flask>=3.0.0
```

### test-requirements.txt

Test dependencies:

```
# Testing framework
fixtures>=4.0.0
testtools>=2.5.0
stestr>=4.0.0
oslotest>=4.5.0

# Gabbi
gabbi>=2.4.0
wsgi-intercept>=1.10.0

# Neo4j testing
testcontainers[neo4j]>=3.7.0

# Coverage
coverage>=7.0.0

# Mocking
requests-mock>=1.9.0
```

### doc/requirements.txt

Documentation dependencies:

```
sphinx>=5.0.0
openstackdocstheme>=2.0.0
reno>=3.5.0
```

## pyproject.toml

For complete pbr configuration (build-system, project metadata, entry points), see [Technology Stack - pbr](../00-overview/technology-stack.md#buildpackaging-pbr).

Testing-specific configuration in `pyproject.toml`:

```toml
[tool.stestr]
test_path = "./tests/tachyon_tests/unit"
top_dir = "./"
group_regex = "tachyon_tests\\.functional\\.test_api(?:\\.|_)([^_]+)"

[tool.setuptools.packages.find]
where = ["src"]

# Coverage, ruff, mypy configs as shown in sections above...
```

## Zuul CI Configuration

Create `.zuul.yaml`:

```yaml
- project:
    templates:
      - check-requirements
      - openstack-python3-jobs
      - openstack-cover-jobs
      - publish-openstack-docs-pti
      - release-notes-jobs-python3
    check:
      jobs:
        - openstack-tox-pep8
        - openstack-tox-py310
        - openstack-tox-py311
        - openstack-tox-py312
        - tachyon-functional-py312
    gate:
      jobs:
        - openstack-tox-pep8
        - openstack-tox-py310
        - openstack-tox-py311
        - openstack-tox-py312
        - tachyon-functional-py312

- job:
    name: tachyon-functional-py312
    parent: openstack-tox-py312
    description: Run Tachyon functional tests with Neo4j
    vars:
      tox_envlist: functional-py312
    pre-run: playbooks/ensure-docker.yaml
```

## Running PTI Commands

### Local Development

```bash
# Unit tests
tox -e py312

# Functional tests (requires Docker)
tox -e functional

# Style checks
tox -e pep8

# Coverage
tox -e cover

# Documentation
tox -e docs

# Build packages
python -m build -s .  # Source distribution
python -m build -w .  # Wheel
```

### CI Verification

Before submitting, verify all PTI commands pass:

```bash
# Full PTI verification
tox -e pep8 && tox -e py312 && tox -e cover && tox -e docs
```

## References

- [PTI for Python](../../ref/src/governance/reference/pti/python.rst)
- [stestr documentation](https://stestr.readthedocs.io/)
- [OpenStack tox conventions](https://governance.openstack.org/tc/reference/pti/python.html)
- [grian-ui tox.ini](../../ref/src/grian-ui/tox.ini) - Reference implementation
- [Technology Stack](../00-overview/technology-stack.md) - pbr configuration and Flask API

