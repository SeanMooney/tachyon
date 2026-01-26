# SPDX-License-Identifier: Apache-2.0

"""Allocation policy rules."""

from __future__ import annotations

from oslo_policy import policy

from tachyon.policies import base

PREFIX = "placement:allocations:%s"
LIST = PREFIX % "list"
MANAGE = PREFIX % "manage"
UPDATE = PREFIX % "update"
DELETE = PREFIX % "delete"

rules = [
    policy.DocumentedRuleDefault(
        name=LIST,
        check_str=base.ADMIN_OR_SERVICE,
        description="List allocations for a consumer.",
        operations=[
            {
                "method": "GET",
                "path": "/allocations/{consumer_uuid}",
            }
        ],
        scope_types=["project"],
    ),
    policy.DocumentedRuleDefault(
        name=MANAGE,
        check_str=base.ADMIN_OR_SERVICE,
        description="Manage allocations for multiple consumers.",
        operations=[
            {
                "method": "POST",
                "path": "/allocations",
            }
        ],
        scope_types=["project"],
    ),
    policy.DocumentedRuleDefault(
        name=UPDATE,
        check_str=base.ADMIN_OR_SERVICE,
        description="Update allocations for a consumer.",
        operations=[
            {
                "method": "PUT",
                "path": "/allocations/{consumer_uuid}",
            }
        ],
        scope_types=["project"],
    ),
    policy.DocumentedRuleDefault(
        name=DELETE,
        check_str=base.ADMIN_OR_SERVICE,
        description="Delete allocations for a consumer.",
        operations=[
            {
                "method": "DELETE",
                "path": "/allocations/{consumer_uuid}",
            }
        ],
        scope_types=["project"],
    ),
]


def list_rules() -> list[policy.DocumentedRuleDefault]:
    """Return allocation policy rules.

    :returns: List of DocumentedRuleDefault instances
    """
    return rules
