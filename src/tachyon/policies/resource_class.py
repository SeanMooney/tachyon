# SPDX-License-Identifier: Apache-2.0

"""Resource class policy rules."""

from __future__ import annotations

from oslo_policy import policy

from tachyon.policies import base

PREFIX = "placement:resource_classes:%s"
LIST = PREFIX % "list"
CREATE = PREFIX % "create"
SHOW = PREFIX % "show"
UPDATE = PREFIX % "update"
DELETE = PREFIX % "delete"

rules = [
    policy.DocumentedRuleDefault(
        name=LIST,
        check_str=base.ADMIN_OR_SERVICE,
        description="List resource classes.",
        operations=[
            {
                "method": "GET",
                "path": "/resource_classes",
            }
        ],
        scope_types=["project"],
    ),
    policy.DocumentedRuleDefault(
        name=CREATE,
        check_str=base.ADMIN_OR_SERVICE,
        description="Create resource class.",
        operations=[
            {
                "method": "POST",
                "path": "/resource_classes",
            }
        ],
        scope_types=["project"],
    ),
    policy.DocumentedRuleDefault(
        name=SHOW,
        check_str=base.ADMIN_OR_SERVICE,
        description="Show resource class.",
        operations=[
            {
                "method": "GET",
                "path": "/resource_classes/{name}",
            }
        ],
        scope_types=["project"],
    ),
    policy.DocumentedRuleDefault(
        name=UPDATE,
        check_str=base.ADMIN_OR_SERVICE,
        description="Update resource class.",
        operations=[
            {
                "method": "PUT",
                "path": "/resource_classes/{name}",
            }
        ],
        scope_types=["project"],
    ),
    policy.DocumentedRuleDefault(
        name=DELETE,
        check_str=base.ADMIN_OR_SERVICE,
        description="Delete resource class.",
        operations=[
            {
                "method": "DELETE",
                "path": "/resource_classes/{name}",
            }
        ],
        scope_types=["project"],
    ),
]


def list_rules() -> list[policy.DocumentedRuleDefault]:
    """Return resource class policy rules.

    :returns: List of DocumentedRuleDefault instances
    """
    return rules
