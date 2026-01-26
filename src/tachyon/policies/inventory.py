# SPDX-License-Identifier: Apache-2.0

"""Inventory policy rules."""

from __future__ import annotations

from oslo_policy import policy

from tachyon.policies import base

PREFIX = "placement:resource_providers:inventories:%s"
LIST = PREFIX % "list"
CREATE = PREFIX % "create"
SHOW = PREFIX % "show"
UPDATE = PREFIX % "update"
DELETE = PREFIX % "delete"
DELETE_ALL = PREFIX % "delete_all"

rules = [
    policy.DocumentedRuleDefault(
        name=LIST,
        check_str=base.ADMIN_OR_SERVICE,
        description="List inventories for a resource provider.",
        operations=[
            {
                "method": "GET",
                "path": "/resource_providers/{uuid}/inventories",
            }
        ],
        scope_types=["project"],
    ),
    policy.DocumentedRuleDefault(
        name=CREATE,
        check_str=base.ADMIN_OR_SERVICE,
        description="Create inventory for a resource provider.",
        operations=[
            {
                "method": "POST",
                "path": "/resource_providers/{uuid}/inventories",
            }
        ],
        scope_types=["project"],
    ),
    policy.DocumentedRuleDefault(
        name=SHOW,
        check_str=base.ADMIN_OR_SERVICE,
        description="Show inventory for a resource provider.",
        operations=[
            {
                "method": "GET",
                "path": "/resource_providers/{uuid}/inventories/{resource_class}",
            }
        ],
        scope_types=["project"],
    ),
    policy.DocumentedRuleDefault(
        name=UPDATE,
        check_str=base.ADMIN_OR_SERVICE,
        description="Update inventory for a resource provider.",
        operations=[
            {
                "method": "PUT",
                "path": "/resource_providers/{uuid}/inventories/{resource_class}",
            },
            {
                "method": "PUT",
                "path": "/resource_providers/{uuid}/inventories",
            },
        ],
        scope_types=["project"],
    ),
    policy.DocumentedRuleDefault(
        name=DELETE,
        check_str=base.ADMIN_OR_SERVICE,
        description="Delete inventory for a resource provider.",
        operations=[
            {
                "method": "DELETE",
                "path": "/resource_providers/{uuid}/inventories/{resource_class}",
            }
        ],
        scope_types=["project"],
    ),
    policy.DocumentedRuleDefault(
        name=DELETE_ALL,
        check_str=base.ADMIN_OR_SERVICE,
        description="Delete all inventories for a resource provider.",
        operations=[
            {
                "method": "DELETE",
                "path": "/resource_providers/{uuid}/inventories",
            }
        ],
        scope_types=["project"],
    ),
]


def list_rules() -> list[policy.DocumentedRuleDefault]:
    """Return inventory policy rules.

    :returns: List of DocumentedRuleDefault instances
    """
    return rules
