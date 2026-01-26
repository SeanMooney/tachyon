# SPDX-License-Identifier: Apache-2.0

"""Allocations API blueprint.

Implements Placement-compatible allocation management.
"""

from __future__ import annotations

import collections
import re
from typing import Any

import flask

from oslo_log import log

from tachyon.api import errors
from tachyon.api import microversion
from tachyon.policies import allocation as alloc_policies

# Pattern for valid consumer_type (uppercase alphanumeric and underscore)
CONSUMER_TYPE_PATTERN = re.compile(r"^[A-Z0-9_]+$")

LOG = log.getLogger(__name__)


def _mv() -> microversion.Microversion:
    """Return the parsed microversion from the request context.

    :returns: Parsed Microversion object
    """
    mv: microversion.Microversion | None = getattr(flask.g, "microversion", None)
    if mv is None:
        mv = microversion.Microversion(1, 0)
    return mv

bp = flask.Blueprint("allocations", __name__)


def _driver() -> Any:
    """Get the Neo4j driver from the Flask app.

    :returns: Neo4j driver instance
    """
    from tachyon.api import app

    return app.get_driver()


@bp.route("/allocations/<string:consumer_uuid>", methods=["GET"])
def get_allocations(consumer_uuid: str) -> tuple[flask.Response, int]:
    """Get allocations for a consumer.

    Returns allocations grouped by resource provider with resource class
    amounts. Response format varies by microversion:
    - 1.12+: includes project_id, user_id, and per-provider generation
    - 1.28+: includes consumer_generation at top level

    :param consumer_uuid: Consumer UUID
    :returns: Tuple of (response, status_code)
    """
    flask.g.context.can(alloc_policies.LIST)
    mv = _mv()

    with _driver().session() as session:
        res = session.run(
            """
            MATCH (c:Consumer {uuid: $consumer_uuid})
            OPTIONAL MATCH (c)-[alloc:CONSUMES]->(inv)-[:OF_CLASS]->(rc:ResourceClass)
            OPTIONAL MATCH (inv)<-[:HAS_INVENTORY]-(rp:ResourceProvider)
            OPTIONAL MATCH (c)-[:OWNED_BY]->(p:Project)
            OPTIONAL MATCH (c)-[:CREATED_BY]->(u:User)
            RETURN c, collect({rc: rc.name, used: alloc.used, rp_uuid: rp.uuid,
                              rp_gen: rp.generation}) AS rows,
                   p.external_id AS project_id, u.external_id AS user_id,
                   c.consumer_type AS consumer_type
            """,
            consumer_uuid=consumer_uuid,
        ).single()

        if not res:
            # Consumer doesn't exist - return empty allocations per API spec
            return flask.jsonify({"allocations": {}}), 200

        rows = res["rows"]
        # Build allocations dict with per-provider generation
        allocations: dict[str, dict[str, Any]] = collections.defaultdict(
            lambda: {"resources": {}}
        )
        for row in rows:
            if not row["rc"] or not row["rp_uuid"]:
                continue
            rp_uuid = row["rp_uuid"]
            allocations[rp_uuid]["resources"][row["rc"]] = row["used"]
            # Include resource provider generation in each allocation
            allocations[rp_uuid]["generation"] = row.get("rp_gen", 0)

    # Build response
    response: dict[str, Any] = {"allocations": dict(allocations)}

    # Only include extra fields when allocations exist
    if allocations:
        # project_id and user_id at 1.12+
        if mv.is_at_least(12):
            if res["project_id"]:
                response["project_id"] = res["project_id"]
            if res["user_id"]:
                response["user_id"] = res["user_id"]
        # consumer_generation at 1.28+
        if mv.is_at_least(28):
            response["consumer_generation"] = res["c"].get("generation", 0)
        # consumer_type at 1.38+
        if mv.is_at_least(38):
            consumer_type = res.get("consumer_type")
            if consumer_type:
                response["consumer_type"] = consumer_type

    return flask.jsonify(response), 200


@bp.route("/allocations/<string:consumer_uuid>", methods=["PUT"])
def put_allocations(consumer_uuid: str) -> tuple[flask.Response, int]:
    """Create or update allocations for a consumer.

    Request Body:
        allocations: Dict mapping resource provider UUIDs to resource dicts.
        consumer_generation: Required at 1.28+. Current consumer generation.
        project_id: Required at 1.8+. Project ID for the consumer.
        user_id: Required at 1.8+. User ID for the consumer.

    :param consumer_uuid: Consumer UUID
    :returns: Tuple of (response, status_code)
    """
    flask.g.context.can(alloc_policies.UPDATE)
    mv = _mv()
    body = flask.request.get_json(force=True, silent=True) or {}
    allocations = body.get("allocations") or {}
    project_id = body.get("project_id")
    user_id = body.get("user_id")

    # Microversion 1.8+ requires project_id and user_id
    if mv.is_at_least(8):
        if project_id is None:
            raise errors.BadRequest("'project_id' is a required field.")
        if user_id is None:
            raise errors.BadRequest("'user_id' is a required field.")

    # Microversion 1.28+ requires consumer_generation
    requires_consumer_generation = mv.is_at_least(28)
    if requires_consumer_generation:
        if "consumer_generation" not in body:
            raise errors.BadRequest("'consumer_generation' is a required field.")
    consumer_generation = body.get("consumer_generation")  # Can be None or int

    # Microversion 1.38+ requires consumer_type
    requires_consumer_type = mv.is_at_least(38)
    consumer_type = body.get("consumer_type")
    if requires_consumer_type:
        if consumer_type is None:
            raise errors.BadRequest("'consumer_type' is a required property")
        if not CONSUMER_TYPE_PATTERN.match(consumer_type):
            raise errors.BadRequest(
                "'%s' does not match '^[A-Z0-9_]+$'" % consumer_type
            )

    with _driver().session() as session:
        tx = session.begin_transaction()
        try:
            # Consumer generation handling depends on microversion
            if requires_consumer_generation:
                # 1.28+: Handle consumer_generation: null vs integer differently
                # - null means "expect consumer doesn't exist, create new"
                # - integer means "expect consumer exists at this generation"
                if consumer_generation is None:
                    # Check if consumer already exists
                    existing = tx.run(
                        "MATCH (c:Consumer {uuid: $uuid}) RETURN c.generation AS gen",
                        uuid=consumer_uuid,
                    ).single()

                    if existing is not None:
                        # Consumer exists but caller expected it didn't
                        raise errors.ConsumerGenerationConflict(
                            "consumer generation conflict - "
                            "expected null but got %s"
                            % (existing["gen"],)
                        )

                    # Create new consumer with generation 0
                    tx.run(
                        """
                        CREATE (c:Consumer {
                            uuid: $uuid,
                            generation: 0,
                            consumer_type: $consumer_type,
                            created_at: datetime(),
                            updated_at: datetime()
                        })
                        """,
                        uuid=consumer_uuid,
                        consumer_type=consumer_type,
                    )
                else:
                    # consumer_generation is an integer - get or create consumer
                    # and verify generation matches
                    consumer = tx.run(
                        """
                        MERGE (c:Consumer {uuid: $uuid})
                        ON CREATE SET c.generation = 0,
                                      c.created_at = datetime(),
                                      c.updated_at = datetime()
                        RETURN c
                        """,
                        uuid=consumer_uuid,
                    ).single()["c"]

                    if consumer.get("generation", 0) != consumer_generation:
                        raise errors.ConsumerGenerationConflict(
                            "consumer generation conflict - "
                            "expected %s but got %s"
                            % (
                                consumer_generation,
                                consumer.get("generation", 0),
                            )
                        )
                    # Update consumer_type if provided
                    if consumer_type:
                        tx.run(
                            """
                            MATCH (c:Consumer {uuid: $uuid})
                            SET c.consumer_type = $consumer_type
                            """,
                            uuid=consumer_uuid,
                            consumer_type=consumer_type,
                        )
            else:
                # Before 1.28: Simply create or get consumer without generation check
                tx.run(
                    """
                    MERGE (c:Consumer {uuid: $uuid})
                    ON CREATE SET c.generation = 0,
                                  c.created_at = datetime(),
                                  c.updated_at = datetime()
                    """,
                    uuid=consumer_uuid,
                )
                # Store consumer_type if provided (even before 1.38)
                if consumer_type:
                    tx.run(
                        """
                        MATCH (c:Consumer {uuid: $uuid})
                        SET c.consumer_type = $consumer_type
                        """,
                        uuid=consumer_uuid,
                        consumer_type=consumer_type,
                    )

            # Handle project/user associations
            if project_id:
                tx.run(
                    """
                    MERGE (p:Project {external_id: $project_id})
                    ON CREATE SET p.created_at = datetime()
                    WITH p
                    MATCH (c:Consumer {uuid: $uuid})
                    MERGE (c)-[:OWNED_BY]->(p)
                    """,
                    uuid=consumer_uuid,
                    project_id=project_id,
                )

            if user_id:
                tx.run(
                    """
                    MERGE (u:User {external_id: $user_id})
                    ON CREATE SET u.created_at = datetime()
                    WITH u
                    MATCH (c:Consumer {uuid: $uuid})
                    MERGE (c)-[:CREATED_BY]->(u)
                    """,
                    uuid=consumer_uuid,
                    user_id=user_id,
                )

            # Delete existing allocations
            tx.run(
                """
                MATCH (c:Consumer {uuid: $uuid})-[alloc:CONSUMES]->()
                DELETE alloc
                """,
                uuid=consumer_uuid,
            )

            # Create new allocations
            for rp_uuid, rp_allocs in allocations.items():
                resources = rp_allocs.get("resources", rp_allocs)
                for rc_name, amount in resources.items():
                    # Verify inventory exists
                    inv_check = tx.run(
                        """
                        MATCH (rp:ResourceProvider {uuid: $rp_uuid})
                              -[:HAS_INVENTORY]->(inv)
                              -[:OF_CLASS]->(rc:ResourceClass {name: $rc})
                        RETURN inv
                        """,
                        rp_uuid=rp_uuid,
                        rc=rc_name,
                    ).single()

                    if not inv_check:
                        raise errors.NotFound(
                            "Inventory for %s not found on "
                            "resource provider %s." % (rc_name, rp_uuid)
                        )

                    tx.run(
                        """
                        MATCH (rp:ResourceProvider {uuid: $rp_uuid})
                              -[:HAS_INVENTORY]->(inv)
                              -[:OF_CLASS]->(rc:ResourceClass {name: $rc})
                        MATCH (c:Consumer {uuid: $consumer_uuid})
                        MERGE (c)-[alloc:CONSUMES]->(inv)
                        SET alloc.used = $amount,
                            alloc.updated_at = datetime()
                        """,
                        rp_uuid=rp_uuid,
                        rc=rc_name,
                        consumer_uuid=consumer_uuid,
                        amount=amount,
                    )

            # Check if consumer has any allocations after the update
            # If not, delete the consumer (matching Placement behavior)
            # This is critical for live migration where allocations may be cleared
            has_allocations = bool(allocations)
            if not has_allocations:
                # Consumer has no allocations - delete it per Placement behavior
                _delete_consumer_if_no_allocations(tx, consumer_uuid)
            else:
                # Increment consumer generation only if consumer still exists
                tx.run(
                    """
                    MATCH (c:Consumer {uuid: $uuid})
                    SET c.generation = c.generation + 1,
                        c.updated_at = datetime()
                    """,
                    uuid=consumer_uuid,
                )

            tx.commit()
        except (ValueError, TypeError, RuntimeError):
            tx.rollback()
            raise

    # Placement API spec: PUT /allocations returns 204 No Content on success
    return flask.Response(status=204)


@bp.route("/allocations/<string:consumer_uuid>", methods=["DELETE"])
def delete_allocations(consumer_uuid: str) -> flask.Response:
    """Delete all allocations for a consumer.

    :param consumer_uuid: Consumer UUID
    :returns: Response with status 204
    """
    flask.g.context.can(alloc_policies.DELETE)
    with _driver().session() as session:
        # Check if consumer exists
        consumer = session.run(
            "MATCH (c:Consumer {uuid: $uuid}) RETURN c",
            uuid=consumer_uuid,
        ).single()

        if not consumer:
            raise errors.NotFound("Consumer %s not found." % consumer_uuid)

        session.run(
            """
            MATCH (c:Consumer {uuid: $uuid})-[alloc:CONSUMES]->()
            DELETE alloc
            """,
            uuid=consumer_uuid,
        )

    return flask.Response(status=204)


@bp.route("/allocations", methods=["POST"])
def post_allocations() -> flask.Response:
    """Set allocations for multiple consumers atomically.

    Available at microversion 1.13+. This endpoint allows setting or clearing
    allocations for multiple consumers in a single atomic transaction. This is
    critical for operations like live migration where allocations need to move
    from one host to another atomically.

    Request Body:
        {
            "<consumer_uuid>": {
                "allocations": {
                    "<rp_uuid>": {
                        "resources": {"<resource_class>": <int>, ...}
                    },
                    ...
                },
                "project_id": "<project_id>",
                "user_id": "<user_id>",
                "consumer_generation": <int or null>,  # Required at 1.28+
                "consumer_type": "<type>"  # Required at 1.38+
            },
            ...
        }

    :returns: Response with status 204 on success
    """
    flask.g.context.can(alloc_policies.MANAGE)
    mv = _mv()

    # POST /allocations requires microversion 1.13+
    if not mv.is_at_least(13):
        raise errors.NotFound("The resource could not be found.")

    body = flask.request.get_json(force=True, silent=True)
    if not body or not isinstance(body, dict):
        raise errors.BadRequest("Malformed JSON in request body")

    # Validate each consumer's data based on microversion
    requires_consumer_generation = mv.is_at_least(28)
    requires_consumer_type = mv.is_at_least(38)

    for consumer_uuid, consumer_data in body.items():
        if not isinstance(consumer_data, dict):
            raise errors.BadRequest(
                "Allocation data for consumer %s must be a dict" % consumer_uuid
            )

        # Validate required fields based on microversion
        if "project_id" not in consumer_data:
            raise errors.BadRequest(
                "'project_id' is a required property for consumer %s" % consumer_uuid
            )
        if "user_id" not in consumer_data:
            raise errors.BadRequest(
                "'user_id' is a required property for consumer %s" % consumer_uuid
            )

        if requires_consumer_generation:
            if "consumer_generation" not in consumer_data:
                raise errors.BadRequest(
                    "'consumer_generation' is a required property for consumer %s"
                    % consumer_uuid
                )

        if requires_consumer_type:
            consumer_type = consumer_data.get("consumer_type")
            if consumer_type is None:
                raise errors.BadRequest(
                    "'consumer_type' is a required property for consumer %s"
                    % consumer_uuid
                )
            if not CONSUMER_TYPE_PATTERN.match(consumer_type):
                raise errors.BadRequest(
                    "'%s' does not match '^[A-Z0-9_]+$'" % consumer_type
                )

    # Track newly created consumers so we can delete them on error
    new_consumers: list[str] = []

    with _driver().session() as session:
        tx = session.begin_transaction()
        try:
            # Phase 1: Ensure all consumers exist and validate generations
            for consumer_uuid, consumer_data in body.items():
                project_id = consumer_data.get("project_id")
                user_id = consumer_data.get("user_id")
                consumer_generation = consumer_data.get("consumer_generation")
                consumer_type = consumer_data.get("consumer_type")

                if requires_consumer_generation:
                    if consumer_generation is None:
                        # consumer_generation: null means expect consumer doesn't exist
                        existing = tx.run(
                            "MATCH (c:Consumer {uuid: $uuid}) RETURN c.generation AS gen",
                            uuid=consumer_uuid,
                        ).single()

                        if existing is not None:
                            # Rollback and clean up any new consumers we created
                            tx.rollback()
                            _cleanup_consumers(session, new_consumers)
                            raise errors.ConsumerGenerationConflict(
                                "consumer generation conflict - "
                                "expected null but got %s for consumer %s"
                                % (existing["gen"], consumer_uuid)
                            )

                        # Create new consumer
                        tx.run(
                            """
                            CREATE (c:Consumer {
                                uuid: $uuid,
                                generation: 0,
                                consumer_type: $consumer_type,
                                created_at: datetime(),
                                updated_at: datetime()
                            })
                            """,
                            uuid=consumer_uuid,
                            consumer_type=consumer_type,
                        )
                        new_consumers.append(consumer_uuid)
                    else:
                        # consumer_generation is an integer - verify or create
                        result = tx.run(
                            """
                            MERGE (c:Consumer {uuid: $uuid})
                            ON CREATE SET c.generation = 0,
                                          c.created_at = datetime(),
                                          c.updated_at = datetime()
                            RETURN c, c.generation AS gen,
                                   EXISTS { MATCH (c2:Consumer {uuid: $uuid})
                                           WHERE c2.created_at < datetime() - duration('PT1S') }
                                   AS existed
                            """,
                            uuid=consumer_uuid,
                        ).single()

                        consumer = result["c"]
                        current_gen = consumer.get("generation", 0)

                        if current_gen != consumer_generation:
                            tx.rollback()
                            _cleanup_consumers(session, new_consumers)
                            raise errors.ConsumerGenerationConflict(
                                "consumer generation conflict - "
                                "expected %s but got %s for consumer %s"
                                % (consumer_generation, current_gen, consumer_uuid)
                            )

                        # Update consumer_type if provided
                        if consumer_type:
                            tx.run(
                                """
                                MATCH (c:Consumer {uuid: $uuid})
                                SET c.consumer_type = $consumer_type
                                """,
                                uuid=consumer_uuid,
                                consumer_type=consumer_type,
                            )
                else:
                    # Before 1.28: Simply create or get consumer
                    tx.run(
                        """
                        MERGE (c:Consumer {uuid: $uuid})
                        ON CREATE SET c.generation = 0,
                                      c.created_at = datetime(),
                                      c.updated_at = datetime()
                        """,
                        uuid=consumer_uuid,
                    )
                    if consumer_type:
                        tx.run(
                            """
                            MATCH (c:Consumer {uuid: $uuid})
                            SET c.consumer_type = $consumer_type
                            """,
                            uuid=consumer_uuid,
                            consumer_type=consumer_type,
                        )

                # Handle project/user associations
                if project_id:
                    tx.run(
                        """
                        MERGE (p:Project {external_id: $project_id})
                        ON CREATE SET p.created_at = datetime()
                        WITH p
                        MATCH (c:Consumer {uuid: $uuid})
                        MERGE (c)-[:OWNED_BY]->(p)
                        """,
                        uuid=consumer_uuid,
                        project_id=project_id,
                    )

                if user_id:
                    tx.run(
                        """
                        MERGE (u:User {external_id: $user_id})
                        ON CREATE SET u.created_at = datetime()
                        WITH u
                        MATCH (c:Consumer {uuid: $uuid})
                        MERGE (c)-[:CREATED_BY]->(u)
                        """,
                        uuid=consumer_uuid,
                        user_id=user_id,
                    )

            # Phase 2: Delete existing allocations and create new ones
            for consumer_uuid, consumer_data in body.items():
                allocations = consumer_data.get("allocations") or {}

                # Delete existing allocations for this consumer
                tx.run(
                    """
                    MATCH (c:Consumer {uuid: $uuid})-[alloc:CONSUMES]->()
                    DELETE alloc
                    """,
                    uuid=consumer_uuid,
                )

                # Create new allocations
                for rp_uuid, rp_allocs in allocations.items():
                    resources = rp_allocs.get("resources", rp_allocs)
                    for rc_name, amount in resources.items():
                        # Verify inventory exists
                        inv_check = tx.run(
                            """
                            MATCH (rp:ResourceProvider {uuid: $rp_uuid})
                                  -[:HAS_INVENTORY]->(inv)
                                  -[:OF_CLASS]->(rc:ResourceClass {name: $rc})
                            RETURN inv
                            """,
                            rp_uuid=rp_uuid,
                            rc=rc_name,
                        ).single()

                        if not inv_check:
                            tx.rollback()
                            _cleanup_consumers(session, new_consumers)
                            raise errors.BadRequest(
                                "Allocation for resource provider '%s' "
                                "that does not exist." % rp_uuid
                            )

                        tx.run(
                            """
                            MATCH (rp:ResourceProvider {uuid: $rp_uuid})
                                  -[:HAS_INVENTORY]->(inv)
                                  -[:OF_CLASS]->(rc:ResourceClass {name: $rc})
                            MATCH (c:Consumer {uuid: $consumer_uuid})
                            MERGE (c)-[alloc:CONSUMES]->(inv)
                            SET alloc.used = $amount,
                                alloc.updated_at = datetime()
                            """,
                            rp_uuid=rp_uuid,
                            rc=rc_name,
                            consumer_uuid=consumer_uuid,
                            amount=amount,
                        )

                # Check if consumer has any allocations after the update
                # If not, delete the consumer (matching Placement behavior)
                # This is critical for live migration where allocations may be cleared
                has_allocations = bool(allocations)
                if not has_allocations:
                    # Consumer has no allocations - delete it per Placement behavior
                    _delete_consumer_if_no_allocations(tx, consumer_uuid)
                else:
                    # Increment consumer generation only if consumer still exists
                    tx.run(
                        """
                        MATCH (c:Consumer {uuid: $uuid})
                        SET c.generation = c.generation + 1,
                            c.updated_at = datetime()
                        """,
                        uuid=consumer_uuid,
                    )

            tx.commit()
            LOG.debug("Successfully wrote allocations for %d consumers", len(body))

        except errors.ConsumerGenerationConflict:
            # Already handled above with cleanup
            raise
        except errors.BadRequest:
            # Already handled above with cleanup
            raise
        except Exception:
            tx.rollback()
            _cleanup_consumers(session, new_consumers)
            raise

    return flask.Response(status=204)


def _cleanup_consumers(session: Any, consumer_uuids: list[str]) -> None:
    """Delete consumers that were auto-created during a failed allocation.

    :param session: Neo4j session
    :param consumer_uuids: List of consumer UUIDs to delete
    """
    for consumer_uuid in consumer_uuids:
        try:
            session.run(
                """
                MATCH (c:Consumer {uuid: $uuid})
                WHERE NOT EXISTS { MATCH (c)-[:CONSUMES]->() }
                DETACH DELETE c
                """,
                uuid=consumer_uuid,
            )
            LOG.debug(
                "Deleted auto-created consumer %s after failed allocation",
                consumer_uuid,
            )
        except Exception as err:
            LOG.warning(
                "Failed to delete auto-created consumer %s: %s",
                consumer_uuid,
                err,
            )


def _delete_consumer_if_no_allocations(tx: Any, consumer_uuid: str) -> bool:
    """Delete a consumer if it has no allocations.

    This matches Placement's behavior where consumers without allocations
    are automatically cleaned up. This is critical for live migration where
    a consumer's allocations may be temporarily cleared.

    :param tx: Neo4j transaction
    :param consumer_uuid: Consumer UUID to check and potentially delete
    :returns: True if consumer was deleted, False otherwise
    """
    # Check if consumer has any allocations
    result = tx.run(
        """
        MATCH (c:Consumer {uuid: $uuid})
        OPTIONAL MATCH (c)-[alloc:CONSUMES]->()
        WITH c, count(alloc) AS alloc_count
        WHERE alloc_count = 0
        DETACH DELETE c
        RETURN true AS deleted
        """,
        uuid=consumer_uuid,
    ).single()

    if result and result.get("deleted"):
        LOG.debug(
            "Deleted consumer %s because it has no allocations",
            consumer_uuid,
        )
        return True
    return False


@bp.route("/resource_providers/<string:rp_uuid>/allocations", methods=["GET"])
def get_provider_allocations(rp_uuid: str) -> tuple[flask.Response, int]:
    """Get all allocations against a resource provider.

    :param rp_uuid: Resource provider UUID
    :returns: Tuple of (response, status_code)
    """
    flask.g.context.can(alloc_policies.LIST)
    with _driver().session() as session:
        # Check provider exists
        provider = session.run(
            "MATCH (rp:ResourceProvider {uuid: $uuid}) RETURN rp",
            uuid=rp_uuid,
        ).single()

        if not provider:
            raise errors.NotFound("Resource provider %s not found." % rp_uuid)

        res = session.run(
            """
            MATCH (rp:ResourceProvider {uuid: $uuid})
                  -[:HAS_INVENTORY]->(inv)
                  -[:OF_CLASS]->(rc:ResourceClass)
            OPTIONAL MATCH (c:Consumer)-[alloc:CONSUMES]->(inv)
            RETURN c.uuid AS consumer_uuid,
                   c.generation AS consumer_generation,
                   rc.name AS resource_class,
                   alloc.used AS used
            """,
            uuid=rp_uuid,
        )

        allocations: dict[str, dict[str, Any]] = collections.defaultdict(
            lambda: {"resources": {}}
        )
        for row in res:
            if row["consumer_uuid"] and row["resource_class"]:
                allocations[row["consumer_uuid"]]["resources"][
                    row["resource_class"]
                ] = row["used"]
                allocations[row["consumer_uuid"]]["consumer_generation"] = row[
                    "consumer_generation"
                ]

    return flask.jsonify(
        {
            "allocations": dict(allocations),
            "resource_provider_generation": provider["rp"].get("generation", 0),
        }
    ), 200
