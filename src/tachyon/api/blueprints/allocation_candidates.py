# SPDX-License-Identifier: Apache-2.0

"""Allocation Candidates API blueprint.

Implements Placement-compatible allocation candidate queries for scheduling.
"""

from __future__ import annotations

import datetime
from typing import Any

import flask

from oslo_log import log

from tachyon.api import errors
from tachyon.api import microversion

LOG = log.getLogger(__name__)

bp = flask.Blueprint(
    "allocation_candidates", __name__, url_prefix="/allocation_candidates"
)


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


def _httpdate(dt: datetime.datetime | None = None) -> str:
    """Return an HTTP-date string.

    :param dt: Optional datetime, defaults to now
    :returns: HTTP-date formatted string
    """
    dt = dt or datetime.datetime.now(datetime.timezone.utc)
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")


def _parse_resources(resources_str: str) -> dict[str, int]:
    """Parse resources query parameter.

    Format: CLASS1:AMOUNT1,CLASS2:AMOUNT2,...

    :param resources_str: Resources string to parse
    :returns: Dict mapping resource class names to amounts
    :raises errors.BadRequest: If format is invalid
    """
    if not resources_str:
        raise errors.BadRequest(
            "Badly formed resources parameter. Expected resources query string "
            "parameter in form: VCPU:1,MEMORY_MB:2048. "
            "Got: empty string."
        )

    result: dict[str, int] = {}
    for part in resources_str.split(","):
        if ":" not in part:
            raise errors.BadRequest(
                "Badly formed resources parameter. Expected resources query "
                "string parameter in form: VCPU:1,MEMORY_MB:2048. Got: %s"
                % resources_str
            )
        rc, amount_str = part.split(":", 1)
        try:
            amount = int(amount_str)
        except ValueError:
            raise errors.BadRequest(
                "Badly formed resources parameter. Expected resources query "
                "string parameter in form: VCPU:1,MEMORY_MB:2048. Got: %s"
                % resources_str
            )
        result[rc] = amount

    return result


def _validate_resource_classes(session: Any, resource_classes: list[str]) -> None:
    """Check that all resource classes exist.

    :param session: Neo4j session
    :param resource_classes: List of resource class names
    :raises errors.BadRequest: If any resource class doesn't exist
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
            raise errors.BadRequest(
                "Invalid resource class in resources parameter: %s" % rc
            )


def _get_providers_with_capacity(
    session: Any, resources: dict[str, int]
) -> list[dict[str, Any]]:
    """Find providers with capacity for all requested resources.

    :param session: Neo4j session
    :param resources: Dict of resource_class -> amount
    :returns: List of provider dicts with uuid, resources, and capacity info
    """
    # For each resource class, find providers that have inventory
    # and sufficient capacity
    providers: dict[str, dict[str, Any]] = {}

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

        rc_providers: dict[str, dict[str, Any]] = {}
        for row in result:
            rp_uuid = row["uuid"]
            rc_providers[rp_uuid] = {
                "uuid": rp_uuid,
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
                rp_uuid: prov
                for rp_uuid, prov in providers.items()
                if rp_uuid in rc_providers
            }

    return list(providers.values())


def _build_allocation_requests_dict(
    providers: list[dict[str, Any]], resources: dict[str, int]
) -> list[dict[str, Any]]:
    """Build allocation requests in dict format (1.12+).

    :param providers: List of provider dicts
    :param resources: Dict of resource_class -> amount
    :returns: List of allocation request dicts
    """
    return [
        {"allocations": {prov["uuid"]: {"resources": resources}}} for prov in providers
    ]


def _build_allocation_requests_list(
    providers: list[dict[str, Any]], resources: dict[str, int]
) -> list[dict[str, Any]]:
    """Build allocation requests in list format (<1.12).

    :param providers: List of provider dicts
    :param resources: Dict of resource_class -> amount
    :returns: List of allocation request dicts
    """
    return [
        {
            "allocations": [
                {"resource_provider": {"uuid": prov["uuid"]}, "resources": resources}
            ]
        }
        for prov in providers
    ]


def _build_provider_summaries(
    session: Any,
    provider_uuids: list[str],
    resources: dict[str, int],
    mv: microversion.Microversion,
) -> dict[str, dict[str, Any]]:
    """Build provider summaries with capacity and usage.

    :param session: Neo4j session
    :param provider_uuids: List of provider UUIDs
    :param resources: Dict of requested resources
    :param mv: Microversion instance
    :returns: Dict of provider summaries
    """
    summaries: dict[str, dict[str, Any]] = {}

    for rp_uuid in provider_uuids:
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
            uuid=rp_uuid,
        )

        resource_data: dict[str, dict[str, int]] = {}
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

        summary: dict[str, Any] = {"resources": resource_data}

        # Add traits at 1.17+
        if mv.is_at_least(17):
            traits_result = session.run(
                """
                MATCH (rp:ResourceProvider {uuid: $uuid})-[:HAS_TRAIT]->(t:Trait)
                RETURN collect(t.name) AS traits
                """,
                uuid=rp_uuid,
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
                uuid=rp_uuid,
            ).single()
            if tree_result:
                summary["parent_provider_uuid"] = tree_result["parent_uuid"]
                summary["root_provider_uuid"] = tree_result["root_uuid"] or rp_uuid

        summaries[rp_uuid] = summary

    return summaries


@bp.route("", methods=["GET"])
def list_allocation_candidates() -> tuple[flask.Response, int]:
    """Get allocation candidates for requested resources.

    Query Parameters:
        resources: Required. Format: CLASS1:AMOUNT1,CLASS2:AMOUNT2
        limit: Optional (1.16+). Maximum number of candidates to return.
        required: Optional (1.17+). Required traits.

    :returns: Tuple of (response, status_code)
    """
    mv = _mv()

    # Allocation candidates requires microversion >= 1.10
    if not mv.is_at_least(10):
        raise errors.NotFound("The resource could not be found.")

    # Validate allowed query parameters based on microversion
    allowed_params: set[str] = {"resources"}
    if mv.is_at_least(16):
        allowed_params.add("limit")
    if mv.is_at_least(17):
        allowed_params.add("required")
    if mv.is_at_least(21):
        allowed_params.add("member_of")
    if mv.is_at_least(25):
        allowed_params.add("in_tree")

    unknown = set(flask.request.args) - allowed_params
    if unknown:
        raise errors.BadRequest(
            "Invalid query string parameters: '%s' was unexpected" % list(unknown)[0]
        )

    resources_param = flask.request.args.get("resources")
    if resources_param is None:
        raise errors.BadRequest("'resources' is a required property")

    resources = _parse_resources(resources_param)

    # Parse limit
    limit: int | None = None
    if "limit" in flask.request.args:
        limit_str = flask.request.args.get("limit")
        # Validate limit format (positive integer)
        if not limit_str or not limit_str.isdigit() or int(limit_str) < 1:
            raise errors.BadRequest(
                "Invalid query string parameters: Failed validating 'pattern' for limit"
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
        allocation_requests: list[dict[str, Any]]
        if mv.is_at_least(12):
            allocation_requests = _build_allocation_requests_dict(providers, resources)
        else:
            allocation_requests = _build_allocation_requests_list(providers, resources)

        provider_uuids = [p["uuid"] for p in providers]
        provider_summaries = _build_provider_summaries(
            session, provider_uuids, resources, mv
        )

    response_data: dict[str, Any] = {
        "allocation_requests": allocation_requests,
        "provider_summaries": provider_summaries,
    }

    resp = flask.jsonify(response_data)
    if mv.is_at_least(15):
        resp.headers["cache-control"] = "no-cache"
        resp.headers["last-modified"] = _httpdate()

    return resp, 200
