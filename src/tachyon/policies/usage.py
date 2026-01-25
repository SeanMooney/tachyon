# SPDX-License-Identifier: Apache-2.0

"""Usage policy rules."""

from __future__ import annotations

from oslo_policy import policy

from tachyon.policies import base

PROVIDER_USAGES = "placement:resource_providers:usages"
TOTAL_USAGES = "placement:usages"

rules = [
    policy.DocumentedRuleDefault(
        name=PROVIDER_USAGES,
        check_str=base.ADMIN_OR_SERVICE,
        description="List resource provider usages.",
        operations=[
            {
                "method": "GET",
                "path": "/resource_providers/{uuid}/usages",
            }
        ],
        scope_types=["project"],
    ),
    policy.DocumentedRuleDefault(
        name=TOTAL_USAGES,
        # Admin in any project (legacy admin) can get usage of other project.
        # Project member or reader roles can see usage of their project only.
        check_str=base.ADMIN_OR_PROJECT_READER_OR_SERVICE,
        description="List total resource usages for a given project.",
        operations=[
            {
                "method": "GET",
                "path": "/usages",
            }
        ],
        scope_types=["project"],
    ),
]


def list_rules() -> list[policy.DocumentedRuleDefault]:
    """Return usage policy rules.

    :returns: List of DocumentedRuleDefault instances
    """
    return rules
