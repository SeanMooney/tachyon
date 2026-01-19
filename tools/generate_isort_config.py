#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import re
import sys
import tomlkit  # type: ignore[import-not-found]
from urllib.request import urlopen

PROJECTS_URL = (
    "https://opendev.org/openstack/governance/raw/branch/master/reference/projects.yaml"
)
PYPROJECT_PATH = Path("pyproject.toml")
REQUIREMENTS_FILENAMES = {
    "requirements.txt",
    "test-requirements.txt",
}
DEFAULT_IGNORED_DIRS = {
    ".git",
    ".tox",
    ".venv",
}


def _load_pyproject(path: Path):
    return tomlkit.parse(path.read_text(encoding="utf-8"))


def _fetch_projects_yaml(url: str) -> str:
    with urlopen(url) as response:
        return response.read().decode("utf-8")


def _parse_repo_names(yaml_text: str) -> set[str]:
    repos: set[str] = set()
    for line in yaml_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped in {"---", "..."}:
            continue
        match = re.match(r"^-\s+openstack/([A-Za-z0-9_.-]+)\s*$", stripped)
        if match:
            repos.add(match.group(1))
    return repos


def _normalize_module_name(name: str) -> str:
    # Preserve any os- prefix; only normalize hyphens to underscores.
    normalized = name.lower().replace("-", "_").replace(".", "_")
    if normalized.startswith("python_"):
        return normalized[len("python_") :]
    return normalized


def _load_gitignore_dirs(base_dir: Path) -> set[str]:
    gitignore_path = base_dir / ".gitignore"
    if not gitignore_path.exists():
        return set()
    ignored_dirs: set[str] = set()
    for raw_line in gitignore_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "!" in line:
            continue
        if line.endswith("/"):
            ignored_dirs.add(line.strip("/"))
    return ignored_dirs


def _iter_requirement_files(base_dir: Path) -> list[Path]:
    ignored_dirs = DEFAULT_IGNORED_DIRS | _load_gitignore_dirs(base_dir)
    files: list[Path] = []
    for root, dirs, filenames in os.walk(base_dir):
        dirs[:] = [d for d in dirs if d not in ignored_dirs]
        for filename in filenames:
            if filename in REQUIREMENTS_FILENAMES:
                files.append(Path(root) / filename)
    return sorted(set(files))


def _parse_requirement_name(raw_line: str) -> str | None:
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith(("-r", "--requirement", "-c", "--constraint")):
        return None
    if line.startswith(("-e", "--editable")) and "egg=" in line:
        egg_match = re.search(r"egg=([A-Za-z0-9_.-]+)", line)
        if egg_match:
            return egg_match.group(1)
    if "@" in line:
        line = line.split("@", 1)[0].strip()
    line = line.split(";", 1)[0].strip()
    line = line.split("[", 1)[0].strip()
    name_match = re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]*", line)
    if not name_match:
        return None
    return name_match.group(0)


def _collect_dependency_names(base_dir: Path) -> set[str]:
    dependencies: set[str] = set()
    for req_path in _iter_requirement_files(base_dir):
        for raw_line in req_path.read_text(encoding="utf-8").splitlines():
            name = _parse_requirement_name(raw_line)
            if name:
                dependencies.add(_normalize_module_name(name))
    return dependencies


def _build_isort_config(first_party_module: str, openstack_modules: list[str]):
    known_first_party = tomlkit.array().multiline(True)
    known_first_party.append(first_party_module)

    section_order = tomlkit.array().multiline(True)
    for section in (
        "future",
        "standard-library",
        "third-party",
        "openstack-third-party",
        "first-party",
    ):
        section_order.append(section)

    openstack_third_party = tomlkit.array().multiline(True)
    for module in openstack_modules:
        openstack_third_party.append(module)

    isort_table = tomlkit.table()
    isort_table.add("known-first-party", known_first_party)
    isort_table.add("section-order", section_order)
    isort_table.add("default-section", "third-party")
    isort_table.add("order-by-type", True)
    isort_table.add("from-first", False)
    isort_table.add("force-sort-within-sections", True)
    isort_table.add("force-single-line", True)
    isort_table.add("combine-as-imports", False)

    sections_table = tomlkit.table()
    sections_table.add("openstack-third-party", openstack_third_party)
    isort_table.add("sections", sections_table)
    return isort_table


def _ensure_table(parent, key: str):
    if key not in parent:
        parent[key] = tomlkit.table()
    return parent[key]


def _read_project_name(pyproject: dict) -> str:
    project_section = pyproject.get("project", {})
    project_name = project_section.get("name")
    if not project_name:
        raise RuntimeError("Missing [project].name in pyproject.toml")
    return _normalize_module_name(project_name)


def main() -> int:
    if not PYPROJECT_PATH.exists():
        raise RuntimeError("pyproject.toml not found")

    pyproject = _load_pyproject(PYPROJECT_PATH)
    first_party_module = _read_project_name(pyproject)

    yaml_text = _fetch_projects_yaml(PROJECTS_URL)
    repo_names = _parse_repo_names(yaml_text)
    dependencies = _collect_dependency_names(PYPROJECT_PATH.parent)
    openstack_modules = sorted(
        {_normalize_module_name(name) for name in repo_names}
        & dependencies - {first_party_module}
    )

    tool_section = _ensure_table(pyproject, "tool")
    ruff_section = _ensure_table(tool_section, "ruff")
    lint_section = _ensure_table(ruff_section, "lint")
    lint_section["isort"] = _build_isort_config(
        first_party_module, openstack_modules
    )

    PYPROJECT_PATH.write_text(tomlkit.dumps(pyproject), encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
