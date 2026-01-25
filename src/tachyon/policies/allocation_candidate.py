# SPDX-License-Identifier: Apache-2.0

"""Allocation candidate policy rules."""

from __future__ import annotations

from oslo_policy import policy

from tachyon.policies import base

LIST = "placement:allocation_candidates:list"

rules = [
    policy.DocumentedRuleDefault(
        name=LIST,
        check_str=base.ADMIN_OR_SERVICE,
        description="List allocation candidates.",
        operations=[
            {
                "method": "GET",
                "path": "/allocation_candidates",
            }
        ],
        scope_types=["project"],
    ),
]


def list_rules() -> list[policy.DocumentedRuleDefault]:
    """Return allocation candidate policy rules.

    :returns: List of DocumentedRuleDefault instances
    """
    return rules
