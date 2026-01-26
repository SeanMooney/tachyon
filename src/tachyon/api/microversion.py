# SPDX-License-Identifier: Apache-2.0

"""Helpers for parsing and checking Placement microversions.

Backed by the upstream ``microversion-parse`` library for correctness.
"""

from __future__ import annotations

import dataclasses
import re

import microversion_parse
from oslo_log import log

LOG = log.getLogger(__name__)

# The minimum and maximum supported microversions
MIN_SUPPORTED_MINOR: int = 0
MAX_SUPPORTED_MINOR: int = 39

# Internal value for "latest" - higher than any actual version for comparisons
LATEST_MINOR: int = 999


class MicroversionParseError(Exception):
    """Raised when a microversion string is malformed."""

    def __init__(self, version_string: str) -> None:
        self.version_string = version_string
        super().__init__(f"invalid version string: {version_string}")


class MicroversionNotAcceptable(Exception):
    """Raised when a microversion is outside the supported range."""

    def __init__(self, version_string: str) -> None:
        self.version_string = version_string
        super().__init__(f"Unacceptable version header: {version_string}")


@dataclasses.dataclass(frozen=True, order=True)
class Microversion:
    """Parsed microversion consisting of major/minor components.

    :ivar major: Major version number (always 1 for Placement)
    :ivar minor: Minor version number
    """

    major: int
    minor: int

    def is_at_least(self, minor: int) -> bool:
        """Check if this version is >= the given minor (major is fixed at 1).

        :param minor: Minor version to compare against
        :returns: True if this version's minor is >= the given minor
        """
        return self.minor >= minor


def _extract(header_value: str | None) -> str | None:
    """Use microversion-parse to extract the version string from headers.

    :param header_value: Value of the OpenStack-API-Version header
    :returns: Version string or None
    """
    headers: dict[str, str] = {}
    if header_value:
        headers["openstack-api-version"] = header_value

    try:
        return microversion_parse.get_version(headers, service_type="placement")
    except (TypeError, ValueError):
        return None


def parse_with_validation(header_value: str | None) -> Microversion:
    """Parse the OpenStack-API-Version header with validation.

    This function validates the version string format and ensures
    the version is within the supported range.

    :param header_value: Value of the OpenStack-API-Version header
    :returns: Microversion instance
    :raises MicroversionParseError: If version string is malformed
    :raises MicroversionNotAcceptable: If version is outside supported range
    """
    version_str = _extract(header_value)
    if not version_str:
        return Microversion(1, 0)

    if version_str.lower() == "latest":
        return Microversion(1, LATEST_MINOR)

    # Check for valid version format: must be X.Y where X and Y are integers
    # This catches things like "pony.horse", "1.2.3", etc.
    if not re.match(r"^\d+\.\d+$", version_str):
        raise MicroversionParseError(version_str)

    try:
        version_tuple = microversion_parse.parse_version_string(version_str)
        major = int(version_tuple.major)
        minor = int(version_tuple.minor)
    except (TypeError, ValueError, AttributeError) as e:
        raise MicroversionParseError(version_str) from e

    # Validate version is in supported range
    # Placement only supports major version 1
    if major != 1:
        raise MicroversionNotAcceptable(version_str)

    if minor < MIN_SUPPORTED_MINOR or minor > MAX_SUPPORTED_MINOR:
        raise MicroversionNotAcceptable(version_str)

    return Microversion(major, minor)


def parse(header_value: str | None) -> Microversion:
    """Parse the OpenStack-API-Version header into a Microversion.

    This is a lenient parser that defaults to 1.0 on errors.
    For strict validation, use parse_with_validation().

    :param header_value: Value of the OpenStack-API-Version header
    :returns: Microversion instance
    """
    try:
        return parse_with_validation(header_value)
    except (MicroversionParseError, MicroversionNotAcceptable):
        return Microversion(1, 0)


def min_version_string() -> str:
    """Return the minimum supported version as a string."""
    return f"1.{MIN_SUPPORTED_MINOR}"


def max_version_string() -> str:
    """Return the maximum supported version as a string."""
    return f"1.{MAX_SUPPORTED_MINOR}"
