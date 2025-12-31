from __future__ import annotations

from flask import abort, g, request

from tachyon.api import microversion


def _accepts_json() -> bool:
    """Check if the client accepts application/json.

    Handles standard Accept header parsing including wildcards.
    """
    accept = request.headers.get("Accept", "")
    if not accept:
        return True  # No Accept header means accept anything

    # Parse Accept header - simplified but handles common cases
    parts = accept.lower().split(",")
    for part in parts:
        media_type = part.split(";")[0].strip()
        if media_type in ("application/json", "*/*", "application/*"):
            return True
    return False


def register(app) -> None:
    """Register placeholder middleware for auth and microversion."""

    @app.before_request
    def _set_context():
        # Minimal request context placeholder; expanded later.
        g.context = {
            "user_id": request.headers.get("X-User-Id"),
            "project_id": request.headers.get("X-Project-Id"),
            "roles": request.headers.get("X-Roles", "").split(","),
        }

    @app.before_request
    def _set_microversion():
        header = request.headers.get("OpenStack-API-Version")
        g.microversion = microversion.parse(header)
        g.microversion_header = header or "placement 1.0"

    @app.after_request
    def _add_microversion_headers(response):
        """Add microversion response headers."""
        mv = getattr(g, "microversion", microversion.Microversion(1, 0))
        # When "latest" was requested (minor == 999), report the actual max version
        minor = mv.minor
        if minor == microversion.LATEST_MINOR:
            minor = microversion.MAX_SUPPORTED_MINOR
        response.headers["OpenStack-API-Version"] = f"placement {mv.major}.{minor}"
        response.headers["Vary"] = "OpenStack-API-Version"
        return response

    @app.before_request
    def _check_accept():
        """Validate Accept header for JSON responses."""
        # Skip check for root endpoint
        if request.path == "/":
            return

        # Check if this path matches a valid route - if not, let it 404
        adapter = app.url_map.bind('')
        try:
            adapter.match(request.path, method=request.method)
        except Exception:
            # Route doesn't exist, let it 404 naturally
            return

        if not _accepts_json():
            abort(406)

    @app.before_request
    def _check_content_type():
        """Validate Content-Type header for requests with bodies."""
        # Only check for methods that typically have bodies
        if request.method in ("POST", "PUT", "PATCH"):
            content_type = request.content_type or ""
            content_length = request.content_length

            # If there's content, check the content type
            if content_length and content_length > 0:
                if not content_type:
                    from tachyon.api.errors import BadRequest
                    raise BadRequest("content-type header required when body is present")

                # Check if it's application/json
                if not content_type.startswith("application/json"):
                    abort(415)
