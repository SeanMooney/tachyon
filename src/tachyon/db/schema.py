# SPDX-License-Identifier: Apache-2.0

"""Schema helpers for Neo4j.

This module defines the database schema (constraints and indexes) for Tachyon.
Schema is applied via Cypher statements rather than migrations, following
the design in design/05-operations/indexes-constraints.md.
"""

from __future__ import annotations

import random
import time
from typing import Any

from neo4j.exceptions import TransientError
from oslo_log import log

LOG = log.getLogger(__name__)

# Uniqueness constraints (also create indexes automatically)
UNIQUENESS_CONSTRAINTS: list[str] = [
    # Resource Provider
    "CREATE CONSTRAINT rp_uuid_unique IF NOT EXISTS "
    "FOR (rp:ResourceProvider) REQUIRE rp.uuid IS UNIQUE",
    "CREATE CONSTRAINT rp_name_unique IF NOT EXISTS "
    "FOR (rp:ResourceProvider) REQUIRE rp.name IS UNIQUE",
    # Consumer
    "CREATE CONSTRAINT consumer_uuid_unique IF NOT EXISTS "
    "FOR (c:Consumer) REQUIRE c.uuid IS UNIQUE",
    # Resource Class
    "CREATE CONSTRAINT rc_name_unique IF NOT EXISTS "
    "FOR (rc:ResourceClass) REQUIRE rc.name IS UNIQUE",
    # Trait
    "CREATE CONSTRAINT trait_name_unique IF NOT EXISTS "
    "FOR (t:Trait) REQUIRE t.name IS UNIQUE",
    # Aggregate
    "CREATE CONSTRAINT agg_uuid_unique IF NOT EXISTS "
    "FOR (agg:Aggregate) REQUIRE agg.uuid IS UNIQUE",
    # Project
    "CREATE CONSTRAINT project_external_id_unique IF NOT EXISTS "
    "FOR (p:Project) REQUIRE p.external_id IS UNIQUE",
    # User
    "CREATE CONSTRAINT user_external_id_unique IF NOT EXISTS "
    "FOR (u:User) REQUIRE u.external_id IS UNIQUE",
]

# Property existence constraints
# NOTE: These require Neo4j Enterprise Edition and are skipped in Community Edition.
# The application logic enforces these constraints instead.
EXISTENCE_CONSTRAINTS: list[str] = [
    # Resource Provider must have generation
    # "CREATE CONSTRAINT rp_generation_exists IF NOT EXISTS "
    # "FOR (rp:ResourceProvider) REQUIRE rp.generation IS NOT NULL",
    # Consumer must have generation
    # "CREATE CONSTRAINT consumer_generation_exists IF NOT EXISTS "
    # "FOR (c:Consumer) REQUIRE c.generation IS NOT NULL",
]

# Performance indexes (beyond those created by uniqueness constraints)
INDEXES: list[str] = [
    # Trait name index (for fast lookups)
    "CREATE INDEX trait_name_idx IF NOT EXISTS FOR (t:Trait) ON (t.name)",
    # Resource Class name index
    "CREATE INDEX rc_name_idx IF NOT EXISTS FOR (rc:ResourceClass) ON (rc.name)",
    # Consumer UUID index
    "CREATE INDEX consumer_uuid_idx IF NOT EXISTS FOR (c:Consumer) ON (c.uuid)",
    # Aggregate UUID index
    "CREATE INDEX agg_uuid_idx IF NOT EXISTS FOR (agg:Aggregate) ON (agg.uuid)",
]

# All schema statements in order
SCHEMA_STATEMENTS: list[str] = UNIQUENESS_CONSTRAINTS + EXISTENCE_CONSTRAINTS + INDEXES


def apply_schema(session: Any, max_retries: int = 3) -> None:
    """Apply all schema constraints and indexes with retry logic.

    :param session: Neo4j session to execute statements against
    :param max_retries: Maximum number of retry attempts on transient errors
    :note: Uses IF NOT EXISTS to make this idempotent.
    :raises TransientError: If schema application fails after all retries
    """
    for attempt in range(max_retries):
        try:
            LOG.debug("Applying %d schema statements", len(SCHEMA_STATEMENTS))
            for statement in SCHEMA_STATEMENTS:
                LOG.debug("Executing schema statement: %s", statement[:60])
                session.run(statement)
            LOG.info("Schema applied successfully")
            return
        except TransientError as e:
            if attempt < max_retries - 1:
                # Exponential backoff with jitter
                wait_time = (2**attempt) + random.uniform(0, 1)
                LOG.warning(
                    "Schema apply attempt %d/%d failed (transient error), "
                    "retrying in %.1fs: %s",
                    attempt + 1,
                    max_retries,
                    wait_time,
                    e,
                )
                time.sleep(wait_time)
            else:
                LOG.error("Schema apply failed after %d attempts", max_retries)
                raise
