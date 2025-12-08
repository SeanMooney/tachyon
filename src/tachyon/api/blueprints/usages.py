"""Usages API blueprint.

Implements Placement-compatible usage reporting.
"""

from __future__ import annotations

from flask import Blueprint, Response, jsonify, request

from tachyon.api.errors import BadRequest, NotFound

bp = Blueprint("usages", __name__)


def _driver():
    """Get the Neo4j driver from the Flask app."""
    from tachyon.api.app import get_driver

    return get_driver()


@bp.route("/resource_providers/<string:uuid>/usages", methods=["GET"])
def provider_usages(uuid: str) -> tuple[Response, int]:
    """Get resource usages for a resource provider.

    Returns the sum of allocations against each resource class
    on the specified provider.
    """
    with _driver().session() as session:
        # Check provider exists
        provider = session.run(
            "MATCH (rp:ResourceProvider {uuid: $uuid}) RETURN rp",
            uuid=uuid,
        ).single()

        if not provider:
            raise NotFound(f"Resource provider {uuid} not found.")

        rows = session.run(
            """
            MATCH (rp:ResourceProvider {uuid: $uuid})
                  -[:HAS_INVENTORY]->(inv)
                  -[:OF_CLASS]->(rc:ResourceClass)
            OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
            RETURN rc.name AS rc, COALESCE(sum(alloc.used), 0) AS used
            """,
            uuid=uuid,
        )
        usages = {row["rc"]: int(row["used"]) for row in rows}

    return jsonify(
        {
            "resource_provider_generation": provider["rp"].get("generation", 0),
            "usages": usages,
        }
    ), 200


@bp.route("/usages", methods=["GET"])
def project_usages() -> tuple[Response, int]:
    """Get resource usages for a project.

    Query Parameters:
        project_id: Required. Project ID to get usages for.

    Returns the sum of allocations for all consumers owned by the project.
    """
    project_id = request.args.get("project_id")

    if not project_id:
        raise BadRequest("'project_id' is a required query parameter.")

    with _driver().session() as session:
        rows = session.run(
            """
            MATCH (c:Consumer)-[:OWNED_BY]->(proj:Project {external_id: $project_id})
            MATCH (c)-[alloc:CONSUMES]->(inv)-[:OF_CLASS]->(rc:ResourceClass)
            RETURN rc.name AS rc, COALESCE(sum(alloc.used), 0) AS used
            """,
            project_id=project_id,
        )
        usages = {row["rc"]: int(row["used"]) for row in rows}

    return jsonify({"usages": usages}), 200
