# SPDX-License-Identifier: Apache-2.0

"""Request context for Tachyon API.

Provides RequestContext class that integrates with oslo.context and
oslo.policy for authentication and authorization.
"""

from __future__ import annotations

from typing import Any

from oslo_context import context
from oslo_log import log as logging

from tachyon import policy

LOG = logging.getLogger(__name__)


class RequestContext(context.RequestContext):
    """Security context for Tachyon API requests.

    Extends oslo.context.RequestContext with policy checking capabilities.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the request context.

        :param args: Positional arguments passed to parent
        :param kwargs: Keyword arguments passed to parent
        """
        # Extract any tachyon-specific kwargs before passing to parent
        self.config = kwargs.pop("config", None)
        super().__init__(*args, **kwargs)

    def can(
        self,
        action: str,
        target: dict[str, Any] | None = None,
        fatal: bool = True,
    ) -> bool:
        """Check if the action is allowed on the target.

        Verifies that the given action is valid on the target in this context.

        :param action: String representing the action to be checked, e.g.
            ``placement:resource_providers:list``
        :param target: Dictionary with information about the object being
            operated on. For object creation this should be a dictionary
            representing the location of the object e.g.
            ``{'project_id': context.project_id}``. If None, then this default
            target will be considered:
            ``{'project_id': self.project_id, 'user_id': self.user_id}``
        :param fatal: If True (the default), raises PolicyNotAuthorized;
            if False, returns False on authorization failure.
        :raises policy.PolicyNotAuthorized: If verification fails and fatal
            is True.
        :returns: True if authorized, False if not authorized and fatal is
            False.
        """
        if target is None:
            target = {"project_id": self.project_id, "user_id": self.user_id}

        try:
            return policy.authorize(self, action, target)
        except policy.PolicyNotAuthorized:
            if fatal:
                raise
            return False

    @classmethod
    def from_environ(
        cls,
        environ: dict[str, Any],
        **kwargs: Any,
    ) -> "RequestContext":
        """Create a context from a WSGI environ dict.

        Creates a RequestContext from the headers set by keystonemiddleware
        auth_token middleware.

        :param environ: WSGI environ dictionary
        :param kwargs: Additional keyword arguments for the context
        :returns: RequestContext instance
        """
        # Extract request ID if present
        request_id = environ.get("openstack.request_id")

        # Create context from environ using parent class method
        ctx = super().from_environ(environ, **kwargs)

        # If parent didn't get a request_id, try our custom location
        if not ctx.request_id and request_id:
            ctx.request_id = request_id

        return ctx
