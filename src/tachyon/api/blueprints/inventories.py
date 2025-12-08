"""Inventories API blueprint.

Implements Placement-compatible inventory management for ResourceProviders.
"""

from __future__ import annotations

from flask import Blueprint, Response, jsonify, request
from neo4j.time import DateTime

from tachyon.api.errors import (
    BadRequest,
    InvalidInventory,
    InventoryInUse,
    NotFound,
    ResourceProviderGenerationConflict,
)

bp = Blueprint(
    "inventories", __name__, url_prefix="/resource_providers/<string:uuid>/inventories"
)


def _driver():
    """Get the Neo4j driver from the Flask app."""
    from tachyon.api.app import get_driver

    return get_driver()


def _ensure_resource_class(session, name: str) -> None:
    """Ensure a resource class exists, creating if necessary."""
    session.run(
        """
        MERGE (rc:ResourceClass {name: $name})
        ON CREATE SET rc.created_at = datetime(), rc.updated_at = datetime()
        ON MATCH SET rc.updated_at = datetime()
        """,
        name=name,
    )


def _validate_inventory(inv: dict, rc_name: str) -> None:
    """Validate inventory values.

    Args:
        inv: Inventory dict with total, reserved, etc.
        rc_name: Resource class name for error messages.

    Raises:
        InvalidInventory: If values are invalid.
    """
    total = inv.get("total", 0)
    reserved = inv.get("reserved", 0)
    min_unit = inv.get("min_unit", 1)
    max_unit = inv.get("max_unit", total)
    step_size = inv.get("step_size", 1)
    allocation_ratio = inv.get("allocation_ratio", 1.0)

    if total < 0:
        raise InvalidInventory(f"Inventory {rc_name}: total must be >= 0.")
    if reserved < 0:
        raise InvalidInventory(f"Inventory {rc_name}: reserved must be >= 0.")
    if min_unit < 1:
        raise InvalidInventory(f"Inventory {rc_name}: min_unit must be >= 1.")
    if max_unit < min_unit:
        raise InvalidInventory(f"Inventory {rc_name}: max_unit must be >= min_unit.")
    if step_size < 1:
        raise InvalidInventory(f"Inventory {rc_name}: step_size must be >= 1.")
    if allocation_ratio <= 0:
        raise InvalidInventory(f"Inventory {rc_name}: allocation_ratio must be > 0.")


def _check_provider_exists(session, uuid: str) -> None:
    """Check if a resource provider exists.

    Args:
        session: Neo4j session.
        uuid: Provider UUID.

    Raises:
        NotFound: If provider doesn't exist.
    """
    result = session.run(
        "MATCH (rp:ResourceProvider {uuid: $uuid}) RETURN rp",
        uuid=uuid,
    ).single()
    if not result:
        raise NotFound(f"Resource provider {uuid} not found.")


def _serialize_for_json(value):
    """Convert Neo4j temporal values to JSON-serializable strings."""
    if isinstance(value, DateTime):
        # neo4j.time.DateTime implements iso_format for consistent output
        return value.iso_format()
    if isinstance(value, dict):
        return {k: _serialize_for_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize_for_json(v) for v in value]
    return value


@bp.route("", methods=["GET"])
def list_inventories(uuid: str) -> tuple[Response, int]:
    """List all inventories for a resource provider."""
    with _driver().session() as session:
        res = session.run(
            """
            MATCH (rp:ResourceProvider {uuid: $uuid})
            OPTIONAL MATCH (rp)-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(rc:ResourceClass)
            RETURN rp.generation AS generation,
                   collect({rc: rc.name, inv: properties(inv)}) AS inventories
            """,
            uuid=uuid,
        ).single()

        if not res or res["generation"] is None:
            raise NotFound(f"Resource provider {uuid} not found.")

        inv_map = {
            row["rc"]: _serialize_for_json(row["inv"])
            for row in res["inventories"]
            if row["rc"]
        }

    return jsonify(
        {
            "resource_provider_generation": res["generation"],
            "inventories": inv_map,
        }
    ), 200


@bp.route("", methods=["PUT"])
def replace_inventories(uuid: str) -> tuple[Response, int]:
    """Replace all inventories for a resource provider.

    Request Body:
        resource_provider_generation: Required. Current generation.
        inventories: Dict mapping resource class names to inventory objects.
    """
    data = request.get_json(force=True, silent=True) or {}
    generation = data.get("resource_provider_generation")
    inventories = data.get("inventories") or {}

    if generation is None:
        raise BadRequest("'resource_provider_generation' is a required field.")

    # Validate all inventories before starting transaction
    for rc_name, inv in inventories.items():
        _validate_inventory(inv, rc_name)

    with _driver().session() as session:
        _check_provider_exists(session, uuid)

        tx = session.begin_transaction()
        try:
            res = tx.run(
                "MATCH (rp:ResourceProvider {uuid: $uuid}) "
                "WHERE rp.generation = $generation RETURN rp",
                uuid=uuid,
                generation=generation,
            ).single()

            if not res:
                raise ResourceProviderGenerationConflict(
                    f"Generation mismatch for resource provider {uuid}."
                )

            # Delete existing inventories without allocations
            tx.run(
                """
                MATCH (rp:ResourceProvider {uuid: $uuid})-[:HAS_INVENTORY]->(old_inv)
                OPTIONAL MATCH (old_inv)<-[alloc:CONSUMES]-()
                WITH old_inv, alloc
                WHERE alloc IS NULL
                DETACH DELETE old_inv
                """,
                uuid=uuid,
            )

            # Create new inventories
            for rc_name, inv in inventories.items():
                _ensure_resource_class(tx, rc_name)
                tx.run(
                    """
                    MATCH (rp:ResourceProvider {uuid: $uuid})
                    MATCH (rc:ResourceClass {name: $rc_name})
                    MERGE (rp)-[:HAS_INVENTORY]->(inv:Inventory)-[:OF_CLASS]->(rc)
                    SET inv.total = $total,
                        inv.reserved = COALESCE($reserved, 0),
                        inv.min_unit = COALESCE($min_unit, 1),
                        inv.max_unit = COALESCE($max_unit, $total),
                        inv.step_size = COALESCE($step_size, 1),
                        inv.allocation_ratio = COALESCE($allocation_ratio, 1.0),
                        inv.updated_at = datetime()
                    """,
                    uuid=uuid,
                    rc_name=rc_name,
                    total=inv.get("total", 0),
                    reserved=inv.get("reserved"),
                    min_unit=inv.get("min_unit"),
                    max_unit=inv.get("max_unit"),
                    step_size=inv.get("step_size"),
                    allocation_ratio=inv.get("allocation_ratio"),
                )

            # Increment generation
            updated = tx.run(
                """
                MATCH (rp:ResourceProvider {uuid: $uuid})
                SET rp.generation = rp.generation + 1,
                    rp.updated_at = datetime()
                RETURN rp.generation AS generation
                """,
                uuid=uuid,
            ).single()

            tx.commit()
        except Exception:
            tx.rollback()
            raise

    return jsonify(
        {
            "resource_provider_generation": updated["generation"],
            "inventories": inventories,
        }
    ), 200


@bp.route("/<string:rc_name>", methods=["GET"])
def get_inventory(uuid: str, rc_name: str) -> tuple[Response, int]:
    """Get a specific inventory by resource class."""
    with _driver().session() as session:
        res = session.run(
            """
            MATCH (rp:ResourceProvider {uuid: $uuid})
                  -[:HAS_INVENTORY]->(inv)
                  -[:OF_CLASS]->(rc:ResourceClass {name: $rc})
            RETURN rp.generation AS generation, properties(inv) AS inv
            """,
            uuid=uuid,
            rc=rc_name,
        ).single()

        if not res:
            # Check if provider exists vs inventory missing
            _check_provider_exists(session, uuid)
            raise NotFound(
                f"Inventory for resource class {rc_name} not found "
                f"on resource provider {uuid}."
            )

    return jsonify(
        {
            "resource_provider_generation": res["generation"],
            "inventory": _serialize_for_json(res["inv"]),
        }
    ), 200


@bp.route("/<string:rc_name>", methods=["PUT"])
def put_inventory(uuid: str, rc_name: str) -> tuple[Response, int]:
    """Create or update a specific inventory."""
    data = request.get_json(force=True, silent=True) or {}
    generation = data.get("resource_provider_generation")
    inv = data.get("inventory") or data

    if generation is None:
        raise BadRequest("'resource_provider_generation' is a required field.")

    _validate_inventory(inv, rc_name)

    with _driver().session() as session:
        tx = session.begin_transaction()
        try:
            res = tx.run(
                "MATCH (rp:ResourceProvider {uuid: $uuid}) "
                "WHERE rp.generation = $generation RETURN rp",
                uuid=uuid,
                generation=generation,
            ).single()

            if not res:
                # Check if provider exists
                exists = tx.run(
                    "MATCH (rp:ResourceProvider {uuid: $uuid}) RETURN rp",
                    uuid=uuid,
                ).single()
                if not exists:
                    raise NotFound(f"Resource provider {uuid} not found.")
                raise ResourceProviderGenerationConflict(
                    f"Generation mismatch for resource provider {uuid}."
                )

            _ensure_resource_class(tx, rc_name)
            tx.run(
                """
                MATCH (rp:ResourceProvider {uuid: $uuid})
                MATCH (rc:ResourceClass {name: $rc})
                MERGE (rp)-[:HAS_INVENTORY]->(inv:Inventory)-[:OF_CLASS]->(rc)
                SET inv.total = $total,
                    inv.reserved = COALESCE($reserved, 0),
                    inv.min_unit = COALESCE($min_unit, 1),
                    inv.max_unit = COALESCE($max_unit, $total),
                    inv.step_size = COALESCE($step_size, 1),
                    inv.allocation_ratio = COALESCE($allocation_ratio, 1.0),
                    inv.updated_at = datetime()
                """,
                uuid=uuid,
                rc=rc_name,
                total=inv.get("total", 0),
                reserved=inv.get("reserved"),
                min_unit=inv.get("min_unit"),
                max_unit=inv.get("max_unit"),
                step_size=inv.get("step_size"),
                allocation_ratio=inv.get("allocation_ratio"),
            )

            updated = tx.run(
                """
                MATCH (rp:ResourceProvider {uuid: $uuid})
                SET rp.generation = rp.generation + 1,
                    rp.updated_at = datetime()
                RETURN rp.generation AS generation
                """,
                uuid=uuid,
            ).single()

            tx.commit()
        except Exception:
            tx.rollback()
            raise

    return jsonify({"resource_provider_generation": updated["generation"]}), 200


@bp.route("/<string:rc_name>", methods=["DELETE"])
def delete_inventory(uuid: str, rc_name: str) -> Response:
    """Delete a specific inventory.

    Will fail if the inventory has active allocations.
    """
    with _driver().session() as session:
        # Check for allocations first
        has_allocs = session.run(
            """
            MATCH (rp:ResourceProvider {uuid: $uuid})
                  -[:HAS_INVENTORY]->(inv)
                  -[:OF_CLASS]->(rc:ResourceClass {name: $rc})
            OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
            RETURN inv, count(alloc) AS alloc_count
            """,
            uuid=uuid,
            rc=rc_name,
        ).single()

        if not has_allocs or not has_allocs["inv"]:
            _check_provider_exists(session, uuid)
            raise NotFound(
                f"Inventory for resource class {rc_name} not found "
                f"on resource provider {uuid}."
            )

        if has_allocs["alloc_count"] > 0:
            raise InventoryInUse(
                f"Inventory for {rc_name} has {has_allocs['alloc_count']} "
                f"active allocations."
            )

        # Safe to delete
        session.run(
            """
            MATCH (rp:ResourceProvider {uuid: $uuid})
                  -[:HAS_INVENTORY]->(inv)
                  -[:OF_CLASS]->(rc:ResourceClass {name: $rc})
            DETACH DELETE inv
            """,
            uuid=uuid,
            rc=rc_name,
        )

    return Response(status=204)
