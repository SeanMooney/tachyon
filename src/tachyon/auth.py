# SPDX-License-Identifier: Apache-2.0

"""Authentication middleware for Tachyon API.

Provides authentication middleware following the Placement API pattern:
- NoAuthMiddleware: For noauth2 mode (testing without Keystone)
- TachyonAuthProtocol: Wrapper on keystonemiddleware that skips auth for root
- TachyonKeystoneContext: Creates RequestContext from Keystone headers
"""

from __future__ import annotations

from typing import Any
from typing import Callable

from keystonemiddleware import auth_token
from oslo_log import log as logging
from oslo_middleware import request_id
import webob
import webob.dec
import webob.exc

from tachyon import context

LOG = logging.getLogger(__name__)

# Type aliases for WSGI
WSGIEnviron = dict[str, Any]
StartResponse = Callable[[str, list[tuple[str, str]]], Callable[[bytes], None]]
WSGIApp = Callable[[WSGIEnviron, StartResponse], list[bytes]]


class Middleware:
    """Base middleware class."""

    def __init__(self, application: WSGIApp, **kwargs: Any) -> None:
        """Initialize middleware.

        :param application: The WSGI application to wrap
        :param kwargs: Additional keyword arguments (ignored)
        """
        self.application = application


class NoAuthMiddleware(Middleware):
    """Middleware for noauth2 mode.

    Requires a token if one isn't present, and extracts user/project info
    from the token. Used for testing without Keystone.

    Token format: ``user_id:project_id`` or just ``user_id``
    If only user_id is provided, project_id defaults to the same value.
    """

    def __init__(self, application: WSGIApp) -> None:
        """Initialize NoAuthMiddleware.

        :param application: The WSGI application to wrap
        """
        self.application = application

    @webob.dec.wsgify
    def __call__(self, req: webob.Request) -> webob.Response | WSGIApp:
        """Process the request.

        :param req: The request object
        :returns: Response or calls the wrapped application
        """
        # Skip auth for root endpoint (version discovery)
        if req.environ["PATH_INFO"] == "/":
            return self.application

        # Require a token for all other endpoints
        if "X-Auth-Token" not in req.headers:
            return webob.exc.HTTPUnauthorized()

        token = req.headers["X-Auth-Token"]
        user_id, _sep, project_id = token.partition(":")
        project_id = project_id or user_id

        # Real keystone expands and flattens roles to include their implied
        # roles, e.g. admin implies member and reader, so tests should include
        # this flattened list also
        if "HTTP_X_ROLES" in req.environ.keys():
            roles = req.headers["X_ROLES"].split(",")
        elif user_id == "admin":
            roles = ["admin", "member", "reader"]
        else:
            roles = ["member", "reader"]

        req.headers["X_USER_ID"] = user_id

        if not req.headers.get("OPENSTACK_SYSTEM_SCOPE"):
            req.headers["X_TENANT_ID"] = project_id

        req.headers["X_ROLES"] = ",".join(roles)
        return self.application


class TachyonKeystoneContext(Middleware):
    """Middleware that creates RequestContext from Keystone headers."""

    @webob.dec.wsgify
    def __call__(self, req: webob.Request) -> webob.Response | WSGIApp:
        """Create RequestContext from Keystone headers.

        :param req: The request object
        :returns: Response or calls the wrapped application
        """
        req_id = req.environ.get(request_id.ENV_REQUEST_ID)

        ctx = context.RequestContext.from_environ(req.environ, request_id=req_id)

        # Require user_id for all endpoints except root
        if ctx.user_id is None and req.environ["PATH_INFO"] not in ["/", ""]:
            LOG.debug("Neither X_USER_ID nor X_USER found in request")
            return webob.exc.HTTPUnauthorized()

        req.environ["tachyon.context"] = ctx
        return self.application


class TachyonAuthProtocol(auth_token.AuthProtocol):
    """Wrapper on Keystone auth_token middleware.

    Does not perform verification of authentication tokens for root endpoint
    (version discovery).
    """

    def __init__(self, app: WSGIApp, conf: dict[str, Any]) -> None:
        """Initialize TachyonAuthProtocol.

        :param app: The WSGI application to wrap
        :param conf: Configuration dictionary
        """
        self._tachyon_app = app
        super().__init__(app, conf)

    def __call__(
        self, environ: WSGIEnviron, start_response: StartResponse
    ) -> list[bytes]:
        """Process the request.

        Skip authentication for root endpoint.

        :param environ: WSGI environ dictionary
        :param start_response: WSGI start_response callable
        :returns: Response body
        """
        if environ["PATH_INFO"] in ["/", ""]:
            return self._tachyon_app(environ, start_response)

        return super().__call__(environ, start_response)


def filter_factory(
    global_conf: dict[str, Any], **local_conf: Any
) -> Callable[[WSGIApp], TachyonAuthProtocol]:
    """Paste Deploy filter factory for TachyonAuthProtocol.

    :param global_conf: Global configuration dictionary
    :param local_conf: Local configuration dictionary
    :returns: Factory function that wraps an app with TachyonAuthProtocol
    """
    conf = global_conf.copy()
    conf.update(local_conf)

    def auth_filter(app: WSGIApp) -> TachyonAuthProtocol:
        return TachyonAuthProtocol(app, conf)

    return auth_filter
