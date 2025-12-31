# SPDX-License-Identifier: Apache-2.0

"""Helpers for parsing and checking Placement microversions.

Backed by the upstream ``microversion-parse`` library for correctness.
"""

from __future__ import annotations

import dataclasses

import microversion_parse

# The maximum supported microversion - this maps to Placement's latest
MAX_SUPPORTED_MINOR = 39

# Internal value for "latest" - higher than any actual version for comparisons
LATEST_MINOR = 999


@dataclasses.dataclass(frozen=True, order=True)
class Microversion:
    """Parsed microversion consisting of major/minor components.

    :ivar major: Major version number (always 1 for Placement)
    :ivar minor: Minor version number
    """

    major: int
    minor: int

    def is_at_least(self, minor):
        """Check if this version is >= the given minor (major is fixed at 1).

        :param minor: Minor version to compare against
        :returns: True if this version's minor is >= the given minor
        """
        return self.minor >= minor


def _extract(header_value):
    """Use microversion-parse to extract the version string from headers.

    :param header_value: Value of the OpenStack-API-Version header
    :returns: Version string or None
    """
    headers = {}
    if header_value:
        headers["openstack-api-version"] = header_value

    try:
        return microversion_parse.get_version(headers, service_type="placement")
    except (TypeError, ValueError):
        return None


def parse(header_value):
    """Parse the OpenStack-API-Version header into a Microversion.

    :param header_value: Value of the OpenStack-API-Version header
    :returns: Microversion instance
    """
    version_str = _extract(header_value)
    if not version_str:
        return Microversion(1, 0)

    if version_str.lower() == "latest":
        return Microversion(1, LATEST_MINOR)

    try:
        version_tuple = microversion_parse.parse_version_string(version_str)
        return Microversion(int(version_tuple.major), int(version_tuple.minor))
    except (TypeError, ValueError, AttributeError):
        return Microversion(1, 0)
