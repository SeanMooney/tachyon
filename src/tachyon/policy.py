# SPDX-License-Identifier: Apache-2.0

"""Policy Enforcement for Tachyon API.

This module provides oslo.policy integration for authorization checks.
Following the Placement API pattern for compatibility.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from oslo_config import cfg
from oslo_log import log as logging
from oslo_policy import opts as policy_opts
from oslo_policy import policy
from oslo_utils import excutils

if TYPE_CHECKING:
    from tachyon import context as tachyon_context

LOG = logging.getLogger(__name__)
_ENFORCER: policy.Enforcer | None = None


class PolicyNotAuthorized(Exception):
    """Exception raised when policy check fails.

    :param action: The policy action that was denied
    """

    def __init__(self, action: str) -> None:
        self.action = action
        super().__init__(f"Policy doesn't allow {action} to be performed.")


def reset() -> None:
    """Reset the global enforcer.

    Used to reset the global _ENFORCER between test runs.
    """
    global _ENFORCER
    if _ENFORCER:
        _ENFORCER.clear()
        _ENFORCER = None


def init(
    conf: cfg.ConfigOpts,
    suppress_deprecation_warnings: bool = False,
) -> None:
    """Initialize the policy enforcer.

    Sets the _ENFORCER global.

    :param conf: A ConfigOpts object to load configuration from.
    :param suppress_deprecation_warnings: Suppress policy deprecation warnings
        (primarily for testing).
    """
    global _ENFORCER
    if not _ENFORCER:
        # Import here to avoid circular imports
        from tachyon import policies

        _enforcer = policy.Enforcer(conf)

        # Suppress warnings for policy defaults changes
        _enforcer.suppress_default_change_warnings = True
        _enforcer.suppress_deprecation_warnings = suppress_deprecation_warnings

        _enforcer.register_defaults(policies.list_rules())
        _enforcer.load_rules()
        _ENFORCER = _enforcer


def get_enforcer() -> policy.Enforcer:
    """Get the policy enforcer, initializing if needed.

    This method is used by oslopolicy CLI scripts to generate policy
    files from overrides on disk and defaults in code.

    :returns: The policy enforcer instance
    """
    cfg.CONF([], project="tachyon")
    # Set default policy file to policy.yaml
    policy_opts.set_defaults(cfg.CONF, "policy.yaml")
    return _get_enforcer(cfg.CONF)


def _get_enforcer(conf: cfg.ConfigOpts) -> policy.Enforcer:
    """Internal method to get or initialize the enforcer.

    :param conf: Configuration options
    :returns: The policy enforcer instance
    """
    init(conf)
    assert _ENFORCER is not None
    return _ENFORCER


def authorize(
    context: "tachyon_context.RequestContext",
    action: str,
    target: dict | None = None,
    do_raise: bool = True,
) -> bool:
    """Verify that the action is valid on the target in this context.

    :param context: RequestContext instance
    :param action: String representing the action to be checked, e.g.
        ``placement:resource_providers:list``
    :param target: Dictionary representing the object of the action;
        for object creation this should be a dictionary representing the
        owner of the object e.g. ``{'project_id': context.project_id}``.
    :param do_raise: If True (the default), raises PolicyNotAuthorized;
        if False, returns False
    :raises PolicyNotAuthorized: If verification fails and do_raise is True.
    :returns: True if authorized, False if not authorized and do_raise is False
    """
    if target is None:
        target = {}

    assert _ENFORCER is not None, "Policy enforcer not initialized"

    try:
        return _ENFORCER.authorize(
            action,
            target,
            context,
            do_raise=do_raise,
            exc=PolicyNotAuthorized,
            action=action,
        )
    except policy.PolicyNotRegistered:
        with excutils.save_and_reraise_exception():
            LOG.exception("Policy not registered: %s", action)
    except policy.InvalidScope:
        raise PolicyNotAuthorized(action)
    except Exception:
        with excutils.save_and_reraise_exception():
            credentials = context.to_policy_values()
            LOG.debug(
                "Policy check for %(action)s failed with credentials %(credentials)s",
                {"action": action, "credentials": credentials},
            )
