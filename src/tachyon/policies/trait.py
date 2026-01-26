# SPDX-License-Identifier: Apache-2.0

"""Trait policy rules."""

from __future__ import annotations

from oslo_policy import policy

from tachyon.policies import base

PREFIX = "placement:traits:%s"
LIST = PREFIX % "list"
SHOW = PREFIX % "show"
UPDATE = PREFIX % "update"
DELETE = PREFIX % "delete"

RP_TRAIT_PREFIX = "placement:resource_providers:traits:%s"
RP_TRAIT_LIST = RP_TRAIT_PREFIX % "list"
RP_TRAIT_UPDATE = RP_TRAIT_PREFIX % "update"
RP_TRAIT_DELETE = RP_TRAIT_PREFIX % "delete"

rules = [
    policy.DocumentedRuleDefault(
        name=LIST,
        check_str=base.ADMIN_OR_SERVICE,
        description="List traits.",
        operations=[
            {
                "method": "GET",
                "path": "/traits",
            }
        ],
        scope_types=["project"],
    ),
    policy.DocumentedRuleDefault(
        name=SHOW,
        check_str=base.ADMIN_OR_SERVICE,
        description="Show trait.",
        operations=[
            {
                "method": "GET",
                "path": "/traits/{name}",
            }
        ],
        scope_types=["project"],
    ),
    policy.DocumentedRuleDefault(
        name=UPDATE,
        check_str=base.ADMIN_OR_SERVICE,
        description="Create or update trait.",
        operations=[
            {
                "method": "PUT",
                "path": "/traits/{name}",
            }
        ],
        scope_types=["project"],
    ),
    policy.DocumentedRuleDefault(
        name=DELETE,
        check_str=base.ADMIN_OR_SERVICE,
        description="Delete trait.",
        operations=[
            {
                "method": "DELETE",
                "path": "/traits/{name}",
            }
        ],
        scope_types=["project"],
    ),
    policy.DocumentedRuleDefault(
        name=RP_TRAIT_LIST,
        check_str=base.ADMIN_OR_SERVICE,
        description="List traits for a resource provider.",
        operations=[
            {
                "method": "GET",
                "path": "/resource_providers/{uuid}/traits",
            }
        ],
        scope_types=["project"],
    ),
    policy.DocumentedRuleDefault(
        name=RP_TRAIT_UPDATE,
        check_str=base.ADMIN_OR_SERVICE,
        description="Update traits for a resource provider.",
        operations=[
            {
                "method": "PUT",
                "path": "/resource_providers/{uuid}/traits",
            }
        ],
        scope_types=["project"],
    ),
    policy.DocumentedRuleDefault(
        name=RP_TRAIT_DELETE,
        check_str=base.ADMIN_OR_SERVICE,
        description="Delete traits for a resource provider.",
        operations=[
            {
                "method": "DELETE",
                "path": "/resource_providers/{uuid}/traits",
            }
        ],
        scope_types=["project"],
    ),
]


def list_rules() -> list[policy.DocumentedRuleDefault]:
    """Return trait policy rules.

    :returns: List of DocumentedRuleDefault instances
    """
    return rules
