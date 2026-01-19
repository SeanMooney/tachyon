# SPDX-License-Identifier: Apache-2.0

"""Allocations API blueprint.

Implements Placement-compatible allocation management.
"""

from __future__ import annotations

import collections
from typing import Any

import flask

from oslo_log import log

from tachyon.api import errors

LOG = log.getLogger(__name__)

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
    amounts and consumer generation.

    :param consumer_uuid: Consumer UUID
    :returns: Tuple of (response, status_code)
    """
    with _driver().session() as session:
        res = session.run(
            """
            MATCH (c:Consumer {uuid: $consumer_uuid})
            OPTIONAL MATCH (c)-[alloc:CONSUMES]->(inv)-[:OF_CLASS]->(rc:ResourceClass)
            OPTIONAL MATCH (inv)<-[:HAS_INVENTORY]-(rp:ResourceProvider)
            RETURN c, collect({rc: rc.name, used: alloc.used, rp: rp.uuid}) AS rows
            """,
            consumer_uuid=consumer_uuid,
        ).single()

        if not res:
            raise errors.NotFound("Consumer %s not found." % consumer_uuid)

        rows = res["rows"]
        allocations: dict[str, dict[str, Any]] = collections.defaultdict(dict)
        for row in rows:
            if not row["rc"] or not row["rp"]:
                continue
            allocations[row["rp"]][row["rc"]] = row["used"]

    response: dict[str, Any] = {
        "allocations": {
            rp: {"resources": resources} for rp, resources in allocations.items()
        },
        "consumer_generation": res["c"].get("generation", 0),
    }
    return flask.jsonify(response), 200


@bp.route("/allocations/<string:consumer_uuid>", methods=["PUT"])
def put_allocations(consumer_uuid: str) -> tuple[flask.Response, int]:
    """Create or update allocations for a consumer.

    Request Body:
        allocations: Dict mapping resource provider UUIDs to resource dicts.
        consumer_generation: Required. Current consumer generation (0 for new).
        project_id: Optional. Project ID for the consumer.
        user_id: Optional. User ID for the consumer.

    :param consumer_uuid: Consumer UUID
    :returns: Tuple of (response, status_code)
    """
    body = flask.request.get_json(force=True, silent=True) or {}
    allocations = body.get("allocations") or {}
    consumer_generation = body.get("consumer_generation")
    project_id = body.get("project_id")
    user_id = body.get("user_id")

    if consumer_generation is None:
        raise errors.BadRequest("'consumer_generation' is a required field.")

    with _driver().session() as session:
        tx = session.begin_transaction()
        try:
            # Create or get consumer
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
                    "Consumer %s generation mismatch: "
                    "expected %s, got %s."
                    % (
                        consumer_uuid,
                        consumer_generation,
                        consumer.get("generation", 0),
                    )
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

            # Increment consumer generation
            updated = tx.run(
                """
                MATCH (c:Consumer {uuid: $uuid})
                SET c.generation = c.generation + 1,
                    c.updated_at = datetime()
                RETURN c.generation AS generation
                """,
                uuid=consumer_uuid,
            ).single()

            tx.commit()
        except (ValueError, TypeError, RuntimeError):
            tx.rollback()
            raise

    return flask.jsonify({"consumer_generation": updated["generation"]}), 200


@bp.route("/allocations/<string:consumer_uuid>", methods=["DELETE"])
def delete_allocations(consumer_uuid: str) -> flask.Response:
    """Delete all allocations for a consumer.

    :param consumer_uuid: Consumer UUID
    :returns: Response with status 204
    """
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


@bp.route("/resource_providers/<string:rp_uuid>/allocations", methods=["GET"])
def get_provider_allocations(rp_uuid: str) -> tuple[flask.Response, int]:
    """Get all allocations against a resource provider.

    :param rp_uuid: Resource provider UUID
    :returns: Tuple of (response, status_code)
    """
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
