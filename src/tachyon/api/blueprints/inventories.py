# SPDX-License-Identifier: Apache-2.0

"""Inventories API blueprint.

Implements Placement-compatible inventory management for ResourceProviders.
"""

from __future__ import annotations

from flask import Blueprint, Response, g, jsonify, request
from neo4j.time import DateTime
from datetime import datetime, timezone

from tachyon.api.errors import (
    BadRequest,
    Conflict,
    InvalidInventory,
    InventoryInUse,
    NotFound,
    ResourceProviderGenerationConflict,
)
from tachyon.api.microversion import Microversion

bp = Blueprint(
    "inventories", __name__, url_prefix="/resource_providers/<string:uuid>/inventories"
)

INT_MAX = 2_147_483_647


def _driver():
    """Get the Neo4j driver from the Flask app."""
    from tachyon.api.app import get_driver

    return get_driver()


def _mv() -> Microversion:
    mv = getattr(g, "microversion", None)
    if mv is None:
        return Microversion(1, 0)
    return mv


def _httpdate(dt: datetime | None = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")


def _abs_url(path: str) -> str:
    base = request.host_url.rstrip("/")
    return f"{base}{path}"


def _format_inventory_response(inv_props: dict, generation: int) -> dict:
    body = {"resource_provider_generation": generation}
    body.update(_serialize_for_json(inv_props))
    return body


def _normalize_inventory(inv: dict) -> dict:
    # Note: validation of 'total' is done in _validate_inventory
    total = inv.get("total", 0)
    reserved = inv.get("reserved")
    if reserved is None:
        reserved = 0
    min_unit = inv.get("min_unit")
    if min_unit is None:
        min_unit = 1
    max_unit = inv.get("max_unit")
    if max_unit is None:
        max_unit = total
    step_size = inv.get("step_size")
    if step_size is None:
        step_size = 1
    allocation_ratio = inv.get("allocation_ratio")
    if allocation_ratio is None:
        allocation_ratio = 1.0
    return {
        "total": total,
        "reserved": reserved,
        "min_unit": min_unit,
        "max_unit": max_unit,
        "step_size": step_size,
        "allocation_ratio": allocation_ratio,
    }


def _ensure_resource_class(session, name: str, detail: str) -> None:
    """Ensure a resource class exists, otherwise raise BadRequest."""
    STANDARD_RCS = {"VCPU", "MEMORY_MB", "DISK_GB", "IPV4_ADDRESS"}
    found = session.run(
        "MATCH (rc:ResourceClass {name: $name}) RETURN rc",
        name=name,
    ).single()
    if not found:
        if name in STANDARD_RCS:
            session.run(
                """
                MERGE (rc:ResourceClass {name: $name})
                ON CREATE SET rc.created_at = datetime(), rc.updated_at = datetime()
                ON MATCH SET rc.updated_at = datetime()
                """,
                name=name,
            )
        else:
            raise BadRequest(detail)


def _validate_inventory(
    inv: dict,
    rc_name: str,
    mv: Microversion,
    action: str = "update",
    rp_uuid: str | None = None,
) -> None:
    """Validate inventory values.

    Args:
        inv: Inventory dict with total, reserved, etc.
        rc_name: Resource class name for error messages.

    Raises:
        InvalidInventory: If values are invalid.
    """
    # Check for required 'total' field first
    if "total" not in inv:
        raise BadRequest("JSON does not validate: 'total' is a required property")

    total = inv.get("total", 0)
    reserved = inv.get("reserved", 0)
    min_unit = inv.get("min_unit", 1)
    max_unit = inv.get("max_unit", total)
    step_size = inv.get("step_size", 1)
    allocation_ratio = inv.get("allocation_ratio", 1.0)

    def _check_max(value):
        if value > INT_MAX:
            raise BadRequest("Failed validating 'maximum'")

    prefix = "Unable to update inventory"
    if action == "create":
        prefix = "Unable to create inventory for resource provider"
    elif action == "replace":
        prefix = "Unable to update inventory"

    if total < 1:
        raise BadRequest(
            f"JSON does not validate: {total} is less than the minimum of 1\n"
            "Failed validating 'minimum' in schema['properties']['total']"
        )
    _check_max(total)
    if reserved < 0:
        raise BadRequest(
            f"JSON does not validate: {reserved} is less than the minimum of 0\n"
            "Failed validating 'minimum' in schema['properties']['reserved']"
        )
    _check_max(reserved)
    if min_unit < 1:
        raise BadRequest(
            f"JSON does not validate: {min_unit} is less than the minimum of 1\n"
            "Failed validating 'minimum' in schema['properties']['min_unit']"
        )
    _check_max(min_unit)
    if max_unit < 1:
        raise BadRequest(
            f"JSON does not validate: {max_unit} is less than the minimum of 1\n"
            "Failed validating 'minimum' in schema['properties']['max_unit']"
        )
    _check_max(max_unit)
    if step_size < 1:
        raise BadRequest(
            f"JSON does not validate: {step_size} is less than the minimum of 1\n"
            "Failed validating 'minimum' in schema['properties']['step_size']"
        )
    _check_max(step_size)
    if allocation_ratio <= 0:
        raise BadRequest(
            "Failed validating 'minimum' in schema['properties']['allocation_ratio']"
        )
    if allocation_ratio >= 3.40282e39:
        raise BadRequest(
            "Failed validating 'maximum' in schema['properties']['allocation_ratio']"
        )

    allow_equal = mv.is_at_least(26)
    msg_prefix = prefix
    if rp_uuid:
        if "for resource provider" in msg_prefix:
            msg_prefix = f"{msg_prefix} {rp_uuid}"
        else:
            msg_prefix = f"{msg_prefix} for resource provider {rp_uuid}"

    if reserved > total or (not allow_equal and reserved == total):
        msg = msg_prefix
        if allow_equal:
            # At microversion >= 1.26, reserved can equal total, so only > is an error
            msg = f"{msg}: reserved value ({reserved}) is greater than total ({total})"
        else:
            # At microversion < 1.26, reserved >= total is an error
            msg = f"{msg}: reserved value ({reserved}) is greater than or equal to total ({total})"
        raise BadRequest(msg)
    if max_unit < min_unit:
        raise BadRequest(f"Inventory {rc_name}: max_unit must be >= min_unit.")


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
        raise NotFound(f"No resource provider with uuid {uuid} found")


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
    mv = _mv()
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
            _check_provider_exists(session, uuid)

        inv_map = {
            row["rc"]: _serialize_for_json(row["inv"])
            for row in res["inventories"]
            if row["rc"]
        }

    resp = jsonify(
        {
            "resource_provider_generation": res["generation"],
            "inventories": inv_map,
        }
    )
    if mv.is_at_least(15):
        resp.headers["cache-control"] = "no-cache"
        resp.headers["last-modified"] = _httpdate()
    return resp, 200


@bp.route("", methods=["PUT"])
def replace_inventories(uuid: str) -> tuple[Response, int]:
    """Replace all inventories for a resource provider.

    Request Body:
        resource_provider_generation: Required. Current generation.
        inventories: Dict mapping resource class names to inventory objects.
    """
    mv = _mv()
    try:
        data = request.get_json(force=True, silent=False) or {}
    except Exception as exc:
        raise BadRequest(f"Malformed JSON: {exc}")
    generation = data.get("resource_provider_generation")
    inventories = data.get("inventories") or {}

    if generation is None:
        raise BadRequest("'resource_provider_generation' is a required field.")

    # Validate all inventories before starting transaction
    normalized_inventories = {}
    for rc_name, inv in inventories.items():
        _validate_inventory(inv, rc_name, mv, action="replace", rp_uuid=uuid)
        normalized_inventories[rc_name] = _normalize_inventory(inv)

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
                raise Conflict(
                    "resource provider generation conflict",
                    code="placement.concurrent_update",
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
            for rc_name, inv in normalized_inventories.items():
                _ensure_resource_class(tx, rc_name, f"Unknown resource class in inventory: {rc_name}")
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

    resp = jsonify(
        {
            "resource_provider_generation": updated["generation"],
            "inventories": normalized_inventories,
        }
    )
    if mv.is_at_least(15):
        resp.headers["cache-control"] = "no-cache"
        resp.headers["last-modified"] = _httpdate()
    return resp, 200


@bp.route("/<string:rc_name>", methods=["GET"])
def get_inventory(uuid: str, rc_name: str) -> tuple[Response, int]:
    """Get a specific inventory by resource class."""
    mv = _mv()
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
            raise NotFound(f"No inventory of class {rc_name} for {uuid}")

    body = {"resource_provider_generation": res["generation"]}
    body.update(_serialize_for_json(res["inv"]))
    resp = jsonify(body)
    if mv.is_at_least(15):
        resp.headers["cache-control"] = "no-cache"
        resp.headers["last-modified"] = _httpdate()
    return resp, 200


@bp.route("", methods=["POST"])
def create_inventory(uuid: str) -> tuple[Response, int]:
    """Create a single inventory record."""
    mv = _mv()
    try:
        data = request.get_json(force=True, silent=False) or {}
    except Exception as exc:
        raise BadRequest(f"Malformed JSON: {exc}")

    rc_name = data.get("resource_class")
    generation = data.get("resource_provider_generation")
    if rc_name is None:
        raise BadRequest("JSON does not validate")

    _validate_inventory(data, rc_name, mv, action="create", rp_uuid=uuid)
    norm = _normalize_inventory(data)

    with _driver().session() as session:
        _check_provider_exists(session, uuid)
        _ensure_resource_class(
            session, rc_name, f"No such resource class {rc_name}"
        )

        # Ensure inventory does not already exist
        exists = session.run(
            """
            MATCH (rp:ResourceProvider {uuid: $uuid})
                  -[:HAS_INVENTORY]->(:Inventory)-[:OF_CLASS]->(rc:ResourceClass {name: $rc})
            RETURN rc
            """,
            uuid=uuid,
            rc=rc_name,
        ).single()
        if exists:
            raise Conflict("Update conflict")

        # Verify generation
        current = session.run(
            "MATCH (rp:ResourceProvider {uuid: $uuid}) RETURN rp.generation AS gen",
            uuid=uuid,
        ).single()
        current_gen = current["gen"] if current else None
        if generation is not None and current_gen != generation:
            raise Conflict(
                "resource provider generation conflict",
                code="placement.concurrent_update",
            )

        session.run(
            """
            MATCH (rp:ResourceProvider {uuid: $uuid})
            MATCH (rc:ResourceClass {name: $rc})
            CREATE (rp)-[:HAS_INVENTORY]->(inv:Inventory)-[:OF_CLASS]->(rc)
            SET inv.total = $total,
                inv.reserved = COALESCE($reserved, 0),
                inv.min_unit = COALESCE($min_unit, 1),
                inv.max_unit = COALESCE($max_unit, $total),
                inv.step_size = COALESCE($step_size, 1),
                inv.allocation_ratio = COALESCE($allocation_ratio, 1.0),
                inv.created_at = datetime(),
                inv.updated_at = datetime()
            """,
            uuid=uuid,
            rc=rc_name,
            total=norm["total"],
            reserved=norm["reserved"],
            min_unit=norm["min_unit"],
            max_unit=norm["max_unit"],
            step_size=norm["step_size"],
            allocation_ratio=norm["allocation_ratio"],
        )

        updated = session.run(
            """
            MATCH (rp:ResourceProvider {uuid: $uuid})
            SET rp.generation = rp.generation + 1,
                rp.updated_at = datetime()
            RETURN rp.generation AS generation
            """,
            uuid=uuid,
        ).single()

    body = _format_inventory_response(norm, updated["generation"])
    resp = jsonify(body)
    resp.headers["Location"] = _abs_url(
        f"/resource_providers/{uuid}/inventories/{rc_name}"
    )
    resp.status_code = 201
    return resp, 201


@bp.route("/<string:rc_name>", methods=["PUT"])
def put_inventory(uuid: str, rc_name: str) -> tuple[Response, int]:
    """Update a specific inventory (must already exist)."""
    mv = _mv()
    try:
        data = request.get_json(force=True, silent=False) or {}
    except Exception as exc:
        raise BadRequest(f"Malformed JSON: {exc}")

    generation = data.get("resource_provider_generation")
    inv = data.get("inventory") or data

    # Validate required fields
    allowed_keys = {"resource_provider_generation", "total", "reserved", "min_unit", "max_unit", "step_size", "allocation_ratio"}
    extra_keys = set(data.keys()) - allowed_keys
    if extra_keys:
        raise BadRequest("JSON does not validate")

    if generation is None:
        raise BadRequest("'resource_provider_generation' is a required field.")

    _validate_inventory(inv, rc_name, mv, action="update", rp_uuid=uuid)
    norm = _normalize_inventory(inv)

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
                    "resource provider generation conflict"
                )

            # Check if inventory exists for this resource class
            inv_exists = tx.run(
                """
                MATCH (rp:ResourceProvider {uuid: $uuid})
                      -[:HAS_INVENTORY]->(inv)
                      -[:OF_CLASS]->(rc:ResourceClass {name: $rc})
                RETURN inv
                """,
                uuid=uuid,
                rc=rc_name,
            ).single()

            if not inv_exists:
                raise BadRequest(
                    f"No inventory record with resource class {rc_name} found "
                    f"for resource provider {uuid}"
                )

            tx.run(
                """
                MATCH (rp:ResourceProvider {uuid: $uuid})
                      -[:HAS_INVENTORY]->(inv)
                      -[:OF_CLASS]->(rc:ResourceClass {name: $rc})
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
                total=norm.get("total", 0),
                reserved=norm.get("reserved"),
                min_unit=norm.get("min_unit"),
                max_unit=norm.get("max_unit"),
                step_size=norm.get("step_size"),
                allocation_ratio=norm.get("allocation_ratio"),
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

    body = _format_inventory_response(norm, updated["generation"])
    resp = jsonify(body)
    return resp, 200


@bp.route("/<string:rc_name>", methods=["DELETE"])
def delete_inventory(uuid: str, rc_name: str) -> Response:
    """Delete a specific inventory.

    Will fail if the inventory has active allocations.
    """
    mv = _mv()
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
            raise NotFound(f"No inventory of class {rc_name} found for delete")

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
        session.run(
            """
            MATCH (rp:ResourceProvider {uuid: $uuid})
            SET rp.generation = rp.generation + 1,
                rp.updated_at = datetime()
            """,
            uuid=uuid,
        )

    resp = Response(status=204)
    resp.headers.pop("Content-Type", None)
    return resp


@bp.route("", methods=["DELETE"])
def delete_all_inventories(uuid: str) -> Response:
    """Delete all inventories for a resource provider (microversion >=1.5)."""
    mv = _mv()
    if mv.minor < 5:
        return Response(status=405)

    with _driver().session() as session:
        _check_provider_exists(session, uuid)
        session.run(
            """
            MATCH (rp:ResourceProvider {uuid: $uuid})-[:HAS_INVENTORY]->(inv)
            DETACH DELETE inv
            """,
            uuid=uuid,
        )
        session.run(
            """
            MATCH (rp:ResourceProvider {uuid: $uuid})
            SET rp.generation = rp.generation + 1,
                rp.updated_at = datetime()
            """,
            uuid=uuid,
        )

    resp = Response(status=204)
    resp.headers.pop("Content-Type", None)
    return resp
