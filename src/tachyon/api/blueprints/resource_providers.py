"""Resource Providers API blueprint.

Implements Placement-compatible CRUD operations for ResourceProvider nodes.
"""

from __future__ import annotations

import uuid as uuidlib

from flask import Blueprint, Response, jsonify, request

from tachyon.api.errors import (
    BadRequest,
    NotFound,
    ResourceProviderGenerationConflict,
    ResourceProviderInUse,
)

bp = Blueprint("resource_providers", __name__, url_prefix="/resource_providers")


def _driver():
    """Get the Neo4j driver from the Flask app."""
    from tachyon.api.app import get_driver

    return get_driver()


def _format_provider(
    rp: dict, root_uuid: str | None = None, parent_uuid: str | None = None
) -> dict:
    """Format a resource provider node for API response.

    Args:
        rp: Resource provider node properties.
        root_uuid: UUID of the root provider in the tree.
        parent_uuid: UUID of the immediate parent provider.

    Returns:
        Dict with Placement-compatible response format.
    """
    return {
        "uuid": rp.get("uuid"),
        "name": rp.get("name"),
        "generation": rp.get("generation", 0),
        "root_provider_uuid": root_uuid or rp.get("uuid"),
        "parent_provider_uuid": parent_uuid,
    }


@bp.route("", methods=["GET"])
def list_resource_providers() -> tuple[Response, int]:
    """List resource providers with optional filtering.

    Query Parameters:
        name: Filter by name (contains match).
        in_tree: Filter to providers in the tree rooted at this UUID.
        member_of: Filter to providers in specified aggregate(s).
        required: Filter to providers with all specified traits.
    """
    name = request.args.get("name")
    in_tree = request.args.get("in_tree")
    member_of = request.args.get("member_of")
    required = request.args.get("required")

    # Build dynamic Cypher query
    match_clause = "MATCH (rp:ResourceProvider)"
    where_clauses = []
    params: dict = {}

    if name:
        where_clauses.append("rp.name CONTAINS $name")
        params["name"] = name

    if in_tree:
        where_clauses.append(
            "EXISTS { MATCH (root:ResourceProvider {uuid: $in_tree})-[:PARENT_OF*0..]->(rp) }"
        )
        params["in_tree"] = in_tree

    if member_of:
        # member_of can be comma-separated list of aggregate UUIDs
        agg_uuids = [a.strip() for a in member_of.split(",")]
        where_clauses.append(
            "EXISTS { MATCH (rp)-[:MEMBER_OF]->(agg:Aggregate) WHERE agg.uuid IN $agg_uuids }"
        )
        params["agg_uuids"] = agg_uuids

    if required:
        # required is comma-separated list of trait names
        trait_names = [t.strip() for t in required.split(",")]
        where_clauses.append(
            "ALL(t IN $trait_names WHERE EXISTS { MATCH (rp)-[:HAS_TRAIT]->(:Trait {name: t}) })"
        )
        params["trait_names"] = trait_names

    # Construct full query
    where_str = " AND ".join(where_clauses) if where_clauses else "true"
    cypher = f"""
        {match_clause}
        WHERE {where_str}
        OPTIONAL MATCH (parent:ResourceProvider)-[:PARENT_OF]->(rp)
        OPTIONAL MATCH path = (root:ResourceProvider)-[:PARENT_OF*0..]->(rp)
        WHERE NOT EXISTS {{ MATCH (:ResourceProvider)-[:PARENT_OF]->(root) }}
        WITH rp, parent, root
        ORDER BY length(path) DESC
        WITH rp, parent, collect(root)[0] AS root_provider
        RETURN rp, parent.uuid AS parent_uuid, root_provider.uuid AS root_uuid
    """

    with _driver().session() as session:
        result = session.run(cypher, **params)
        providers = [
            _format_provider(
                dict(record["rp"]),
                root_uuid=record["root_uuid"],
                parent_uuid=record["parent_uuid"],
            )
            for record in result
        ]

    return jsonify({"resource_providers": providers}), 200


@bp.route("", methods=["POST"])
def create_resource_provider() -> tuple[Response, int]:
    """Create a new resource provider.

    Request Body:
        name: Required. Provider name (must be unique).
        uuid: Optional. Provider UUID (generated if not provided).
        parent_provider_uuid: Optional. UUID of parent provider.
    """
    data = request.get_json(force=True, silent=True) or {}
    name = data.get("name")
    parent_uuid = data.get("parent_provider_uuid")
    rp_uuid = data.get("uuid") or str(uuidlib.uuid4())

    if not name:
        raise BadRequest("'name' is a required field.")

    with _driver().session() as session:
        # Check if parent exists when specified
        if parent_uuid:
            parent_check = session.run(
                "MATCH (p:ResourceProvider {uuid: $uuid}) RETURN p",
                uuid=parent_uuid,
            ).single()
            if not parent_check:
                raise NotFound(f"Parent resource provider {parent_uuid} not found.")

        # Create the resource provider
        result = session.run(
            """
            OPTIONAL MATCH (parent:ResourceProvider {uuid: $parent_uuid})
            WITH parent
            WHERE $parent_uuid IS NULL OR parent IS NOT NULL
            CREATE (rp:ResourceProvider {
                uuid: $uuid,
                name: $name,
                generation: 0,
                created_at: datetime(),
                updated_at: datetime()
            })
            FOREACH (_ IN CASE WHEN parent IS NOT NULL THEN [1] ELSE [] END |
              CREATE (parent)-[:PARENT_OF]->(rp)
            )
            RETURN rp, parent.uuid AS parent_uuid
            """,
            uuid=rp_uuid,
            name=name,
            parent_uuid=parent_uuid,
        ).single()

        if not result:
            raise BadRequest("Failed to create resource provider.")

    return jsonify(
        _format_provider(
            {"uuid": rp_uuid, "name": name, "generation": 0},
            root_uuid=parent_uuid if parent_uuid else rp_uuid,
            parent_uuid=parent_uuid,
        )
    ), 200


@bp.route("/<string:uuid>", methods=["GET"])
def get_resource_provider(uuid: str) -> tuple[Response, int]:
    """Get a specific resource provider by UUID."""
    with _driver().session() as session:
        record = session.run(
            """
            MATCH (rp:ResourceProvider {uuid: $uuid})
            OPTIONAL MATCH (parent:ResourceProvider)-[:PARENT_OF]->(rp)
            OPTIONAL MATCH path = (root:ResourceProvider)-[:PARENT_OF*0..]->(rp)
            WHERE NOT EXISTS { MATCH (:ResourceProvider)-[:PARENT_OF]->(root) }
            WITH rp, parent, root
            ORDER BY length(path) DESC
            WITH rp, parent, collect(root)[0] AS root_provider
            RETURN rp, parent.uuid AS parent_uuid, root_provider.uuid AS root_uuid
            """,
            uuid=uuid,
        ).single()

        if not record:
            raise NotFound(f"Resource provider {uuid} not found.")

    return jsonify(
        _format_provider(
            dict(record["rp"]),
            root_uuid=record["root_uuid"],
            parent_uuid=record["parent_uuid"],
        )
    ), 200


@bp.route("/<string:uuid>", methods=["PUT"])
def update_resource_provider(uuid: str) -> tuple[Response, int]:
    """Update a resource provider.

    Request Body:
        name: Optional. New provider name.
        generation: Required. Current generation for optimistic concurrency.
        parent_provider_uuid: Optional. New parent UUID (re-parenting).
    """
    data = request.get_json(force=True, silent=True) or {}
    name = data.get("name")
    generation = data.get("generation")

    if generation is None:
        raise BadRequest("'generation' is a required field for updates.")

    with _driver().session() as session:
        result = session.run(
            """
            MATCH (rp:ResourceProvider {uuid: $uuid})
            WHERE rp.generation = $generation
            SET rp.name = COALESCE($name, rp.name),
                rp.generation = rp.generation + 1,
                rp.updated_at = datetime()
            WITH rp
            OPTIONAL MATCH (parent:ResourceProvider)-[:PARENT_OF]->(rp)
            OPTIONAL MATCH path = (root:ResourceProvider)-[:PARENT_OF*0..]->(rp)
            WHERE NOT EXISTS { MATCH (:ResourceProvider)-[:PARENT_OF]->(root) }
            WITH rp, parent, root
            ORDER BY length(path) DESC
            WITH rp, parent, collect(root)[0] AS root_provider
            RETURN rp, parent.uuid AS parent_uuid, root_provider.uuid AS root_uuid
            """,
            uuid=uuid,
            generation=generation,
            name=name,
        ).single()

        if not result:
            # Check if provider exists to differentiate 404 vs 409
            exists = session.run(
                "MATCH (rp:ResourceProvider {uuid: $uuid}) RETURN rp",
                uuid=uuid,
            ).single()
            if not exists:
                raise NotFound(f"Resource provider {uuid} not found.")
            raise ResourceProviderGenerationConflict(
                f"Generation mismatch for resource provider {uuid}."
            )

    return jsonify(
        _format_provider(
            dict(result["rp"]),
            root_uuid=result["root_uuid"],
            parent_uuid=result["parent_uuid"],
        )
    ), 200


@bp.route("/<string:uuid>", methods=["DELETE"])
def delete_resource_provider(uuid: str) -> Response:
    """Delete a resource provider.

    Will fail if the provider has allocations or child providers.
    """
    with _driver().session() as session:
        # Check if provider exists
        exists = session.run(
            "MATCH (rp:ResourceProvider {uuid: $uuid}) RETURN rp",
            uuid=uuid,
        ).single()
        if not exists:
            raise NotFound(f"Resource provider {uuid} not found.")

        # Check for child providers
        has_children = session.run(
            "MATCH (rp:ResourceProvider {uuid: $uuid})-[:PARENT_OF]->() RETURN count(*) as cnt",
            uuid=uuid,
        ).single()
        if has_children and has_children["cnt"] > 0:
            raise ResourceProviderInUse(
                f"Resource provider {uuid} has child providers."
            )

        # Check for allocations
        has_allocations = session.run(
            """
            MATCH (rp:ResourceProvider {uuid: $uuid})-[:HAS_INVENTORY]->(inv)<-[:CONSUMES]-()
            RETURN count(*) as cnt
            """,
            uuid=uuid,
        ).single()
        if has_allocations and has_allocations["cnt"] > 0:
            raise ResourceProviderInUse(
                f"Resource provider {uuid} has active allocations."
            )

        # Safe to delete
        session.run(
            "MATCH (rp:ResourceProvider {uuid: $uuid}) DETACH DELETE rp",
            uuid=uuid,
        )

    return Response(status=204)
