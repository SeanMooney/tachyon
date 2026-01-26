# SPDX-License-Identifier: Apache-2.0

"""Traits API blueprint.

Implements Placement-compatible trait management.
"""

from __future__ import annotations

import datetime
import re
from typing import Any

import flask

from oslo_log import log

from tachyon.api import errors
from tachyon.api import microversion
from tachyon.policies import trait as trait_policies

LOG = log.getLogger(__name__)

bp = flask.Blueprint("traits", __name__, url_prefix="/traits")
# Expose provider-traits endpoints on the Placement-compatible path
# /resource_providers/<uuid>/traits as well as under /traits/resource_providers.
provider_traits_bp = flask.Blueprint(
    "provider_traits",
    __name__,
    url_prefix="/resource_providers/<string:rp_uuid>/traits",
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


def _normalize_traits_qs_param(qs: str) -> dict[str, Any]:
    """Parse the name query parameter for trait filtering.

    Supports formats:
        name=in:TRAIT1,TRAIT2,... - Match any of the listed traits
        name=startswith:PREFIX - Match traits starting with PREFIX

    :param qs: Query string value
    :returns: Dict with either 'name_in' or 'prefix' key
    :raises errors.BadRequest: If format is invalid
    """
    try:
        op, value = qs.split(":", 1)
    except ValueError:
        raise errors.BadRequest(
            "Badly formatted name parameter. Expected name query string "
            "parameter in form: "
            "?name=[in|startswith]:[name1,name2|prefix]. Got: \"%s\"" % qs
        )

    filters: dict[str, Any] = {}
    if op == "in":
        filters["name_in"] = value.split(",")
    elif op == "startswith":
        filters["prefix"] = value
    else:
        raise errors.BadRequest(
            "Badly formatted name parameter. Expected name query string "
            "parameter in form: "
            "?name=[in|startswith]:[name1,name2|prefix]. Got: \"%s\"" % qs
        )

    return filters


@bp.route("", methods=["GET"])
def list_traits() -> tuple[flask.Response, int]:
    """List all traits.

    Query Parameters:
        name: Filter by name. Supports formats:
            - name=in:TRAIT1,TRAIT2 - Match any of the listed traits
            - name=startswith:PREFIX - Match traits starting with PREFIX
        associated: If 'true', only return traits associated with providers.

    :returns: Tuple of (response, status_code)
    """
    flask.g.context.can(trait_policies.LIST)
    mv = _mv()
    name_filter = flask.request.args.get("name")
    associated_param = flask.request.args.get("associated")

    # Validate associated parameter if provided
    if associated_param is not None:
        if associated_param.lower() not in ("true", "false"):
            raise errors.BadRequest(
                'The query parameter "associated" only accepts '
                '"true" or "false"'
            )
        associated = associated_param.lower() == "true"
    else:
        associated = False

    # Parse name filter
    name_in: list[str] | None = None
    prefix: str | None = None

    if name_filter:
        filters = _normalize_traits_qs_param(name_filter)
        name_in = filters.get("name_in")
        prefix = filters.get("prefix")

    # Build query based on filters
    with _driver().session() as session:
        if associated:
            if name_in:
                cypher = """
                    MATCH (:ResourceProvider)-[:HAS_TRAIT]->(t:Trait)
                    WHERE t.name IN $names
                    RETURN DISTINCT t.name AS name ORDER BY name
                """
                rows = session.run(cypher, names=name_in)
            elif prefix:
                cypher = """
                    MATCH (:ResourceProvider)-[:HAS_TRAIT]->(t:Trait)
                    WHERE t.name STARTS WITH $prefix
                    RETURN DISTINCT t.name AS name ORDER BY name
                """
                rows = session.run(cypher, prefix=prefix)
            else:
                cypher = """
                    MATCH (:ResourceProvider)-[:HAS_TRAIT]->(t:Trait)
                    RETURN DISTINCT t.name AS name ORDER BY name
                """
                rows = session.run(cypher)
        else:
            if name_in:
                cypher = """
                    MATCH (t:Trait)
                    WHERE t.name IN $names
                    RETURN t.name AS name ORDER BY name
                """
                rows = session.run(cypher, names=name_in)
            elif prefix:
                cypher = """
                    MATCH (t:Trait)
                    WHERE t.name STARTS WITH $prefix
                    RETURN t.name AS name ORDER BY name
                """
                rows = session.run(cypher, prefix=prefix)
            else:
                cypher = """
                    MATCH (t:Trait)
                    RETURN t.name AS name ORDER BY name
                """
                rows = session.run(cypher)

        names = [r["name"] for r in rows]

    resp = flask.jsonify({"traits": names})
    if mv.is_at_least(15):
        resp.headers["cache-control"] = "no-cache"
        resp.headers["last-modified"] = _httpdate()
    return resp, 200


@bp.route("/<string:name>", methods=["PUT"])
def create_trait(name: str) -> flask.Response:
    """Create or verify existence of a trait.

    Custom traits must start with 'CUSTOM_' and be all uppercase,
    max 255 characters, containing only A-Z, 0-9, and _.

    Returns:
        201 if newly created
        204 if already exists

    :param name: Trait name
    :returns: Response with status 201 or 204
    """
    flask.g.context.can(trait_policies.UPDATE)
    mv = _mv()

    # Validate trait name format - must start with CUSTOM_ and be valid format
    if not re.match(r"^CUSTOM_[A-Z0-9_]+$", name):
        raise errors.BadRequest(
            "The trait is invalid. A valid trait must be no longer than "
            '255 characters, start with the prefix "CUSTOM_" and use '
            'following characters: "A"-"Z", "0"-"9" and "_"'
        )

    if len(name) > 255:
        raise errors.BadRequest(
            "The trait is invalid. A valid trait must be no longer than "
            '255 characters, start with the prefix "CUSTOM_" and use '
            'following characters: "A"-"Z", "0"-"9" and "_"'
        )

    with _driver().session() as session:
        # Check if trait already exists
        existing = session.run(
            "MATCH (t:Trait {name: $name}) RETURN t", name=name
        ).single()

        if existing:
            status = 204
        else:
            session.run(
                """
                CREATE (t:Trait {name: $name, created_at: datetime(), updated_at: datetime()})
                """,
                name=name,
            )
            status = 201

    resp = flask.Response(status=status)
    resp.headers.pop("Content-Type", None)
    resp.headers["Location"] = "/traits/%s" % name
    if mv.is_at_least(15):
        resp.headers["last-modified"] = _httpdate()
        resp.headers["cache-control"] = "no-cache"
    return resp


@bp.route("/<string:name>", methods=["GET"])
def get_trait(name: str) -> flask.Response:
    """Get a specific trait.

    Returns 204 with empty body if trait exists, 404 if not found.
    This matches Placement API behavior.

    :param name: Trait name
    :returns: Response with status 204
    """
    flask.g.context.can(trait_policies.SHOW)
    mv = _mv()

    with _driver().session() as session:
        res = session.run("MATCH (t:Trait {name: $name}) RETURN t", name=name).single()

        if not res:
            raise errors.NotFound("No such trait(s): %s" % name)

    resp = flask.Response(status=204)
    resp.headers.pop("Content-Type", None)
    if mv.is_at_least(15):
        resp.headers["last-modified"] = _httpdate()
        resp.headers["cache-control"] = "no-cache"
    return resp


@bp.route("/<string:name>", methods=["DELETE"])
def delete_trait(name: str) -> flask.Response:
    """Delete a trait.

    Will fail if trait is associated with any resource providers.

    :param name: Trait name
    :returns: Response with status 204
    """
    flask.g.context.can(trait_policies.DELETE)
    with _driver().session() as session:
        # Check if trait exists
        exists = session.run(
            "MATCH (t:Trait {name: $name}) RETURN t", name=name
        ).single()

        if not exists:
            raise errors.NotFound("Trait %s not found." % name)

        # Check if in use
        in_use = session.run(
            """
            MATCH (:ResourceProvider)-[:HAS_TRAIT]->(t:Trait {name: $name})
            RETURN count(*) AS cnt
            """,
            name=name,
        ).single()

        if in_use and in_use["cnt"] > 0:
            raise errors.Conflict(
                "Trait %s is associated with %d "
                "resource provider(s) and cannot be deleted." % (name, in_use["cnt"])
            )

        session.run("MATCH (t:Trait {name: $name}) DELETE t", name=name)

    return flask.Response(status=204)


# Provider traits endpoints (separate URL pattern)
@bp.route(
    "/resource_providers/<string:rp_uuid>/traits",
    methods=["GET"],
    endpoint="get_provider_traits_via_traits",
)
def get_provider_traits(rp_uuid: str) -> tuple[flask.Response, int]:
    """Get traits for a resource provider.

    :param rp_uuid: Resource provider UUID
    :returns: Tuple of (response, status_code)
    """
    flask.g.context.can(trait_policies.RP_TRAIT_LIST)
    with _driver().session() as session:
        res = session.run(
            """
            MATCH (rp:ResourceProvider {uuid: $uuid})
            OPTIONAL MATCH (rp)-[:HAS_TRAIT]->(t:Trait)
            RETURN rp.generation AS generation, collect(t.name) AS traits
            """,
            uuid=rp_uuid,
        ).single()

        if not res or res["generation"] is None:
            raise errors.NotFound("Resource provider %s not found." % rp_uuid)

    return flask.jsonify(
        {
            "resource_provider_generation": res["generation"],
            "traits": sorted(res["traits"]),
        }
    ), 200


@bp.route(
    "/resource_providers/<string:rp_uuid>/traits",
    methods=["PUT"],
    endpoint="put_provider_traits_via_traits",
)
def put_provider_traits(rp_uuid: str) -> tuple[flask.Response, int]:
    """Set traits for a resource provider.

    Request Body:
        resource_provider_generation: Required. Current generation.
        traits: List of trait names to set.

    :param rp_uuid: Resource provider UUID
    :returns: Tuple of (response, status_code)
    """
    flask.g.context.can(trait_policies.RP_TRAIT_UPDATE)
    data = flask.request.get_json(force=True, silent=True) or {}
    generation = data.get("resource_provider_generation")
    traits: list[str] = data.get("traits", [])

    if generation is None:
        raise errors.BadRequest("'resource_provider_generation' is a required field.")

    with _driver().session() as session:
        # Check provider exists and generation matches
        provider = session.run(
            "MATCH (rp:ResourceProvider {uuid: $uuid}) RETURN rp",
            uuid=rp_uuid,
        ).single()

        if not provider:
            raise errors.NotFound("Resource provider %s not found." % rp_uuid)

        if provider["rp"].get("generation", 0) != generation:
            raise errors.ResourceProviderGenerationConflict(
                "Generation mismatch for resource provider %s." % rp_uuid
            )

        tx = session.begin_transaction()
        try:
            # Delete existing trait relationships
            tx.run(
                """
                MATCH (rp:ResourceProvider {uuid: $uuid})-[rel:HAS_TRAIT]->()
                DELETE rel
                """,
                uuid=rp_uuid,
            )

            # Create new trait relationships
            if traits:
                tx.run(
                    """
                    MATCH (rp:ResourceProvider {uuid: $uuid})
                    UNWIND $traits AS trait_name
                    MERGE (t:Trait {name: trait_name})
                    ON CREATE SET t.created_at = datetime()
                    CREATE (rp)-[:HAS_TRAIT]->(t)
                    """,
                    uuid=rp_uuid,
                    traits=traits,
                )

            # Increment generation
            result = tx.run(
                """
                MATCH (rp:ResourceProvider {uuid: $uuid})
                SET rp.generation = rp.generation + 1,
                    rp.updated_at = datetime()
                RETURN rp.generation AS generation
                """,
                uuid=rp_uuid,
            ).single()

            tx.commit()
        except (ValueError, TypeError, RuntimeError):
            tx.rollback()
            raise

    return flask.jsonify(
        {
            "resource_provider_generation": result["generation"],
            "traits": sorted(traits),
        }
    ), 200


@bp.route(
    "/resource_providers/<string:rp_uuid>/traits",
    methods=["DELETE"],
    endpoint="delete_provider_traits_via_traits",
)
def delete_provider_traits(rp_uuid: str) -> flask.Response:
    """Delete all traits from a resource provider.

    :param rp_uuid: Resource provider UUID
    :returns: Response with status 204
    """
    flask.g.context.can(trait_policies.RP_TRAIT_DELETE)
    with _driver().session() as session:
        provider = session.run(
            "MATCH (rp:ResourceProvider {uuid: $uuid}) RETURN rp",
            uuid=rp_uuid,
        ).single()

        if not provider:
            raise errors.NotFound("Resource provider %s not found." % rp_uuid)

        session.run(
            """
            MATCH (rp:ResourceProvider {uuid: $uuid})-[rel:HAS_TRAIT]->()
            DELETE rel
            """,
            uuid=rp_uuid,
        )

    return flask.Response(status=204)


# Register provider trait handlers on the placement-standard path
provider_traits_bp.add_url_rule("", view_func=get_provider_traits, methods=["GET"])
provider_traits_bp.add_url_rule("", view_func=put_provider_traits, methods=["PUT"])
provider_traits_bp.add_url_rule(
    "", view_func=delete_provider_traits, methods=["DELETE"]
)
