# SPDX-License-Identifier: Apache-2.0

"""Root API blueprint.

Implements the Placement-compatible root endpoint for version discovery.
"""

from __future__ import annotations

import datetime

import flask

from tachyon.api import microversion

bp = flask.Blueprint("root", __name__)

# Placement API version range
MIN_VERSION = "1.0"
MAX_VERSION = "1.39"


def _mv():
    """Return the parsed microversion from the request context.

    :returns: Microversion instance
    """
    mv = getattr(flask.g, "microversion", None)
    if mv is None:
        return microversion.Microversion(1, 0)
    return mv


def _httpdate(dt=None):
    """Return an HTTP-date string.

    :param dt: Optional datetime, defaults to now
    :returns: HTTP-date formatted string
    """
    dt = dt or datetime.datetime.now(datetime.timezone.utc)
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")


@bp.route("/", methods=["GET"])
def home():
    """Return version discovery information.

    Returns API version information following the OpenStack API guidelines
    for version discovery.

    :returns: Tuple of (response, status_code)
    """
    mv = _mv()

    version_data = {
        "id": "v%s" % MIN_VERSION,
        "max_version": MAX_VERSION,
        "min_version": MIN_VERSION,
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
