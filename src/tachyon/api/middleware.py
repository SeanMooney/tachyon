# SPDX-License-Identifier: Apache-2.0

"""Request middleware for authentication and microversions."""

from __future__ import annotations

import flask
import werkzeug

from oslo_log import log

from tachyon.api import errors
from tachyon.api import microversion
from tachyon import context as tachyon_context

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
        """Set request context from WSGI environ or create from headers.

        The auth middleware (TachyonKeystoneContext) places the context in
        the WSGI environ as 'tachyon.context'. If running without the WSGI
        middleware stack (e.g., Flask dev server or functional tests),
        create the context from request headers.

        Supports noauth2 mode: if X-Auth-Token is present but X-User-Id is not,
        parse user/project from the token and set appropriate roles.
        """
        # Try to get context from WSGI environ (set by auth middleware)
        ctx = flask.request.environ.get("tachyon.context")

        if ctx is None:
            # Create context from request headers (Flask dev server case)
            # This is primarily for development/testing
            user_id = flask.request.headers.get("X-User-Id")
            project_id = flask.request.headers.get("X-Project-Id")
            roles_header = flask.request.headers.get("X-Roles", "")

            # Handle noauth2 mode: parse token if X-User-Id not provided
            if user_id is None and "X-Auth-Token" in flask.request.headers:
                token = flask.request.headers["X-Auth-Token"]
                user_id, _sep, project_id_from_token = token.partition(":")
                project_id = project_id or project_id_from_token or user_id
                # Set admin roles for "admin" token (noauth2 convention)
                if not roles_header:
                    if user_id == "admin":
                        roles_header = "admin,member,reader"
                    else:
                        roles_header = "member,reader"

            roles = [r.strip() for r in roles_header.split(",") if r.strip()]

            ctx = tachyon_context.RequestContext(
                user_id=user_id,
                project_id=project_id,
                roles=roles,
            )

        flask.g.context = ctx

    @app.before_request
    def _set_microversion() -> flask.Response | None:
        """Parse and set microversion from request headers.

        Returns 400 Bad Request for malformed version strings.
        Returns 406 Not Acceptable for unsupported versions.
        """
        header = flask.request.headers.get("OpenStack-API-Version")

        try:
            flask.g.microversion = microversion.parse_with_validation(header)
            flask.g.microversion_header = header or "placement 1.0"
            return None
        except microversion.MicroversionParseError as e:
            # 400 Bad Request for malformed version strings
            flask.g.microversion = microversion.Microversion(1, 0)
            flask.g.microversion_header = "placement 1.0"
            body = {
                "errors": [
                    {
                        "status": 400,
                        "title": "Bad Request",
                        "detail": f"invalid version string: {e.version_string}",
                    }
                ]
            }
            response = flask.jsonify(body)
            response.status_code = 400
            return response
        except microversion.MicroversionNotAcceptable as e:
            # 406 Not Acceptable for unsupported versions
            flask.g.microversion = microversion.Microversion(1, 0)
            flask.g.microversion_header = "placement 1.0"

            # Check Accept header to determine response format
            accept = flask.request.headers.get("Accept", "")
            if "text/html" in accept.lower():
                response = flask.Response(
                    f"Unacceptable version header: {e.version_string}",
                    status=406,
                    content_type="text/html",
                )
            else:
                body = {
                    "errors": [
                        {
                            "status": 406,
                            "title": "Not Acceptable",
                            "detail": f"Unacceptable version header: {e.version_string}",
                        }
                    ]
                }
                response = flask.jsonify(body)
                response.status_code = 406

            return response

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
        response.headers["Vary"] = "openstack-api-version"
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
