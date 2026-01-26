# SPDX-License-Identifier: Apache-2.0

"""Aggregate policy rules."""

from __future__ import annotations

from oslo_policy import policy

from tachyon.policies import base

PREFIX = "placement:resource_providers:aggregates:%s"
LIST = PREFIX % "list"
UPDATE = PREFIX % "update"

rules = [
    policy.DocumentedRuleDefault(
        name=LIST,
        check_str=base.ADMIN_OR_SERVICE,
        description="List aggregates for a resource provider.",
        operations=[
            {
                "method": "GET",
                "path": "/resource_providers/{uuid}/aggregates",
            }
        ],
        scope_types=["project"],
    ),
    policy.DocumentedRuleDefault(
        name=UPDATE,
        check_str=base.ADMIN_OR_SERVICE,
        description="Update aggregates for a resource provider.",
        operations=[
            {
                "method": "PUT",
                "path": "/resource_providers/{uuid}/aggregates",
            }
        ],
        scope_types=["project"],
    ),
]


def list_rules() -> list[policy.DocumentedRuleDefault]:
    """Return aggregate policy rules.

    :returns: List of DocumentedRuleDefault instances
    """
    return rules
