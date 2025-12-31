"""Root API blueprint.

Implements the Placement-compatible root endpoint for version discovery.
"""

from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, Response, g, jsonify

from tachyon.api.microversion import Microversion

bp = Blueprint("root", __name__)

# Placement API version range
MIN_VERSION = "1.0"
MAX_VERSION = "1.39"


def _mv() -> Microversion:
    """Return the parsed microversion from the request context."""
    mv = getattr(g, "microversion", None)
    if mv is None:
        return Microversion(1, 0)
    return mv


def _httpdate(dt: datetime | None = None) -> str:
    """Return an HTTP-date string."""
    dt = dt or datetime.now(timezone.utc)
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")


@bp.route("/", methods=["GET"])
def home() -> tuple[Response, int]:
    """Return version discovery information.

    Returns API version information following the OpenStack API guidelines
    for version discovery.
    """
    mv = _mv()

    version_data = {
        "id": f"v{MIN_VERSION}",
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

    resp = jsonify({"versions": [version_data]})
    resp.content_type = "application/json"

    if mv.is_at_least(15):
        resp.headers["cache-control"] = "no-cache"
        resp.headers["last-modified"] = _httpdate()

    return resp, 200

