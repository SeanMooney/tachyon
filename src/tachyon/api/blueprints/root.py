# SPDX-License-Identifier: Apache-2.0

"""Root API blueprint.

Implements the Placement-compatible root endpoint for version discovery.
"""

from __future__ import annotations

import datetime
from typing import Any

import flask

from oslo_log import log

from tachyon.api import microversion

LOG = log.getLogger(__name__)

bp = flask.Blueprint("root", __name__)


def _mv() -> microversion.Microversion:
    """Return the parsed microversion from the request context.

    :returns: Microversion instance
    """
    mv: microversion.Microversion | None = getattr(flask.g, "microversion", None)
    if mv is None:
        return microversion.Microversion(1, 0)
    return mv


def _httpdate(dt: datetime.datetime | None = None) -> str:
    """Return an HTTP-date string.

    :param dt: Optional datetime, defaults to now
    :returns: HTTP-date formatted string
    """
    dt = dt or datetime.datetime.now(datetime.timezone.utc)
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")


@bp.route("/", methods=["GET"])
def home() -> tuple[flask.Response, int]:
    """Return version discovery information.

    Returns API version information following the OpenStack API guidelines
    for version discovery.

    :returns: Tuple of (response, status_code)
    """
    mv = _mv()
    min_version = microversion.min_version_string()
    max_version = microversion.max_version_string()

    version_data: dict[str, Any] = {
        "id": "v%s" % min_version,
        "max_version": max_version,
        "min_version": min_version,
        "status": "CURRENT",
        "links": [
            {
                "rel": "self",
                "href": "",
            }
        ],
    }

    resp = flask.jsonify({"versions": [version_data]})
    resp.content_type = "application/json"

    if mv.is_at_least(15):
        resp.headers["cache-control"] = "no-cache"
        resp.headers["last-modified"] = _httpdate()

    return resp, 200
