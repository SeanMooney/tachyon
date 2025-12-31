"""Allocation Candidates API blueprint.

Implements Placement-compatible allocation candidate queries for scheduling.
"""

from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, Response, g, jsonify, request

from tachyon.api.errors import BadRequest, NotFound
from tachyon.api.microversion import Microversion

bp = Blueprint("allocation_candidates", __name__, url_prefix="/allocation_candidates")


def _driver():
    """Get the Neo4j driver from the Flask app."""
    from tachyon.api.app import get_driver

    return get_driver()


def _mv() -> Microversion:
    """Return the parsed microversion from the request context."""
    mv = getattr(g, "microversion", None)
    if mv is None:
        return Microversion(1, 0)
    return mv


def _httpdate(dt: datetime | None = None) -> str:
    """Return an HTTP-date string."""
    dt = dt or datetime.now(timezone.utc)
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")


def _parse_resources(resources_str: str) -> dict[str, int]:
    """Parse resources query parameter.

    Format: CLASS1:AMOUNT1,CLASS2:AMOUNT2,...

    Returns:
        Dict mapping resource class names to amounts.

    Raises:
        BadRequest: If format is invalid.
    """
    if not resources_str:
        raise BadRequest(
            "Badly formed resources parameter. Expected resources query string "
            "parameter in form: VCPU:1,MEMORY_MB:2048. "
            "Got: empty string."
        )

    result = {}
    for part in resources_str.split(","):
        if ":" not in part:
            raise BadRequest(
                "Badly formed resources parameter. Expected resources query string "
                f"parameter in form: VCPU:1,MEMORY_MB:2048. Got: {resources_str}"
            )
        rc, amount_str = part.split(":", 1)
        try:
            amount = int(amount_str)
        except ValueError:
            raise BadRequest(
                "Badly formed resources parameter. Expected resources query string "
                f"parameter in form: VCPU:1,MEMORY_MB:2048. Got: {resources_str}"
            )
        result[rc] = amount

    return result


def _validate_resource_classes(session, resource_classes: list[str]) -> None:
    """Check that all resource classes exist.

    Raises:
        BadRequest: If any resource class doesn't exist.
    """
    STANDARD_RCS = {"VCPU", "MEMORY_MB", "DISK_GB", "IPV4_ADDRESS"}

    for rc in resource_classes:
        # Standard classes are implicitly valid
        if rc in STANDARD_RCS:
            continue

        result = session.run(
            "MATCH (rc:ResourceClass {name: $name}) RETURN rc",
            name=rc,
        ).single()

        if not result:
            raise BadRequest(f"Invalid resource class in resources parameter: {rc}")


def _get_providers_with_capacity(
    session, resources: dict[str, int]
) -> list[dict]:
    """Find providers with capacity for all requested resources.

    Returns:
        List of provider dicts with uuid, resources, and capacity info.
    """
    # For each resource class, find providers that have inventory
    # and sufficient capacity
    providers = {}

    for rc_name, amount in resources.items():
        result = session.run(
            """
            MATCH (rp:ResourceProvider)-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(rc:ResourceClass {name: $rc})
            OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
            WITH rp, inv, rc,
                 COALESCE(sum(alloc.used), 0) AS used,
                 inv.total AS total,
                 COALESCE(inv.reserved, 0) AS reserved,
                 COALESCE(inv.allocation_ratio, 1.0) AS allocation_ratio
            WITH rp, rc.name AS rc_name,
                 (total - reserved) * allocation_ratio - used AS available,
                 total, reserved, used, allocation_ratio
            WHERE available >= $amount
            RETURN rp.uuid AS uuid, rp.generation AS generation,
                   rc_name, total, reserved, used, allocation_ratio,
                   (total - reserved) * allocation_ratio AS capacity
            """,
            rc=rc_name,
            amount=amount,
        )

        rc_providers = {}
        for row in result:
            uuid = row["uuid"]
            rc_providers[uuid] = {
                "uuid": uuid,
                "generation": row["generation"],
                "rc_name": rc_name,
                "total": row["total"],
                "reserved": row["reserved"],
                "used": row["used"],
                "allocation_ratio": row["allocation_ratio"],
                "capacity": int(row["capacity"]),
            }

        if not providers:
            providers = rc_providers
        else:
            # Intersect - keep only providers that have all resources
            providers = {
                uuid: prov for uuid, prov in providers.items()
                if uuid in rc_providers
            }

    return list(providers.values())


def _build_allocation_requests_dict(
    providers: list[dict], resources: dict[str, int]
) -> list[dict]:
    """Build allocation requests in dict format (1.12+)."""
    return [
        {
            "allocations": {
                prov["uuid"]: {
                    "resources": resources
                }
            }
        }
        for prov in providers
    ]


def _build_allocation_requests_list(
    providers: list[dict], resources: dict[str, int]
) -> list[dict]:
    """Build allocation requests in list format (<1.12)."""
    return [
        {
            "allocations": [
                {
                    "resource_provider": {"uuid": prov["uuid"]},
                    "resources": resources
                }
            ]
        }
        for prov in providers
    ]


def _build_provider_summaries(
    session, provider_uuids: list[str], resources: dict[str, int], mv: Microversion
) -> dict:
    """Build provider summaries with capacity and usage."""
    summaries = {}

    for uuid in provider_uuids:
        result = session.run(
            """
            MATCH (rp:ResourceProvider {uuid: $uuid})
            OPTIONAL MATCH (rp)-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(rc:ResourceClass)
            OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
            WITH rp, rc.name AS rc_name, inv,
                 COALESCE(sum(alloc.used), 0) AS used
            WHERE inv IS NOT NULL
            RETURN rp.uuid AS uuid, rp.generation AS generation,
                   rc_name, inv.total AS total,
                   COALESCE(inv.reserved, 0) AS reserved,
                   COALESCE(inv.allocation_ratio, 1.0) AS allocation_ratio,
                   used
            """,
            uuid=uuid,
        )

        resource_data = {}
        for row in result:
            rc_name = row["rc_name"]
            # Before 1.27, only show requested resources
            if not mv.is_at_least(27) and rc_name not in resources:
                continue

            total = row["total"]
            reserved = row["reserved"]
            ratio = row["allocation_ratio"]
            used = int(row["used"])

            resource_data[rc_name] = {
                "capacity": int((total - reserved) * ratio),
                "used": used,
            }

        summary = {"resources": resource_data}

        # Add traits at 1.17+
        if mv.is_at_least(17):
            traits_result = session.run(
                """
                MATCH (rp:ResourceProvider {uuid: $uuid})-[:HAS_TRAIT]->(t:Trait)
                RETURN collect(t.name) AS traits
                """,
                uuid=uuid,
            ).single()
            summary["traits"] = traits_result["traits"] if traits_result else []

        # Add parent/root at 1.29+
        if mv.is_at_least(29):
            tree_result = session.run(
                """
                MATCH (rp:ResourceProvider {uuid: $uuid})
                OPTIONAL MATCH (parent:ResourceProvider)-[:PARENT_OF]->(rp)
                OPTIONAL MATCH path = (root:ResourceProvider)-[:PARENT_OF*0..]->(rp)
                WHERE NOT EXISTS { MATCH (:ResourceProvider)-[:PARENT_OF]->(root) }
                WITH rp, parent, root
                ORDER BY length(path) DESC
                WITH rp, parent, collect(root)[0] AS root_provider
                RETURN parent.uuid AS parent_uuid, root_provider.uuid AS root_uuid
                """,
                uuid=uuid,
            ).single()
            if tree_result:
                summary["parent_provider_uuid"] = tree_result["parent_uuid"]
                summary["root_provider_uuid"] = tree_result["root_uuid"] or uuid

        summaries[uuid] = summary

    return summaries


@bp.route("", methods=["GET"])
def list_allocation_candidates() -> tuple[Response, int]:
    """Get allocation candidates for requested resources.

    Query Parameters:
        resources: Required. Format: CLASS1:AMOUNT1,CLASS2:AMOUNT2
        limit: Optional (1.16+). Maximum number of candidates to return.
        required: Optional (1.17+). Required traits.

    Returns:
        allocation_requests: List of possible allocations
        provider_summaries: Summary of each provider's capacity
    """
    mv = _mv()

    # Allocation candidates requires microversion >= 1.10
    if not mv.is_at_least(10):
        raise NotFound("The resource could not be found.")

    # Validate allowed query parameters based on microversion
    allowed_params = {"resources"}
    if mv.is_at_least(16):
        allowed_params.add("limit")
    if mv.is_at_least(17):
        allowed_params.add("required")
    if mv.is_at_least(21):
        allowed_params.add("member_of")
    if mv.is_at_least(25):
        allowed_params.add("in_tree")

    unknown = set(request.args.keys()) - allowed_params
    if unknown:
        raise BadRequest(
            f"Invalid query string parameters: '{list(unknown)[0]}' was unexpected"
        )

    resources_param = request.args.get("resources")
    if resources_param is None:
        raise BadRequest("'resources' is a required property")

    resources = _parse_resources(resources_param)

    # Parse limit
    limit = None
    if "limit" in request.args:
        limit_str = request.args.get("limit")
        # Validate limit format (positive integer)
        if not limit_str or not limit_str.isdigit() or int(limit_str) < 1:
            raise BadRequest(
                f"Invalid query string parameters: Failed validating 'pattern' for limit"
            )
        limit = int(limit_str)

    with _driver().session() as session:
        # Validate resource classes exist
        _validate_resource_classes(session, list(resources.keys()))

        # Find providers with capacity
        providers = _get_providers_with_capacity(session, resources)

        # Apply limit
        if limit and len(providers) > limit:
            providers = providers[:limit]

        # Build response based on microversion
        if mv.is_at_least(12):
            allocation_requests = _build_allocation_requests_dict(providers, resources)
        else:
            allocation_requests = _build_allocation_requests_list(providers, resources)

        provider_uuids = [p["uuid"] for p in providers]
        provider_summaries = _build_provider_summaries(
            session, provider_uuids, resources, mv
        )

    response_data = {
        "allocation_requests": allocation_requests,
        "provider_summaries": provider_summaries,
    }

    resp = jsonify(response_data)
    if mv.is_at_least(15):
        resp.headers["cache-control"] = "no-cache"
        resp.headers["last-modified"] = _httpdate()

    return resp, 200

