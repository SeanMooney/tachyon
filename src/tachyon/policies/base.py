# SPDX-License-Identifier: Apache-2.0

"""Base policy rules for Tachyon API.

Defines the fundamental policy rules that other policies reference.
"""

from __future__ import annotations

from oslo_policy import policy

# Rule check strings used by other policies
ADMIN = "role:admin"
SERVICE = "role:service"
ADMIN_OR_SERVICE = "role:admin or role:service"
PROJECT_READER = "role:reader and project_id:%(project_id)s"
ADMIN_OR_PROJECT_READER_OR_SERVICE = (
    "role:admin or role:reader and project_id:%(project_id)s or role:service"
)

rules = [
    policy.RuleDefault(
        name="admin_api",
        check_str=ADMIN,
        description="Default rule for admin-only APIs.",
        scope_types=["project"],
    ),
    policy.RuleDefault(
        name="service_api",
        check_str=SERVICE,
        description="Default rule for service-to-service APIs.",
        scope_types=["project"],
    ),
    policy.RuleDefault(
        name="admin_or_service_api",
        check_str=ADMIN_OR_SERVICE,
        description="Default rule for most placement APIs.",
        scope_types=["project"],
    ),
    policy.RuleDefault(
        name="project_reader_api",
        check_str=PROJECT_READER,
        description="Default rule for project level reader APIs.",
        scope_types=["project"],
    ),
    policy.RuleDefault(
        name="admin_or_project_reader_or_service_api",
        check_str=ADMIN_OR_PROJECT_READER_OR_SERVICE,
        description="Default rule for project level reader APIs.",
        scope_types=["project"],
    ),
]


def list_rules() -> list[policy.RuleDefault]:
    """Return base policy rules.

    :returns: List of RuleDefault instances
    """
    return rules
