"""Helpers for parsing and checking Placement microversions.

Backed by the upstream ``microversion-parse`` library for correctness.
"""

from __future__ import annotations

from dataclasses import dataclass

import microversion_parse

# The maximum supported microversion - this maps to Placement's latest
MAX_SUPPORTED_MINOR = 39

# Internal value for "latest" - higher than any actual version for comparisons
LATEST_MINOR = 999


@dataclass(frozen=True, order=True)
class Microversion:
    """Parsed microversion consisting of major/minor components."""

    major: int
    minor: int

    def is_at_least(self, minor: int) -> bool:
        """Check if this version is >= the given minor (major is fixed at 1)."""
        return self.minor >= minor


def _extract(header_value: str | None) -> str | None:
    """Use microversion-parse to extract the version string from headers."""
    headers = {}
    if header_value:
        headers["openstack-api-version"] = header_value

    try:
        return microversion_parse.get_version(headers, service_type="placement")
    except Exception:
        return None


def parse(header_value: str | None) -> Microversion:
    """Parse the OpenStack-API-Version header into a Microversion."""
    version_str = _extract(header_value)
    if not version_str:
        return Microversion(1, 0)

    if version_str.lower() == "latest":
        return Microversion(1, LATEST_MINOR)

    try:
        version_tuple = microversion_parse.parse_version_string(version_str)
        return Microversion(int(version_tuple.major), int(version_tuple.minor))
    except Exception:
        return Microversion(1, 0)

