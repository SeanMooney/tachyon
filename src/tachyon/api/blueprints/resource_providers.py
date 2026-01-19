# SPDX-License-Identifier: Apache-2.0

"""Resource Providers API blueprint.

Implements Placement-compatible CRUD operations for ResourceProvider nodes.
"""

from __future__ import annotations

import datetime
from typing import Any
from typing import NoReturn
import uuid as uuid_module

import flask

from oslo_log import log

from tachyon.api import errors
from tachyon.api import microversion

LOG = log.getLogger(__name__)

bp = flask.Blueprint("resource_providers", __name__, url_prefix="/resource_providers")


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


def _abs_url(path: str) -> str:
    """Build absolute URL for Location headers.

    :param path: URL path
    :returns: Absolute URL string
    """
    base = flask.request.host_url.rstrip("/")
    return "%s%s" % (base, path)


def _require_admin() -> None:
    """Enforce a simple admin token check for now.

    :raises errors.Forbidden: If admin token not provided
    """
    token = flask.request.headers.get("x-auth-token") or flask.request.headers.get(
        "X-Auth-Token"
    )
    if token != "admin":
        raise errors.Forbidden("Admin role required.")


def _validate_uuid(value: str, field: str) -> str:
    """Validate and normalize UUID strings (accept dashless input).

    :param value: UUID string to validate
    :param field: Field name for error messages
    :returns: Normalized UUID string
    :raises errors.BadRequest: If UUID is invalid
    """
    try:
        normalized = str(uuid_module.UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise errors.BadRequest("Failed validating 'format' for '%s'." % field)
    return normalized


def _build_links(
    provider_uuid: str, mv: microversion.Microversion
) -> list[dict[str, str]]:
    """Build Placement-style links array respecting microversion.

    :param provider_uuid: Resource provider UUID
    :param mv: Microversion instance
    :returns: List of link dictionaries
    """
    links: list[dict[str, str]] = [
        {"rel": "self", "href": "/resource_providers/%s" % provider_uuid},
        {
            "rel": "inventories",
            "href": "/resource_providers/%s/inventories" % provider_uuid,
        },
        {"rel": "usages", "href": "/resource_providers/%s/usages" % provider_uuid},
        {
            "rel": "aggregates",
            "href": "/resource_providers/%s/aggregates" % provider_uuid,
        },
        {"rel": "traits", "href": "/resource_providers/%s/traits" % provider_uuid},
    ]
    if mv.is_at_least(11):
        links.append(
            {
                "rel": "allocations",
                "href": "/resource_providers/%s/allocations" % provider_uuid,
            }
        )
    return links


def _parse_required(
    value: str, mv: microversion.Microversion
) -> tuple[list[str], list[str]]:
    """Parse the required query parameter into required/forbidden traits.

    :param value: Required parameter value
    :param mv: Microversion instance
    :returns: Tuple of (required_traits, forbidden_traits)
    :raises errors.BadRequest: If parameter format is invalid
    """
    if mv.is_at_least(22):
        expected_form = "HW_CPU_X86_VMX,!CUSTOM_MAGIC."
    else:
        expected_form = "HW_CPU_X86_VMX,CUSTOM_MAGIC."

    def _invalid(got: str | None = None) -> NoReturn:
        suffix = " Got: %s" % got if got is not None else ""
        raise errors.BadRequest(
            "Invalid query string parameters: Expected 'required' "
            "parameter value of the form: %s%s" % (expected_form, suffix)
        )

    if value == "":
        _invalid()

    required: list[str] = []
    forbidden: list[str] = []
    tokens = [t.strip() for t in value.split(",")]
    if any(t == "" for t in tokens):
        _invalid()

    for token in tokens:
        if token.startswith("!"):
            if not mv.is_at_least(22):
                _invalid(value)
            if len(token) == 1:
                _invalid()
            forbidden.append(token[1:])
        else:
            required.append(token)

    return required, forbidden


def _parse_resources(value: str) -> list[tuple[str, int]]:
    """Parse resources query parameter.

    :param value: Resources parameter value
    :returns: List of (resource_class, amount) tuples
    :raises errors.BadRequest: If parameter format is invalid
    """
    resources: list[tuple[str, int]] = []
    for token in value.split(","):
        if ":" not in token:
            raise errors.BadRequest("Invalid query string parameters")
        rc, amount = token.split(":", 1)
        try:
            resources.append((rc, int(amount)))
        except ValueError:
            raise errors.BadRequest("Invalid query string parameters")
    return resources


def _parse_member_of(value: str) -> list[str]:
    """Parse member_of query parameter.

    Formats supported:
        - Single UUID: <uuid>
        - With 'in:' prefix: in:<uuid1>,<uuid2>,...

    :param value: member_of parameter value
    :returns: List of aggregate UUIDs
    :raises errors.BadRequest: If UUIDs are invalid
    """
    if value.startswith("in:"):
        uuid_str = value[3:]
    else:
        uuid_str = value

    aggregates: list[str] = []
    for agg in uuid_str.split(","):
        agg = agg.strip()
        if not agg:
            continue
        try:
            normalized = str(uuid_module.UUID(agg))
            aggregates.append(normalized)
        except (ValueError, TypeError, AttributeError):
            raise errors.BadRequest(
                "Invalid query string parameters: Expected 'member_of' "
                "parameter to contain valid UUID(s)."
            )

    return aggregates


def _missing_traits(session: Any, traits: list[str]) -> list[str]:
    """Find traits that don't exist in the database.

    :param session: Neo4j session
    :param traits: List of trait names to check
    :returns: List of missing trait names
    """
    if not traits:
        return []
    result = session.run(
        "MATCH (t:Trait) WHERE t.name IN $names RETURN t.name AS name", names=traits
    )
    existing = {row["name"] for row in result}
    return [t for t in traits if t not in existing]


def _provider_traits_match(
    session: Any,
    rp_uuid: str,
    required: list[str],
    forbidden: list[str],
    mv: microversion.Microversion,
) -> bool:
    """Check provider satisfies required and forbidden trait sets.

    :param session: Neo4j session
    :param rp_uuid: Resource provider UUID
    :param required: List of required trait names
    :param forbidden: List of forbidden trait names
    :param mv: Microversion instance
    :returns: True if provider matches trait requirements
    """
    if not required and not forbidden:
        return True

    res = session.run(
        """
        MATCH (rp:ResourceProvider {uuid: $uuid})
        OPTIONAL MATCH (rp)-[:HAS_TRAIT]->(t:Trait)
        RETURN collect(t.name) AS traits
        """,
        uuid=rp_uuid,
    ).single()

    traits: set[str] = set(res["traits"] or [])

    if any(req not in traits for req in required):
        return False
    if any(forb in traits for forb in forbidden):
        return False
    return True


def _provider_in_aggregates(
    session: Any, rp_uuid: str, aggregate_uuids: list[str]
) -> bool:
    """Check if provider is a member of any of the specified aggregates.

    :param session: Neo4j session
    :param rp_uuid: Resource provider UUID
    :param aggregate_uuids: List of aggregate UUIDs
    :returns: True if provider is member of any aggregate
    """
    if not aggregate_uuids:
        return True

    res = session.run(
        """
        MATCH (rp:ResourceProvider {uuid: $uuid})-[:MEMBER_OF]->(agg:Aggregate)
        WHERE agg.uuid IN $aggregates
        RETURN count(agg) AS cnt
        """,
        uuid=rp_uuid,
        aggregates=aggregate_uuids,
    ).single()

    return res is not None and res["cnt"] > 0


def _provider_has_capacity(
    session: Any, rp_uuid: str, requirements: list[tuple[str, int]]
) -> bool:
    """Check provider has capacity for all requested resources.

    :param session: Neo4j session
    :param rp_uuid: Resource provider UUID
    :param requirements: List of (resource_class, amount) tuples
    :returns: True if provider has sufficient capacity
    """
    for rc_name, amount in requirements:
        res = session.run(
            """
            MATCH (rp:ResourceProvider {uuid: $uuid})
                  -[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(rc:ResourceClass {name: $rc})
            OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
            RETURN inv.total AS total,
                   inv.reserved AS reserved,
                   inv.allocation_ratio AS allocation_ratio,
                   COALESCE(sum(alloc.used), 0) AS used
            """,
            uuid=rp_uuid,
            rc=rc_name,
        ).single()

        if not res or res["total"] is None:
            return False

        total = res["total"] or 0
        reserved = res["reserved"] or 0
        ratio = res["allocation_ratio"] or 1.0
        used = res["used"] or 0
        capacity = (total - reserved) * ratio - used
        if capacity < amount:
            return False

    return True


def _format_provider(
    rp: dict[str, Any],
    mv: microversion.Microversion,
    root_uuid: str | None = None,
    parent_uuid: str | None = None,
) -> dict[str, Any]:
    """Format a resource provider node for API response.

    :param rp: Resource provider dict
    :param mv: Microversion instance
    :param root_uuid: Optional root provider UUID
    :param parent_uuid: Optional parent provider UUID
    :returns: Formatted response dict
    """
    body: dict[str, Any] = {
        "uuid": rp.get("uuid"),
        "name": rp.get("name"),
        "generation": rp.get("generation", 0),
    }

    if mv.is_at_least(14):
        body["root_provider_uuid"] = root_uuid or rp.get("uuid")
        body["parent_provider_uuid"] = parent_uuid

    if mv.is_at_least(10):
        body["links"] = _build_links(rp.get("uuid", ""), mv)

    return body


@bp.route("", methods=["GET"])
def list_resource_providers() -> tuple[flask.Response, int]:
    """List resource providers with optional filtering.

    Query Parameters:
        name: Filter by name (contains match).
        uuid: Filter by exact UUID.
        in_tree: Filter to providers in the tree rooted at this UUID.
        member_of: Filter to providers in specified aggregate(s).
        required: Filter to providers with required/forbidden traits.
        resources: Filter to providers with capacity for specified resources.

    :returns: Tuple of (response, status_code)
    """
    _require_admin()
    mv = _mv()

    allowed_params = {"name", "uuid", "in_tree", "member_of", "required", "resources"}
    unknown = set(flask.request.args) - allowed_params
    if unknown:
        raise errors.BadRequest("Invalid query string parameters")

    name = flask.request.args.get("name")
    uuid_filter = flask.request.args.get("uuid")
    in_tree = flask.request.args.get("in_tree")
    member_of_param = flask.request.args.get("member_of")
    required_param = flask.request.args.get("required")
    resources_param = flask.request.args.get("resources")

    # member_of requires microversion >= 1.3
    if member_of_param is not None and not mv.is_at_least(3):
        raise errors.BadRequest("Invalid query string parameters")

    if uuid_filter:
        try:
            uuid_filter = _validate_uuid(uuid_filter, "uuid")
        except errors.BadRequest:
            raise errors.BadRequest("Invalid query string parameters")
    if in_tree:
        in_tree = _validate_uuid(in_tree, "in_tree")

    required_traits: list[str] = []
    forbidden_traits: list[str] = []
    if required_param is not None:
        # required supported starting at mv 1.18
        if mv.minor < 18:
            raise errors.BadRequest("Additional properties are not allowed")
        required_traits, forbidden_traits = _parse_required(required_param, mv)

    required_resources: list[tuple[str, int]] = []
    if resources_param:
        required_resources = _parse_resources(resources_param)

    # Parse member_of parameter
    member_of_aggregates: list[str] = []
    if member_of_param:
        member_of_aggregates = _parse_member_of(member_of_param)

    with _driver().session() as session:
        if required_traits:
            missing = _missing_traits(session, required_traits)
            if missing:
                raise errors.BadRequest("No such trait(s): %s." % ", ".join(missing))

        cypher = "MATCH (rp:ResourceProvider)"
        clauses: list[str] = []
        params: dict[str, Any] = {}
        if name:
            clauses.append("rp.name CONTAINS $name")
            params["name"] = name
        if uuid_filter:
            clauses.append("rp.uuid = $uuid_filter")
            params["uuid_filter"] = uuid_filter
        if in_tree:
            clauses.append(
                """EXISTS {
                    MATCH (specified:ResourceProvider {uuid: $in_tree})
                    OPTIONAL MATCH path = (tree_root:ResourceProvider)-[:PARENT_OF*0..]->(specified)
                    WHERE NOT EXISTS { MATCH (:ResourceProvider)-[:PARENT_OF]->(tree_root) }
                    WITH COALESCE(tree_root, specified) AS root
                    MATCH (root)-[:PARENT_OF*0..]->(rp)
                }"""
            )
            params["in_tree"] = in_tree

        where_str = " AND ".join(clauses) if clauses else "true"
        query = """
            %s
        WHERE %s
        OPTIONAL MATCH (parent:ResourceProvider)-[:PARENT_OF]->(rp)
        OPTIONAL MATCH path = (root:ResourceProvider)-[:PARENT_OF*0..]->(rp)
        WHERE NOT EXISTS { MATCH (:ResourceProvider)-[:PARENT_OF]->(root) }
        WITH rp, parent, root
        ORDER BY length(path) DESC
        WITH rp, parent, collect(root)[0] AS root_provider
        RETURN rp, parent.uuid AS parent_uuid, root_provider.uuid AS root_uuid
            """ % (cypher, where_str)
        result = session.run(query, **params)

        providers: list[dict[str, Any]] = []
        for record in result:
            rp = dict(record["rp"])
            rp_uuid_val: str = rp.get("uuid", "")

            if required_traits or forbidden_traits:
                if not _provider_traits_match(
                    session, rp_uuid_val, required_traits, forbidden_traits, mv
                ):
                    continue

            if required_resources:
                if not _provider_has_capacity(session, rp_uuid_val, required_resources):
                    continue

            # Check member_of filter
            if member_of_aggregates:
                if not _provider_in_aggregates(
                    session, rp_uuid_val, member_of_aggregates
                ):
                    continue

            providers.append(
                _format_provider(
                    rp,
                    mv,
                    root_uuid=record["root_uuid"],
                    parent_uuid=record["parent_uuid"],
                )
            )

    resp = flask.jsonify({"resource_providers": providers})
    if mv.is_at_least(15):
        resp.headers["cache-control"] = "no-cache"
        resp.headers["last-modified"] = _httpdate()
    return resp, 200


@bp.route("", methods=["POST"])
def create_resource_provider() -> tuple[flask.Response, int]:
    """Create a new resource provider.

    Request Body:
        name: Required. Provider name (must be unique).
        uuid: Optional. Provider UUID (generated if not provided).
        parent_provider_uuid: Optional. UUID of parent provider.

    :returns: Tuple of (response, status_code)
    """
    _require_admin()
    mv = _mv()

    try:
        data = flask.request.get_json(force=True, silent=False) or {}
    except Exception as exc:
        raise errors.BadRequest("Malformed JSON: %s" % exc)

    name = data.get("name")
    parent_uuid = data.get("parent_provider_uuid")
    rp_uuid_raw = data.get("uuid") or str(uuid_module.uuid4())
    rp_uuid = _validate_uuid(rp_uuid_raw, "uuid")

    if not name:
        raise errors.BadRequest("'name' is a required property")
    if len(name) > 200:
        raise errors.BadRequest("Failed validating 'maxLength'")

    if parent_uuid:
        parent_uuid = _validate_uuid(parent_uuid, "parent_provider_uuid")
        if parent_uuid == rp_uuid:
            raise errors.BadRequest(
                "parent provider UUID cannot be same as UUID. "
                'Unable to create resource provider "%s", %s:' % (name, rp_uuid)
            )
        if not mv.is_at_least(14):
            raise errors.BadRequest("JSON does not validate")

    status_code = 200 if mv.is_at_least(20) else 201

    with _driver().session() as session:
        # Uniqueness checks
        duplicate_uuid = session.run(
            "MATCH (rp:ResourceProvider {uuid: $uuid}) RETURN rp", uuid=rp_uuid
        ).single()
        if duplicate_uuid:
            raise errors.Conflict(
                "Conflicting resource provider uuid: %s already exists" % rp_uuid
            )

        duplicate_name = session.run(
            "MATCH (rp:ResourceProvider {name: $name}) RETURN rp", name=name
        ).single()
        if duplicate_name:
            raise errors.Conflict(
                "Conflicting resource provider name: %s already exists" % name,
                code="placement.duplicate_name",
            )

        if parent_uuid:
            parent_node = session.run(
                "MATCH (p:ResourceProvider {uuid: $uuid}) RETURN p", uuid=parent_uuid
            ).single()
            if not parent_node:
                raise errors.BadRequest("parent provider UUID does not exist")

        result = session.run(
            """
            OPTIONAL MATCH (parent:ResourceProvider {uuid: $parent_uuid})
            WITH parent
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
            raise errors.BadRequest("Failed to create resource provider.")

        root_uuid = parent_uuid or rp_uuid
        body = _format_provider(
            {"uuid": rp_uuid, "name": name, "generation": 0},
            mv,
            root_uuid=root_uuid,
            parent_uuid=parent_uuid,
        )

    location = _abs_url("/resource_providers/%s" % rp_uuid)
    if status_code == 201:
        resp = flask.Response(status=201)
        resp.headers["Location"] = location
        resp.headers.pop("Content-Type", None)
        return resp, 201

    resp = flask.jsonify(body)
    resp.headers["Location"] = location
    return resp, 200


@bp.route("/<string:rp_uuid>", methods=["GET"])
def get_resource_provider(rp_uuid: str) -> tuple[flask.Response, int]:
    """Get a specific resource provider by UUID.

    :param rp_uuid: Resource provider UUID
    :returns: Tuple of (response, status_code)
    """
    _require_admin()
    mv = _mv()
    try:
        rp_uuid = _validate_uuid(rp_uuid, "uuid")
    except errors.BadRequest:
        raise errors.NotFound("No resource provider with uuid %s found." % rp_uuid)

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
            uuid=rp_uuid,
        ).single()

        if not record:
            raise errors.NotFound("No resource provider with uuid %s found." % rp_uuid)

    resp = flask.jsonify(
        _format_provider(
            dict(record["rp"]),
            mv,
            root_uuid=record["root_uuid"],
            parent_uuid=record["parent_uuid"],
        )
    )
    if mv.is_at_least(15):
        resp.headers["cache-control"] = "no-cache"
        resp.headers["last-modified"] = _httpdate()
    return resp, 200


@bp.route("/<string:rp_uuid>", methods=["PUT"])
def update_resource_provider(rp_uuid: str) -> tuple[flask.Response, int]:
    """Update a resource provider.

    Request Body:
        name: Optional. New provider name.
        generation: Required. Current generation for optimistic concurrency.
        parent_provider_uuid: Optional. New parent UUID (re-parenting).

    :param rp_uuid: Resource provider UUID
    :returns: Tuple of (response, status_code)
    """
    _require_admin()
    mv = _mv()
    rp_uuid = _validate_uuid(rp_uuid, "uuid")

    try:
        data = flask.request.get_json(force=True, silent=False) or {}
    except Exception as exc:
        raise errors.BadRequest("Malformed JSON: %s" % exc)

    allowed_keys = {"name", "generation", "parent_provider_uuid"}
    extra_keys = set(data.keys()) - allowed_keys
    if extra_keys:
        if "uuid" in extra_keys:
            raise errors.BadRequest("Additional properties are not allowed")
        raise errors.BadRequest("JSON does not validate")

    name = data.get("name")
    generation = data.get("generation")
    # Use a sentinel to distinguish between "key not present" and "key is null"
    _NOT_SET = object()
    new_parent = data.get("parent_provider_uuid", _NOT_SET)
    has_parent_update = new_parent is not _NOT_SET

    if name and len(name) > 200:
        raise errors.BadRequest("Failed validating 'maxLength'")

    if has_parent_update:
        if new_parent is not None:
            if new_parent == rp_uuid:
                raise errors.BadRequest(
                    "creating loop in the provider tree is not allowed."
                )
            new_parent = _validate_uuid(new_parent, "parent_provider_uuid")
        if not mv.is_at_least(14):
            raise errors.BadRequest("JSON does not validate")

    # Before microversion 1.17, generation was optional and not incremented
    require_generation = mv.is_at_least(17)

    with _driver().session() as session:
        existing = session.run(
            """
            MATCH (rp:ResourceProvider {uuid: $uuid})
            OPTIONAL MATCH (parent:ResourceProvider)-[:PARENT_OF]->(rp)
            RETURN rp, parent.uuid AS parent_uuid
            """,
            uuid=rp_uuid,
        ).single()
        if not existing:
            raise errors.NotFound("No resource provider with uuid %s found" % rp_uuid)

        current_parent_uuid = existing["parent_uuid"]

        if name:
            dup_name = session.run(
                "MATCH (rp:ResourceProvider {name: $name}) "
                "WHERE rp.uuid <> $uuid RETURN rp",
                name=name,
                uuid=rp_uuid,
            ).single()
            if dup_name:
                raise errors.Conflict(
                    "Conflicting resource provider name: %s already exists" % name,
                    code="placement.duplicate_name",
                )

        current_generation = existing["rp"].get("generation", 0)
        if require_generation and generation is None:
            raise errors.BadRequest("'generation' is a required field for updates.")

        if generation is not None and generation != current_generation:
            raise errors.ResourceProviderGenerationConflict(
                "Generation mismatch for resource provider %s." % rp_uuid
            )

        if has_parent_update:
            # Re-parenting rules: only allowed from 1.37 onwards
            if not mv.is_at_least(37):
                if new_parent is None and current_parent_uuid is not None:
                    raise errors.BadRequest(
                        "un-parenting a provider is not currently allowed"
                    )
                if (
                    new_parent is not None
                    and current_parent_uuid is not None
                    and new_parent != current_parent_uuid
                ):
                    raise errors.BadRequest(
                        "re-parenting a provider is not currently allowed"
                    )

            if new_parent is not None:
                parent_exists = session.run(
                    "MATCH (p:ResourceProvider {uuid: $uuid}) RETURN p", uuid=new_parent
                ).single()
                if not parent_exists:
                    raise errors.BadRequest("parent provider UUID does not exist")

                # Prevent cycles
                cycle = session.run(
                    """
                    MATCH (rp:ResourceProvider {uuid: $uuid})
                    MATCH (parent:ResourceProvider {uuid: $parent_uuid})
                    MATCH (rp)-[:PARENT_OF*]->(desc)
                    WHERE desc.uuid = $parent_uuid
                    RETURN desc
                    """,
                    uuid=rp_uuid,
                    parent_uuid=new_parent,
                ).single()
                if cycle:
                    raise errors.BadRequest(
                        "creating loop in the provider tree is not allowed."
                    )

        # Perform update
        session.run(
            """
            MATCH (rp:ResourceProvider {uuid: $uuid})
            SET rp.name = COALESCE($name, rp.name),
                rp.updated_at = datetime()
            WITH rp
            OPTIONAL MATCH (rp)<-[rel:PARENT_OF]-(:ResourceProvider)
            RETURN rp, rel
            """,
            uuid=rp_uuid,
            name=name,
        ).single()

        # Update parent relationships if needed
        if has_parent_update:
            session.run(
                """
                MATCH (rp:ResourceProvider {uuid: $uuid})
                OPTIONAL MATCH (old_parent:ResourceProvider)-[old:PARENT_OF]->(rp)
                DELETE old
                """,
                uuid=rp_uuid,
            )
            if new_parent:
                session.run(
                    """
                    MATCH (rp:ResourceProvider {uuid: $uuid})
                    MATCH (parent:ResourceProvider {uuid: $parent_uuid})
                    CREATE (parent)-[:PARENT_OF]->(rp)
                    """,
                    uuid=rp_uuid,
                    parent_uuid=new_parent,
                )

        new_generation = current_generation
        if generation is not None:
            new_generation = current_generation + 1
            session.run(
                """
                MATCH (rp:ResourceProvider {uuid: $uuid})
                SET rp.generation = $generation
                """,
                uuid=rp_uuid,
                generation=new_generation,
            )

        # Fetch response shape
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
            uuid=rp_uuid,
        ).single()

    body = _format_provider(
        dict(record["rp"], generation=new_generation),
        mv,
        root_uuid=record["root_uuid"],
        parent_uuid=record["parent_uuid"],
    )
    resp = flask.jsonify(body)
    if mv.is_at_least(15):
        resp.headers["cache-control"] = "no-cache"
        resp.headers["last-modified"] = _httpdate()
    return resp, 200


@bp.route("/<string:rp_uuid>", methods=["DELETE"])
def delete_resource_provider(rp_uuid: str) -> flask.Response:
    """Delete a resource provider.

    Will fail if the provider has allocations or child providers.

    :param rp_uuid: Resource provider UUID
    :returns: Response with status 204
    """
    _require_admin()
    with _driver().session() as session:
        # Check if provider exists
        exists = session.run(
            "MATCH (rp:ResourceProvider {uuid: $uuid}) RETURN rp",
            uuid=rp_uuid,
        ).single()
        if not exists:
            raise errors.NotFound(
                "No resource provider with uuid %s found for delete" % rp_uuid
            )

        # Check for child providers
        has_children = session.run(
            "MATCH (rp:ResourceProvider {uuid: $uuid})-[:PARENT_OF]->() "
            "RETURN count(*) as cnt",
            uuid=rp_uuid,
        ).single()
        if has_children and has_children["cnt"] > 0:
            raise errors.ResourceProviderInUse(
                "Unable to delete parent resource provider %s: "
                "It has child resource providers." % rp_uuid,
                code="placement.resource_provider.cannot_delete_parent",
            )

        # Check for allocations
        has_allocations = session.run(
            """
            MATCH (rp:ResourceProvider {uuid: $uuid})-[:HAS_INVENTORY]->(inv)<-[:CONSUMES]-()
            RETURN count(*) as cnt
            """,
            uuid=rp_uuid,
        ).single()
        if has_allocations and has_allocations["cnt"] > 0:
            raise errors.ResourceProviderInUse(
                "Resource provider %s has active allocations." % rp_uuid
            )

        # Safe to delete
        session.run(
            "MATCH (rp:ResourceProvider {uuid: $uuid}) DETACH DELETE rp",
            uuid=rp_uuid,
        )

    resp = flask.Response(status=204)
    resp.headers.pop("Content-Type", None)
    return resp
