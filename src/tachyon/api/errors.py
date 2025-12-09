"""Placement-compatible error handling for Tachyon API.

Error responses follow the OpenStack Placement API format:
{
    "errors": [
        {
            "status": <http_status_code>,
            "title": "<error_title>",
            "detail": "<error_detail>"
        }
    ]
}
"""

from __future__ import annotations

from typing import Any

from flask import Flask, Response, jsonify


class APIError(Exception):
    """Base exception for API errors with Placement-compatible formatting."""

    status_code: int = 500
    title: str = "Internal Server Error"
    code: str | None = None

    def __init__(self, detail: str | None = None, code: str | None = None):
        super().__init__(detail)
        self.detail = detail or self.title
        self.code = code or getattr(self, "code", None)

    def to_response(self) -> tuple[Response, int]:
        """Convert exception to a Placement-compatible JSON response."""
        error = {
            "status": self.status_code,
            "title": self.title,
            "detail": self.detail,
        }
        if self.code:
            error["code"] = self.code

        body = {"errors": [error]}
        return jsonify(body), self.status_code


class NotFound(APIError):
    """Resource not found (404)."""

    status_code = 404
    title = "Not Found"


class Conflict(APIError):
    """Resource conflict, typically generation mismatch (409)."""

    status_code = 409
    title = "Conflict"


class Forbidden(APIError):
    """Forbidden access (403)."""

    status_code = 403
    title = "Forbidden"


class BadRequest(APIError):
    """Invalid request (400)."""

    status_code = 400
    title = "Bad Request"


class InvalidInventory(BadRequest):
    """Invalid inventory values."""

    title = "Invalid Inventory"


class InventoryInUse(Conflict):
    """Cannot delete inventory with active allocations."""

    title = "Inventory In Use"


class ResourceProviderInUse(Conflict):
    """Cannot delete resource provider with allocations or children."""

    title = "Resource Provider In Use"


class ConsumerGenerationConflict(Conflict):
    """Consumer generation mismatch."""

    title = "Consumer Generation Conflict"


class ResourceProviderGenerationConflict(Conflict):
    """Resource provider generation mismatch."""

    title = "Conflict"
    code = "placement.concurrent_update"


def error_response(status: int, title: str, detail: str) -> tuple[Response, int]:
    """Create a Placement-compatible error response.

    Args:
        status: HTTP status code.
        title: Short error title.
        detail: Detailed error message.

    Returns:
        Tuple of (JSON response, status code).
    """
    body = {
        "errors": [
            {
                "status": status,
                "title": title,
                "detail": detail,
            }
        ]
    }
    return jsonify(body), status


def register_handlers(app: Flask) -> None:
    """Register error handlers for common HTTP errors and APIError exceptions."""

    @app.errorhandler(APIError)
    def handle_api_error(error: APIError) -> tuple[Response, int]:
        """Handle APIError subclasses."""
        return error.to_response()

    @app.errorhandler(404)
    def not_found(error: Any) -> tuple[Response, int]:
        return error_response(404, "Not Found", "The resource could not be found.")

    @app.errorhandler(409)
    def conflict(error: Any) -> tuple[Response, int]:
        return error_response(
            409, "Conflict", "A conflict occurred with the current state."
        )

    @app.errorhandler(400)
    def bad_request(error: Any) -> tuple[Response, int]:
        return error_response(400, "Bad Request", "The request is invalid.")

    @app.errorhandler(405)
    def method_not_allowed(error: Any) -> tuple[Response, int]:
        return error_response(
            405, "Method Not Allowed", "The method is not allowed for this resource."
        )

    @app.errorhandler(500)
    def internal_error(error: Any) -> tuple[Response, int]:
        return error_response(
            500, "Internal Server Error", "An unexpected error occurred."
        )
