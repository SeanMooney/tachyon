"""Aggregates API blueprint.

Implements Placement-compatible aggregate management for resource providers.
"""

from __future__ import annotations

import uuid as uuidlib
from datetime import datetime, timezone

from flask import Blueprint, Response, g, jsonify, request

from tachyon.api.errors import BadRequest, Conflict, NotFound
from tachyon.api.microversion import Microversion

bp = Blueprint(
    "aggregates", __name__, url_prefix="/resource_providers/<string:uuid>/aggregates"
)


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


def _check_provider_exists(session, uuid: str) -> dict:
    """Check if a resource provider exists.

    Args:
        session: Neo4j session.
        uuid: Provider UUID.

    Returns:
        Provider node dict.

    Raises:
        NotFound: If provider doesn't exist.
    """
    result = session.run(
        "MATCH (rp:ResourceProvider {uuid: $uuid}) RETURN rp",
        uuid=uuid,
    ).single()
    if not result:
        raise NotFound(f"No resource provider with uuid {uuid} found")
    return dict(result["rp"])


def _validate_uuid(value: str) -> str:
    """Validate and normalize a UUID string."""
    try:
        return str(uuidlib.UUID(value))
    except Exception:
        raise BadRequest(f"'{value}' is not a 'uuid'")


@bp.route("", methods=["GET"])
def get_aggregates(uuid: str) -> tuple[Response, int]:
    """Get aggregates for a resource provider.

    Returns list of aggregate UUIDs the provider is a member of.
    """
    mv = _mv()

    # Aggregates API requires microversion >= 1.1
    if not mv.is_at_least(1):
        raise NotFound("The resource could not be found.")

    with _driver().session() as session:
        provider = _check_provider_exists(session, uuid)

        result = session.run(
            """
            MATCH (rp:ResourceProvider {uuid: $uuid})
            OPTIONAL MATCH (rp)-[:MEMBER_OF]->(agg:Aggregate)
            RETURN collect(agg.uuid) AS aggregates
            """,
            uuid=uuid,
        ).single()

        aggregates = result["aggregates"] if result else []

    response = {
        "aggregates": aggregates,
        "resource_provider_generation": provider.get("generation", 0),
    }

    resp = jsonify(response)
    if mv.is_at_least(15):
        resp.headers["cache-control"] = "no-cache"
        resp.headers["last-modified"] = _httpdate()

    return resp, 200


@bp.route("", methods=["PUT"])
def put_aggregates(uuid: str) -> tuple[Response, int]:
    """Set aggregates for a resource provider.

    Request Body (1.19+):
        resource_provider_generation: Required. Current generation for concurrency.
        aggregates: List of aggregate UUIDs.

    Request Body (1.1-1.18):
        List of aggregate UUIDs directly.
    """
    mv = _mv()

    # Aggregates API requires microversion >= 1.1
    if not mv.is_at_least(1):
        raise NotFound("The resource could not be found.")

    try:
        data = request.get_json(force=True, silent=False)
    except Exception as exc:
        raise BadRequest(f"Malformed JSON: {exc}")

    # Parse based on microversion
    if mv.is_at_least(19):
        # New format: {"aggregates": [...], "resource_provider_generation": N}
        if not isinstance(data, dict):
            raise BadRequest("JSON does not validate")
        if "resource_provider_generation" not in data:
            raise BadRequest("JSON does not validate")
        if "aggregates" not in data:
            raise BadRequest("JSON does not validate")

        generation = data.get("resource_provider_generation")
        aggregates = data.get("aggregates", [])
    else:
        # Old format: [...] (list of UUIDs directly)
        if isinstance(data, dict):
            # If dict provided on old microversion, it's invalid
            raise BadRequest("JSON does not validate")
        if not isinstance(data, list):
            raise BadRequest("JSON does not validate")

        generation = None  # Generation not used in old format
        aggregates = data

    # Validate aggregates are UUIDs
    validated_aggregates = []
    for agg in aggregates:
        validated_aggregates.append(_validate_uuid(agg))

    # Check for duplicates
    if len(validated_aggregates) != len(set(validated_aggregates)):
        raise BadRequest("Aggregates list has non-unique elements")

    with _driver().session() as session:
        provider = _check_provider_exists(session, uuid)
        current_generation = provider.get("generation", 0)

        # Check generation (only for new format 1.19+)
        if mv.is_at_least(19) and generation != current_generation:
            raise Conflict(
                "resource provider generation conflict",
                code="placement.concurrent_update",
            )

        tx = session.begin_transaction()
        try:
            # Delete existing aggregate memberships
            tx.run(
                """
                MATCH (rp:ResourceProvider {uuid: $uuid})-[rel:MEMBER_OF]->()
                DELETE rel
                """,
                uuid=uuid,
            )

            # Create new aggregate memberships
            for agg_uuid in validated_aggregates:
                tx.run(
                    """
                    MATCH (rp:ResourceProvider {uuid: $uuid})
                    MERGE (agg:Aggregate {uuid: $agg_uuid})
                    ON CREATE SET agg.created_at = datetime()
                    CREATE (rp)-[:MEMBER_OF]->(agg)
                    """,
                    uuid=uuid,
                    agg_uuid=agg_uuid,
                )

            # Increment generation (only for new format 1.19+)
            if mv.is_at_least(19):
                updated = tx.run(
                    """
                    MATCH (rp:ResourceProvider {uuid: $uuid})
                    SET rp.generation = rp.generation + 1,
                        rp.updated_at = datetime()
                    RETURN rp.generation AS generation
                    """,
                    uuid=uuid,
                ).single()
                new_generation = updated["generation"]
            else:
                new_generation = current_generation

            tx.commit()
        except Exception:
            tx.rollback()
            raise

    response = {
        "aggregates": validated_aggregates,
        "resource_provider_generation": new_generation,
    }

    resp = jsonify(response)
    if mv.is_at_least(15):
        resp.headers["cache-control"] = "no-cache"
        resp.headers["last-modified"] = _httpdate()

    return resp, 200

