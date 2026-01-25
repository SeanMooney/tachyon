# SPDX-License-Identifier: Apache-2.0

"""Policy definitions for Tachyon API.

This package contains policy rules for all Tachyon API endpoints,
following the Placement API pattern for compatibility.
"""

from __future__ import annotations

import itertools

from oslo_policy import policy

from tachyon.policies import aggregate
from tachyon.policies import allocation
from tachyon.policies import allocation_candidate
from tachyon.policies import base
from tachyon.policies import inventory
from tachyon.policies import resource_class
from tachyon.policies import resource_provider
from tachyon.policies import trait
from tachyon.policies import usage


def list_rules() -> list[policy.RuleDefault]:
    """Return a list of all policy rules.

    :returns: List of RuleDefault instances
    """
    rules = itertools.chain(
        base.list_rules(),
        resource_provider.list_rules(),
        resource_class.list_rules(),
        inventory.list_rules(),
        aggregate.list_rules(),
        usage.list_rules(),
        trait.list_rules(),
        allocation.list_rules(),
        allocation_candidate.list_rules(),
    )
    return list(rules)
