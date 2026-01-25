# SPDX-License-Identifier: Apache-2.0

"""Resource provider policy rules."""

from __future__ import annotations

from oslo_policy import policy

from tachyon.policies import base

PREFIX = "placement:resource_providers:%s"
LIST = PREFIX % "list"
CREATE = PREFIX % "create"
SHOW = PREFIX % "show"
UPDATE = PREFIX % "update"
DELETE = PREFIX % "delete"

rules = [
    policy.DocumentedRuleDefault(
        name=LIST,
        check_str=base.ADMIN_OR_SERVICE,
        description="List resource providers.",
        operations=[
            {
                "method": "GET",
                "path": "/resource_providers",
            }
        ],
        scope_types=["project"],
    ),
    policy.DocumentedRuleDefault(
        name=CREATE,
        check_str=base.ADMIN_OR_SERVICE,
        description="Create resource provider.",
        operations=[
            {
                "method": "POST",
                "path": "/resource_providers",
            }
        ],
        scope_types=["project"],
    ),
    policy.DocumentedRuleDefault(
        name=SHOW,
        check_str=base.ADMIN_OR_SERVICE,
        description="Show resource provider.",
        operations=[
            {
                "method": "GET",
                "path": "/resource_providers/{uuid}",
            }
        ],
        scope_types=["project"],
    ),
    policy.DocumentedRuleDefault(
        name=UPDATE,
        check_str=base.ADMIN_OR_SERVICE,
        description="Update resource provider.",
        operations=[
            {
                "method": "PUT",
                "path": "/resource_providers/{uuid}",
            }
        ],
        scope_types=["project"],
    ),
    policy.DocumentedRuleDefault(
        name=DELETE,
        check_str=base.ADMIN_OR_SERVICE,
        description="Delete resource provider.",
        operations=[
            {
                "method": "DELETE",
                "path": "/resource_providers/{uuid}",
            }
        ],
        scope_types=["project"],
    ),
]


def list_rules() -> list[policy.DocumentedRuleDefault]:
    """Return resource provider policy rules.

    :returns: List of DocumentedRuleDefault instances
    """
    return rules
