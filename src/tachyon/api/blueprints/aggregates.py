# SPDX-License-Identifier: Apache-2.0

"""Aggregates API blueprint.

Implements Placement-compatible aggregate management for resource providers.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

import flask
from oslo_log import log

from tachyon.api import errors, microversion

LOG = log.getLogger(__name__)

bp = flask.Blueprint(
    "aggregates", __name__, url_prefix="/resource_providers/<string:rp_uuid>/aggregates"
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


def _check_provider_exists(session: Any, rp_uuid: str) -> dict[str, Any]:
    """Check if a resource provider exists.

    :param session: Neo4j session
    :param rp_uuid: Provider UUID
    :returns: Provider node dict
    :raises errors.NotFound: If provider doesn't exist
    """
    result = session.run(
        "MATCH (rp:ResourceProvider {uuid: $uuid}) RETURN rp",
        uuid=rp_uuid,
    ).single()
    if not result:
        raise errors.NotFound("No resource provider with uuid %s found" % rp_uuid)
    return dict(result["rp"])


def _validate_uuid(value: str) -> str:
    """Validate and normalize a UUID string.

    :param value: UUID string to validate
    :returns: Normalized UUID string
    :raises errors.BadRequest: If UUID is invalid
    """
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise errors.BadRequest("'%s' is not a 'uuid'" % value)


@bp.route("", methods=["GET"])
def get_aggregates(rp_uuid: str) -> tuple[flask.Response, int]:
    """Get aggregates for a resource provider.

    Returns list of aggregate UUIDs the provider is a member of.

    :param rp_uuid: Resource provider UUID
    :returns: Tuple of (response, status_code)
    """
    mv = _mv()

    # Aggregates API requires microversion >= 1.1
    if not mv.is_at_least(1):
        raise errors.NotFound("The resource could not be found.")

    with _driver().session() as session:
        provider = _check_provider_exists(session, rp_uuid)

        result = session.run(
            """
            MATCH (rp:ResourceProvider {uuid: $uuid})
            OPTIONAL MATCH (rp)-[:MEMBER_OF]->(agg:Aggregate)
            RETURN collect(agg.uuid) AS aggregates
            """,
            uuid=rp_uuid,
        ).single()

        aggregates = result["aggregates"] if result else []

    response: dict[str, Any] = {
        "aggregates": aggregates,
        "resource_provider_generation": provider.get("generation", 0),
    }

    resp = flask.jsonify(response)
    if mv.is_at_least(15):
        resp.headers["cache-control"] = "no-cache"
        resp.headers["last-modified"] = _httpdate()

    return resp, 200


@bp.route("", methods=["PUT"])
def put_aggregates(rp_uuid: str) -> tuple[flask.Response, int]:
    """Set aggregates for a resource provider.

    Request Body (1.19+):
        resource_provider_generation: Required. Current generation.
        aggregates: List of aggregate UUIDs.

    Request Body (1.1-1.18):
        List of aggregate UUIDs directly.

    :param rp_uuid: Resource provider UUID
    :returns: Tuple of (response, status_code)
    """
    mv = _mv()

    # Aggregates API requires microversion >= 1.1
    if not mv.is_at_least(1):
        raise errors.NotFound("The resource could not be found.")

    try:
        data = flask.request.get_json(force=True, silent=False)
    except Exception as exc:
        raise errors.BadRequest("Malformed JSON: %s" % exc)

    generation: int | None
    aggregates: list[Any]

    # Parse based on microversion
    if mv.is_at_least(19):
        # New format: {"aggregates": [...], "resource_provider_generation": N}
        if not isinstance(data, dict):
            raise errors.BadRequest("JSON does not validate")
        if "resource_provider_generation" not in data:
            raise errors.BadRequest("JSON does not validate")
        if "aggregates" not in data:
            raise errors.BadRequest("JSON does not validate")

        generation = data.get("resource_provider_generation")
        aggregates = data.get("aggregates", [])
    else:
        # Old format: [...] (list of UUIDs directly)
        if isinstance(data, dict):
            # If dict provided on old microversion, it's invalid
            raise errors.BadRequest("JSON does not validate")
        if not isinstance(data, list):
            raise errors.BadRequest("JSON does not validate")

        generation = None  # Generation not used in old format
        aggregates = data

    # Validate aggregates are UUIDs
    validated_aggregates: list[str] = []
    for agg in aggregates:
        validated_aggregates.append(_validate_uuid(agg))

    # Check for duplicates
    if len(validated_aggregates) != len(set(validated_aggregates)):
        raise errors.BadRequest("Aggregates list has non-unique elements")

    with _driver().session() as session:
        provider = _check_provider_exists(session, rp_uuid)
        current_generation = provider.get("generation", 0)

        # Check generation (only for new format 1.19+)
        if mv.is_at_least(19) and generation != current_generation:
            raise errors.Conflict(
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
                uuid=rp_uuid,
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
                    uuid=rp_uuid,
                    agg_uuid=agg_uuid,
                )

            # Increment generation (only for new format 1.19+)
            new_generation: int
            if mv.is_at_least(19):
                updated = tx.run(
                    """
                    MATCH (rp:ResourceProvider {uuid: $uuid})
                    SET rp.generation = rp.generation + 1,
                        rp.updated_at = datetime()
                    RETURN rp.generation AS generation
                    """,
                    uuid=rp_uuid,
                ).single()
                new_generation = updated["generation"]
            else:
                new_generation = current_generation

            tx.commit()
        except (ValueError, TypeError, RuntimeError):
            tx.rollback()
            raise

    response = {
        "aggregates": validated_aggregates,
        "resource_provider_generation": new_generation,
    }

    resp = flask.jsonify(response)
    if mv.is_at_least(15):
        resp.headers["cache-control"] = "no-cache"
        resp.headers["last-modified"] = _httpdate()

    return resp, 200
