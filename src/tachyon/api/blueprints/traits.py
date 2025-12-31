# SPDX-License-Identifier: Apache-2.0

"""Traits API blueprint.

Implements Placement-compatible trait management.
"""

from __future__ import annotations

import flask

from tachyon.api import errors

bp = flask.Blueprint("traits", __name__, url_prefix="/traits")
# Expose provider-traits endpoints on the Placement-compatible path
# /resource_providers/<uuid>/traits as well as under /traits/resource_providers.
provider_traits_bp = flask.Blueprint(
    "provider_traits",
    __name__,
    url_prefix="/resource_providers/<string:rp_uuid>/traits"
)


def _driver():
    """Get the Neo4j driver from the Flask app.

    :returns: Neo4j driver instance
    """
    from tachyon.api import app
    return app.get_driver()


@bp.route("", methods=["GET"])
def list_traits():
    """List all traits.

    Query Parameters:
        name: Filter by name prefix (optional).
        associated: If 'true', only return traits associated with providers.

    :returns: Tuple of (response, status_code)
    """
    name_filter = flask.request.args.get("name")
    associated = flask.request.args.get("associated", "").lower() == "true"

    if associated:
        cypher = """
            MATCH (:ResourceProvider)-[:HAS_TRAIT]->(t:Trait)
            WHERE ($name IS NULL OR t.name STARTS WITH $name)
            RETURN DISTINCT t.name AS name ORDER BY name
        """
    else:
        cypher = """
            MATCH (t:Trait)
            WHERE ($name IS NULL OR t.name STARTS WITH $name)
            RETURN t.name AS name ORDER BY name
        """

    with _driver().session() as session:
        rows = session.run(cypher, name=name_filter)
        names = [r["name"] for r in rows]

    return flask.jsonify({"traits": names}), 200


@bp.route("/<string:name>", methods=["PUT"])
def create_trait(name):
    """Create a trait.

    Custom traits must start with 'CUSTOM_'.

    :param name: Trait name
    :returns: Response with status 204
    """
    # Validate trait name format
    if not name.startswith("CUSTOM_") and not name.isupper():
        raise errors.BadRequest(
            "Trait name '%s' must be uppercase. "
            "Custom traits must start with 'CUSTOM_'." % name
        )

    with _driver().session() as session:
        session.run(
            """
            MERGE (t:Trait {name: $name})
            ON CREATE SET t.created_at = datetime(), t.updated_at = datetime()
            ON MATCH SET t.updated_at = datetime()
            """,
            name=name,
        )

    return flask.Response(status=204)


@bp.route("/<string:name>", methods=["GET"])
def get_trait(name):
    """Get a specific trait.

    :param name: Trait name
    :returns: Tuple of (response, status_code)
    """
    with _driver().session() as session:
        res = session.run(
            "MATCH (t:Trait {name: $name}) RETURN t", name=name
        ).single()

        if not res:
            raise errors.NotFound("Trait %s not found." % name)

    return flask.jsonify({"name": name}), 200


@bp.route("/<string:name>", methods=["DELETE"])
def delete_trait(name):
    """Delete a trait.

    Will fail if trait is associated with any resource providers.

    :param name: Trait name
    :returns: Response with status 204
    """
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
                "resource provider(s) and cannot be deleted."
                % (name, in_use["cnt"])
            )

        session.run("MATCH (t:Trait {name: $name}) DELETE t", name=name)

    return flask.Response(status=204)


# Provider traits endpoints (separate URL pattern)
@bp.route(
    "/resource_providers/<string:rp_uuid>/traits",
    methods=["GET"],
    endpoint="get_provider_traits_via_traits",
)
def get_provider_traits(rp_uuid):
    """Get traits for a resource provider.

    :param rp_uuid: Resource provider UUID
    :returns: Tuple of (response, status_code)
    """
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
            raise errors.NotFound(
                "Resource provider %s not found." % rp_uuid
            )

    return flask.jsonify({
        "resource_provider_generation": res["generation"],
        "traits": sorted(res["traits"]),
    }), 200


@bp.route(
    "/resource_providers/<string:rp_uuid>/traits",
    methods=["PUT"],
    endpoint="put_provider_traits_via_traits",
)
def put_provider_traits(rp_uuid):
    """Set traits for a resource provider.

    Request Body:
        resource_provider_generation: Required. Current generation.
        traits: List of trait names to set.

    :param rp_uuid: Resource provider UUID
    :returns: Tuple of (response, status_code)
    """
    data = flask.request.get_json(force=True, silent=True) or {}
    generation = data.get("resource_provider_generation")
    traits = data.get("traits", [])

    if generation is None:
        raise errors.BadRequest(
            "'resource_provider_generation' is a required field."
        )

    with _driver().session() as session:
        # Check provider exists and generation matches
        provider = session.run(
            "MATCH (rp:ResourceProvider {uuid: $uuid}) RETURN rp",
            uuid=rp_uuid,
        ).single()

        if not provider:
            raise errors.NotFound(
                "Resource provider %s not found." % rp_uuid
            )

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

    return flask.jsonify({
        "resource_provider_generation": result["generation"],
        "traits": sorted(traits),
    }), 200


@bp.route(
    "/resource_providers/<string:rp_uuid>/traits",
    methods=["DELETE"],
    endpoint="delete_provider_traits_via_traits",
)
def delete_provider_traits(rp_uuid):
    """Delete all traits from a resource provider.

    :param rp_uuid: Resource provider UUID
    :returns: Response with status 204
    """
    with _driver().session() as session:
        provider = session.run(
            "MATCH (rp:ResourceProvider {uuid: $uuid}) RETURN rp",
            uuid=rp_uuid,
        ).single()

        if not provider:
            raise errors.NotFound(
                "Resource provider %s not found." % rp_uuid
            )

        session.run(
            """
            MATCH (rp:ResourceProvider {uuid: $uuid})-[rel:HAS_TRAIT]->()
            DELETE rel
            """,
            uuid=rp_uuid,
        )

    return flask.Response(status=204)


# Register provider trait handlers on the placement-standard path
provider_traits_bp.add_url_rule(
    "", view_func=get_provider_traits, methods=["GET"]
)
provider_traits_bp.add_url_rule(
    "", view_func=put_provider_traits, methods=["PUT"]
)
provider_traits_bp.add_url_rule(
    "", view_func=delete_provider_traits, methods=["DELETE"]
)
