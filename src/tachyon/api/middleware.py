from __future__ import annotations

from flask import g, request

from tachyon.api import microversion


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
