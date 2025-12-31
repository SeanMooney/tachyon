# SPDX-License-Identifier: Apache-2.0

"""Placement-compatible error handling for Tachyon API.

Error responses follow the OpenStack Placement API format::

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

import flask


class APIError(Exception):
    """Base exception for API errors with Placement-compatible formatting."""

    status_code = 500
    title = "Internal Server Error"
    code = None

    def __init__(self, detail=None, code=None):
        """Initialize the API error.

        :param detail: Detailed error message
        :param code: Optional error code for programmatic handling
        """
        super(APIError, self).__init__(detail)
        self.detail = detail or self.title
        self.code = code or getattr(self, "code", None)

    def to_response(self):
        """Convert exception to a Placement-compatible JSON response.

        :returns: Tuple of (JSON response, status code)
        """
        error = {
            "status": self.status_code,
            "title": self.title,
            "detail": self.detail,
        }
        if self.code:
            error["code"] = self.code

        body = {"errors": [error]}
        return flask.jsonify(body), self.status_code


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


class NotAcceptable(APIError):
    """Not acceptable content type (406)."""

    status_code = 406
    title = "Not Acceptable"


class UnsupportedMediaType(APIError):
    """Unsupported media type (415)."""

    status_code = 415
    title = "Unsupported Media Type"


def error_response(status, title, detail):
    """Create a Placement-compatible error response.

    :param status: HTTP status code
    :param title: Short error title
    :param detail: Detailed error message
    :returns: Tuple of (JSON response, status code)
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
    return flask.jsonify(body), status


def register_handlers(app):
    """Register error handlers for common HTTP errors and APIError exceptions.

    :param app: Flask application instance
    """

    @app.errorhandler(APIError)
    def handle_api_error(error):
        """Handle APIError subclasses."""
        return error.to_response()

    @app.errorhandler(404)
    def not_found(error):
        return error_response(404, "Not Found", "The resource could not be found.")

    @app.errorhandler(409)
    def conflict(error):
        return error_response(
            409, "Conflict", "A conflict occurred with the current state."
        )

    @app.errorhandler(400)
    def bad_request(error):
        return error_response(400, "Bad Request", "The request is invalid.")

    @app.errorhandler(405)
    def method_not_allowed(error):
        method = flask.request.method
        resp, status = error_response(
            405, "Method Not Allowed",
            "The method %s is not allowed for this resource." % method
        )
        if hasattr(error, "valid_methods") and error.valid_methods:
            resp.headers["Allow"] = ", ".join(sorted(error.valid_methods))
        return resp, status

    @app.errorhandler(406)
    def not_acceptable(error):
        return error_response(
            406, "Not Acceptable", "Only application/json is provided"
        )

    @app.errorhandler(415)
    def unsupported_media_type(error):
        content_type = flask.request.content_type
        return error_response(
            415, "Unsupported Media Type",
            "The media type %s is not supported, use application/json"
            % content_type
        )

    @app.errorhandler(500)
    def internal_error(error):
        return error_response(
            500, "Internal Server Error", "An unexpected error occurred."
        )
