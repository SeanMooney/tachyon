# SPDX-License-Identifier: Apache-2.0

"""Request middleware for authentication and microversions."""

from __future__ import annotations

import flask
import werkzeug

from oslo_log import log

from tachyon.api import errors
from tachyon.api import microversion

LOG = log.getLogger(__name__)


def _accepts_json() -> bool:
    """Check if the client accepts application/json.

    Handles standard Accept header parsing including wildcards.

    :returns: True if client accepts JSON responses
    """
    accept = flask.request.headers.get("Accept", "")
    if not accept:
        return True  # No Accept header means accept anything

    # Parse Accept header - simplified but handles common cases
    parts = accept.lower().split(",")
    for part in parts:
        media_type = part.split(";")[0].strip()
        if media_type in ("application/json", "*/*", "application/*"):
            return True
    return False


def register(app: flask.Flask) -> None:
    """Register middleware for auth and microversion handling.

    :param app: Flask application instance
    """
    LOG.debug("Registering middleware")

    @app.before_request
    def _set_context() -> None:
        """Set minimal request context placeholder."""
        flask.g.context = {
            "user_id": flask.request.headers.get("X-User-Id"),
            "project_id": flask.request.headers.get("X-Project-Id"),
            "roles": flask.request.headers.get("X-Roles", "").split(","),
        }

    @app.before_request
    def _set_microversion() -> None:
        """Parse and set microversion from request headers."""
        header = flask.request.headers.get("OpenStack-API-Version")
        flask.g.microversion = microversion.parse(header)
        flask.g.microversion_header = header or "placement 1.0"

    @app.after_request
    def _add_microversion_headers(response: flask.Response) -> flask.Response:
        """Add microversion response headers."""
        mv = getattr(flask.g, "microversion", microversion.Microversion(1, 0))
        # When "latest" was requested, report the actual max version
        minor = mv.minor
        if minor == microversion.LATEST_MINOR:
            minor = microversion.MAX_SUPPORTED_MINOR
        response.headers["OpenStack-API-Version"] = "placement %s.%s" % (
            mv.major,
            minor,
        )
        response.headers["Vary"] = "OpenStack-API-Version"
        return response

    @app.before_request
    def _check_accept() -> None:
        """Validate Accept header for JSON responses."""
        # Skip check for root endpoint
        if flask.request.path == "/":
            return

        # Check if this path matches a valid route - if not, let it 404
        adapter = app.url_map.bind("")
        try:
            adapter.match(flask.request.path, method=flask.request.method)
        except werkzeug.exceptions.HTTPException:
            # Route doesn't exist, let it 404 naturally
            return

        if not _accepts_json():
            flask.abort(406)

    @app.before_request
    def _check_content_type() -> None:
        """Validate Content-Type header for requests with bodies."""
        # Only check for methods that typically have bodies
        if flask.request.method in ("POST", "PUT", "PATCH"):
            content_type = flask.request.content_type or ""
            content_length = flask.request.content_length

            # If there's content, check the content type
            if content_length and content_length > 0:
                if not content_type:
                    raise errors.BadRequest(
                        "content-type header required when body is present"
                    )

                # Check if it's application/json
                if not content_type.startswith("application/json"):
                    flask.abort(415)
