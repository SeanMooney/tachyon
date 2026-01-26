# SPDX-License-Identifier: Apache-2.0

"""Reshaper API blueprint.

Implements Placement-compatible reshaper for atomic inventory/allocation migration.
Available at microversion 1.30+.
"""

from __future__ import annotations

from typing import Any

import flask

from oslo_log import log

from tachyon.api import errors
from tachyon.api import microversion
from tachyon.policies import allocation as alloc_policies

LOG = log.getLogger(__name__)

bp = flask.Blueprint("reshaper", __name__, url_prefix="/reshaper")


def _driver() -> Any:
    """Get the Neo4j driver from the Flask app.

    :returns: Neo4j driver instance
    """
    from tachyon.api import app

    return app.get_driver()


def _mv() -> microversion.Microversion:
    """Return the parsed microversion from the request context.

    :returns: Microversion instance
    """
    mv: microversion.Microversion | None = getattr(flask.g, "microversion", None)
    if mv is None:
        return microversion.Microversion(1, 0)
    return mv


@bp.route("", methods=["POST"])
def reshape() -> flask.Response:
    """Atomically reshape resource providers with new inventories and allocations.

    This endpoint allows atomically updating inventories on multiple providers
    and moving allocations between providers. This is used by nova-compute
    during virt driver resource topology changes (e.g., adding/removing
    SRIOV PFs).

    Available at microversion 1.30+.

    Request Body:
        {
            "inventories": {
                "<rp_uuid>": {
                    "resource_provider_generation": <int>,
                    "inventories": {
                        "<resource_class>": {
                            "total": <int>,
                            "reserved": <int>,  # optional
                            "min_unit": <int>,  # optional
                            "max_unit": <int>,  # optional
                            "step_size": <int>,  # optional
                            "allocation_ratio": <float>  # optional
                        },
                        ...
                    }
                },
                ...
            },
            "allocations": {
                "<consumer_uuid>": {
                    "allocations": {
                        "<rp_uuid>": {
                            "resources": {"<resource_class>": <int>, ...}
                        },
                        ...
                    },
                    "project_id": "<project_id>",
                    "user_id": "<user_id>",
                    "consumer_generation": <int or null>
                },
                ...
            }
        }

    :returns: Response with status 204 on success
    """
    mv = _mv()
    flask.g.context.can(alloc_policies.UPDATE)

    # This endpoint requires microversion 1.30+
    if not mv.is_at_least(30):
        raise errors.NotFound("The resource could not be found.")

    body = flask.request.get_json(force=True, silent=True)
    if not body or not isinstance(body, dict):
        raise errors.BadRequest("Malformed JSON in request body")

    inventories_data = body.get("inventories", {})
    allocations_data = body.get("allocations", {})

    # Validate required fields
    if not inventories_data:
        raise errors.BadRequest("'inventories' is a required field")

    with _driver().session() as session:
        tx = session.begin_transaction()
        try:
            # Phase 1: Update inventories for all providers
            for rp_uuid, rp_inventory_data in inventories_data.items():
                if not isinstance(rp_inventory_data, dict):
                    raise errors.BadRequest(
                        "Inventory data for provider %s must be a dict" % rp_uuid
                    )

                # Validate resource provider generation
                if "resource_provider_generation" not in rp_inventory_data:
                    raise errors.BadRequest(
                        "'resource_provider_generation' is required for provider %s"
                        % rp_uuid
                    )
                expected_generation = rp_inventory_data["resource_provider_generation"]

                # Check provider exists and get its generation
                provider = tx.run(
                    "MATCH (rp:ResourceProvider {uuid: $uuid}) RETURN rp",
                    uuid=rp_uuid,
                ).single()

                if not provider:
                    raise errors.NotFound(
                        "No resource provider with uuid %s found" % rp_uuid
                    )

                current_generation = provider["rp"].get("generation", 0)
                if current_generation != expected_generation:
                    raise errors.ResourceProviderGenerationConflict(uuid=rp_uuid)

                # Process inventory updates
                inventories = rp_inventory_data.get("inventories", {})

                # Delete old inventories for this provider
                tx.run(
                    """
                    MATCH (rp:ResourceProvider {uuid: $uuid})-[:HAS_INVENTORY]->(inv)
                    DETACH DELETE inv
                    """,
                    uuid=rp_uuid,
                )

                # Create new inventories
                for rc_name, inv_values in inventories.items():
                    if not isinstance(inv_values, dict):
                        raise errors.BadRequest(
                            "Inventory for %s on provider %s must be a dict"
                            % (rc_name, rp_uuid)
                        )

                    # Validate required 'total' field
                    if "total" not in inv_values:
                        raise errors.BadRequest(
                            "'total' is required for inventory %s" % rc_name
                        )

                    total = inv_values["total"]
                    reserved = inv_values.get("reserved", 0)
                    min_unit = inv_values.get("min_unit", 1)
                    max_unit = inv_values.get("max_unit", 2147483647)
                    step_size = inv_values.get("step_size", 1)
                    allocation_ratio = inv_values.get("allocation_ratio", 1.0)

                    # Ensure resource class exists
                    tx.run(
                        """
                        MERGE (rc:ResourceClass {name: $name})
                        ON CREATE SET rc.created_at = datetime()
                        """,
                        name=rc_name,
                    )

                    # Create inventory
                    tx.run(
                        """
                        MATCH (rp:ResourceProvider {uuid: $rp_uuid})
                        MATCH (rc:ResourceClass {name: $rc_name})
                        CREATE (rp)-[:HAS_INVENTORY]->(inv:Inventory)-[:OF_CLASS]->(rc)
                        SET inv.total = $total,
                            inv.reserved = $reserved,
                            inv.min_unit = $min_unit,
                            inv.max_unit = $max_unit,
                            inv.step_size = $step_size,
                            inv.allocation_ratio = $allocation_ratio,
                            inv.created_at = datetime(),
                            inv.updated_at = datetime()
                        """,
                        rp_uuid=rp_uuid,
                        rc_name=rc_name,
                        total=total,
                        reserved=reserved,
                        min_unit=min_unit,
                        max_unit=max_unit,
                        step_size=step_size,
                        allocation_ratio=allocation_ratio,
                    )

                # Increment provider generation
                tx.run(
                    """
                    MATCH (rp:ResourceProvider {uuid: $uuid})
                    SET rp.generation = rp.generation + 1,
                        rp.updated_at = datetime()
                    """,
                    uuid=rp_uuid,
                )

            # Phase 2: Update allocations for all consumers
            for consumer_uuid, consumer_data in allocations_data.items():
                if not isinstance(consumer_data, dict):
                    raise errors.BadRequest(
                        "Allocation data for consumer %s must be a dict" % consumer_uuid
                    )

                allocations = consumer_data.get("allocations") or {}
                project_id = consumer_data.get("project_id")
                user_id = consumer_data.get("user_id")
                consumer_type = (
                    consumer_data.get("consumer_type") if mv.is_at_least(38) else None
                )

                # consumer_generation is required
                if "consumer_generation" not in consumer_data:
                    raise errors.BadRequest(
                        "'consumer_generation' is required for consumer %s"
                        % consumer_uuid
                    )

                # At 1.38+, consumer_type is required
                if mv.is_at_least(38):
                    if "consumer_type" not in consumer_data:
                        raise errors.BadRequest(
                            "'consumer_type' is a required property."
                        )
                    import re
                    if not re.match(r"^[A-Z0-9_]+$", consumer_type or ""):
                        raise errors.BadRequest(
                            "'%s' does not match '^[A-Z0-9_]+$'." % consumer_type
                        )
                # Before 1.38, consumer_type is not allowed
                elif "consumer_type" in consumer_data:
                    raise errors.BadRequest(
                        "JSON does not validate: Additional properties are not "
                        "allowed ('consumer_type' was unexpected)."
                    )
                consumer_generation = consumer_data["consumer_generation"]

                # Handle consumer_generation: null vs integer
                if consumer_generation is None:
                    # Check if consumer already exists
                    existing = tx.run(
                        "MATCH (c:Consumer {uuid: $uuid}) RETURN c.generation AS gen",
                        uuid=consumer_uuid,
                    ).single()

                    if existing is not None:
                        raise errors.ConsumerGenerationConflict(
                            uuid=consumer_uuid,
                            expected="null",
                            got=existing["gen"],
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
                else:
                    # Verify or create consumer at expected generation
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
                            uuid=consumer_uuid,
                            expected=consumer_generation,
                            got=consumer.get("generation", 0),
                        )

                    # Update consumer_type if provided (1.38+)
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
                            raise errors.NotFound(
                                "Inventory for %s not found on provider %s"
                                % (rc_name, rp_uuid)
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

    return flask.Response(status=204)
