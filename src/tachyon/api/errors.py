# SPDX-License-Identifier: Apache-2.0

"""Placement-compatible error handling for Tachyon API.

Error responses follow the OpenStack Placement API format::

    {
        "errors": [
            {
                "status": <http_status_code>,
                "title": "<error_title>",
                "detail": "<error_detail>",
                "code": "<error_code>"  # Only at microversion 1.23+
            }
        ]
    }

Exception classes use the OpenStack msg_fmt pattern for consistent
error message formatting with keyword argument substitution.

Error codes follow the Placement API specification and are documented at:
http://specs.openstack.org/openstack/api-wg/guidelines/errors.html
"""

from __future__ import annotations

from typing import Any

import flask

from oslo_log import log

LOG = log.getLogger(__name__)

# Error code constants - match Placement API exactly
# Do not change the string values. Once set, they are set.
DEFAULT = "placement.undefined_code"
INVENTORY_INUSE = "placement.inventory.inuse"
CONCURRENT_UPDATE = "placement.concurrent_update"
DUPLICATE_NAME = "placement.duplicate_name"
PROVIDER_IN_USE = "placement.resource_provider.inuse"
PROVIDER_CANNOT_DELETE_PARENT = "placement.resource_provider.cannot_delete_parent"
RESOURCE_PROVIDER_NOT_FOUND = "placement.resource_provider.not_found"
ILLEGAL_DUPLICATE_QUERYPARAM = "placement.query.duplicate_key"
QUERYPARAM_BAD_VALUE = "placement.query.bad_value"
QUERYPARAM_MISSING_VALUE = "placement.query.missing_value"


def _should_include_error_code() -> bool:
    """Check if error codes should be included based on microversion.

    Error codes are only included at microversion 1.23+.
    """
    mv = getattr(flask.g, "microversion", None)
    if mv is None:
        return False
    return mv.is_at_least(23)


class TachyonException(Exception):
    """Base exception for all Tachyon errors.

    Uses OpenStack-style msg_fmt for consistent message formatting.
    Supports keyword argument substitution via %(key)s syntax.

    :ivar msg_fmt: Default message format string
    :ivar status_code: HTTP status code for this error type
    :ivar title: Short error title for response
    :ivar code: Optional programmatic error code
    """

    msg_fmt = "%(reason)s"
    status_code = 500
    title = "Internal Server Error"
    code: str | None = None

    def __init__(self, reason: str | None = None, **kwargs: Any) -> None:
        """Initialize the exception with message formatting.

        :param reason: Simple reason string (for backward compatibility)
        :param kwargs: Keyword arguments for msg_fmt substitution
        """
        # Handle code override from kwargs
        if "code" in kwargs:
            self.code = kwargs.pop("code")

        self.kwargs = kwargs
        if reason is not None:
            self.kwargs["reason"] = reason

        # Format the message using msg_fmt and kwargs
        try:
            self.detail = self.msg_fmt % self.kwargs
        except (KeyError, TypeError):
            # Fallback if formatting fails
            if reason:
                self.detail = reason
            else:
                self.detail = self.msg_fmt

        super().__init__(self.detail)

    def to_response(self) -> tuple[flask.Response, int]:
        """Convert exception to a Placement-compatible JSON response.

        Error codes are only included at microversion 1.23+.

        :returns: Tuple of (JSON response, status code)
        """
        error: dict[str, Any] = {
            "status": self.status_code,
            "title": self.title,
            "detail": self.detail,
        }
        # Error codes only at microversion 1.23+
        if self.code and _should_include_error_code():
            error["code"] = self.code

        body = {"errors": [error]}
        return flask.jsonify(body), self.status_code


# Backward compatibility alias
APIError = TachyonException


class NotFound(TachyonException):
    """Resource not found (404).

    :Usage:
        raise NotFound(resource_type="resource provider", uuid=rp_uuid)
        raise NotFound(reason="Custom not found message")
    """

    msg_fmt = "No %(resource_type)s with uuid %(uuid)s found"
    status_code = 404
    title = "Not Found"

    def __init__(
        self,
        reason: str | None = None,
        resource_type: str | None = None,
        uuid: str | None = None,
        **kwargs: Any,
    ) -> None:
        if resource_type is not None:
            kwargs["resource_type"] = resource_type
        if uuid is not None:
            kwargs["uuid"] = uuid
        super().__init__(reason=reason, **kwargs)


class Conflict(TachyonException):
    """Resource conflict, typically generation mismatch (409).

    :Usage:
        raise Conflict(resource_type="resource provider", uuid=rp_uuid)
        raise Conflict(reason="Generation mismatch")
    """

    msg_fmt = "Conflict for %(resource_type)s %(uuid)s"
    status_code = 409
    title = "Conflict"


class Forbidden(TachyonException):
    """Forbidden access (403).

    :Usage:
        raise Forbidden(reason="Admin role required.")
    """

    msg_fmt = "Access forbidden: %(reason)s"
    status_code = 403
    title = "Forbidden"


class PolicyNotAuthorized(Forbidden):
    """Policy authorization failure (403).

    Raised when a policy check fails for the requested action.

    :Usage:
        raise PolicyNotAuthorized(action="placement:resource_providers:list")
    """

    msg_fmt = "Policy doesn't allow %(action)s to be performed."

    def __init__(self, action: str, **kwargs: Any) -> None:
        """Initialize PolicyNotAuthorized.

        :param action: The policy action that was denied
        :param kwargs: Additional keyword arguments
        """
        kwargs["action"] = action
        super().__init__(**kwargs)


class BadRequest(TachyonException):
    """Invalid request (400).

    :Usage:
        raise BadRequest(reason="'name' is a required property")
        raise BadRequest(field="name", error="is required")
    """

    msg_fmt = "%(reason)s"
    status_code = 400
    title = "Bad Request"


class InvalidInventory(BadRequest):
    """Invalid inventory values.

    :Usage:
        raise InvalidInventory(field="total", error="must be positive")
    """

    msg_fmt = "Invalid inventory: %(field)s %(error)s"
    title = "Invalid Inventory"


class InventoryInUse(Conflict):
    """Cannot delete inventory with active allocations.

    :Usage:
        raise InventoryInUse(resource_class=rc_name, allocation_count=5)
    """

    msg_fmt = (
        "Inventory for %(resource_class)s has %(allocation_count)s active allocations"
    )
    title = "Inventory In Use"
    code = INVENTORY_INUSE


class ResourceProviderInUse(Conflict):
    """Cannot delete resource provider with allocations or children.

    :Usage:
        raise ResourceProviderInUse(uuid=rp_uuid, reason="has children")
    """

    msg_fmt = "Unable to delete resource provider %(uuid)s: %(reason)s"
    title = "Resource Provider In Use"
    code = PROVIDER_IN_USE


class CannotDeleteParentResourceProvider(Conflict):
    """Cannot delete a resource provider that has child providers.

    :Usage:
        raise CannotDeleteParentResourceProvider(uuid=rp_uuid)
    """

    msg_fmt = (
        "Unable to delete parent resource provider %(uuid)s: "
        "It has child resource providers."
    )
    title = "Conflict"
    code = PROVIDER_CANNOT_DELETE_PARENT


class ConsumerGenerationConflict(Conflict):
    """Consumer generation mismatch.

    :Usage:
        raise ConsumerGenerationConflict(uuid=consumer_uuid, expected=0, got=1)
    """

    msg_fmt = (
        "Consumer %(uuid)s generation mismatch: expected %(expected)s, got %(got)s"
    )
    title = "Consumer Generation Conflict"
    code = CONCURRENT_UPDATE


class ResourceProviderGenerationConflict(Conflict):
    """Resource provider generation mismatch.

    :Usage:
        raise ResourceProviderGenerationConflict(uuid=rp_uuid)
    """

    msg_fmt = "resource provider generation conflict"
    title = "Conflict"
    code = CONCURRENT_UPDATE


class NotAcceptable(TachyonException):
    """Not acceptable content type (406).

    :Usage:
        raise NotAcceptable(reason="Only application/json is provided")
    """

    msg_fmt = "Not acceptable: %(reason)s"
    status_code = 406
    title = "Not Acceptable"


class UnsupportedMediaType(TachyonException):
    """Unsupported media type (415).

    :Usage:
        raise UnsupportedMediaType(content_type="text/plain")
    """

    msg_fmt = "The media type %(content_type)s is not supported, use application/json"
    status_code = 415
    title = "Unsupported Media Type"


class DuplicateName(Conflict):
    """Resource with this name already exists.

    :Usage:
        raise DuplicateName(resource_type="resource provider", name=name)
    """

    msg_fmt = "Conflicting %(resource_type)s name: %(name)s already exists"
    code = DUPLICATE_NAME


class DuplicateUUID(Conflict):
    """Resource with this UUID already exists.

    :Usage:
        raise DuplicateUUID(resource_type="resource provider", uuid=uuid)
    """

    msg_fmt = "Conflicting %(resource_type)s uuid: %(uuid)s already exists"


def error_response(status: int, title: str, detail: str) -> tuple[flask.Response, int]:
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


def register_handlers(app: flask.Flask) -> None:
    """Register error handlers for common HTTP errors and TachyonException.

    :param app: Flask application instance
    """
    # Import here to avoid circular imports
    from tachyon import policy

    LOG.debug("Registering error handlers")

    @app.errorhandler(TachyonException)
    def handle_tachyon_error(error: TachyonException) -> tuple[flask.Response, int]:
        """Handle TachyonException subclasses."""
        LOG.debug("Handling %s: %s", type(error).__name__, error.detail)
        return error.to_response()

    @app.errorhandler(policy.PolicyNotAuthorized)
    def handle_policy_error(
        error: policy.PolicyNotAuthorized,
    ) -> tuple[flask.Response, int]:
        """Handle policy authorization failures."""
        LOG.debug("Policy not authorized: %s", error.action)
        api_error = PolicyNotAuthorized(action=error.action)
        return api_error.to_response()

    @app.errorhandler(404)
    def not_found(error: Exception) -> tuple[flask.Response, int]:
        return error_response(404, "Not Found", "The resource could not be found.")

    @app.errorhandler(409)
    def conflict(error: Exception) -> tuple[flask.Response, int]:
        return error_response(
            409, "Conflict", "A conflict occurred with the current state."
        )

    @app.errorhandler(400)
    def bad_request(error: Exception) -> tuple[flask.Response, int]:
        return error_response(400, "Bad Request", "The request is invalid.")

    @app.errorhandler(405)
    def method_not_allowed(error: Exception) -> tuple[flask.Response, int]:
        method = flask.request.method
        resp, status = error_response(
            405,
            "Method Not Allowed",
            "The method %s is not allowed for this resource." % method,
        )
        if hasattr(error, "valid_methods") and error.valid_methods:
            resp.headers["Allow"] = ", ".join(sorted(error.valid_methods))
        return resp, status

    @app.errorhandler(406)
    def not_acceptable(error: Exception) -> tuple[flask.Response, int]:
        return error_response(
            406, "Not Acceptable", "Only application/json is provided"
        )

    @app.errorhandler(415)
    def unsupported_media_type(error: Exception) -> tuple[flask.Response, int]:
        content_type = flask.request.content_type
        return error_response(
            415,
            "Unsupported Media Type",
            "The media type %s is not supported, use application/json" % content_type,
        )

    @app.errorhandler(500)
    def internal_error(error: Exception) -> tuple[flask.Response, int]:
        LOG.exception("Internal server error")
        return error_response(
            500, "Internal Server Error", "An unexpected error occurred."
        )
