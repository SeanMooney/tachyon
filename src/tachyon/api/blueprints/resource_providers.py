"""Resource Providers API blueprint.

Implements Placement-compatible CRUD operations for ResourceProvider nodes.
"""

from __future__ import annotations

import uuid as uuidlib

from datetime import datetime, timezone
from flask import Blueprint, Response, g, jsonify, request

from tachyon.api.errors import (
    BadRequest,
    Conflict,
    Forbidden,
    NotFound,
    ResourceProviderGenerationConflict,
    ResourceProviderInUse,
)
from tachyon.api.microversion import Microversion

bp = Blueprint("resource_providers", __name__, url_prefix="/resource_providers")


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


def _abs_url(path: str) -> str:
    """Build absolute URL for Location headers."""
    base = request.host_url.rstrip("/")
    return f"{base}{path}"


def _require_admin():
    """Enforce a simple admin token check for now."""
    token = request.headers.get("x-auth-token") or request.headers.get("X-Auth-Token")
    if token != "admin":
        raise Forbidden("Admin role required.")


def _validate_uuid(value: str, field: str) -> str:
    """Validate and normalize UUID strings (accept dashless input)."""
    try:
        normalized = str(uuidlib.UUID(value))
    except Exception:
        raise BadRequest(f"Failed validating 'format' for '{field}'.")
    return normalized


def _build_links(provider_uuid: str, mv: Microversion) -> list[dict]:
    """Build Placement-style links array respecting microversion."""
    links = [
        {"rel": "self", "href": f"/resource_providers/{provider_uuid}"},
        {"rel": "inventories", "href": f"/resource_providers/{provider_uuid}/inventories"},
        {"rel": "usages", "href": f"/resource_providers/{provider_uuid}/usages"},
        {"rel": "aggregates", "href": f"/resource_providers/{provider_uuid}/aggregates"},
        {"rel": "traits", "href": f"/resource_providers/{provider_uuid}/traits"},
    ]
    if mv.is_at_least(11):
        links.append(
            {"rel": "allocations", "href": f"/resource_providers/{provider_uuid}/allocations"}
        )
    return links


def _parse_required(value: str, mv: Microversion) -> tuple[list[str], list[str]]:
    """Parse the required query parameter into required/forbidden traits."""
    expected_form = (
        "HW_CPU_X86_VMX,!CUSTOM_MAGIC."
        if mv.is_at_least(22)
        else "HW_CPU_X86_VMX,CUSTOM_MAGIC."
    )

    def _invalid(got: str | None = None):
        suffix = f" Got: {got}" if got is not None else ""
        raise BadRequest(
            f"Invalid query string parameters: Expected 'required' parameter value of the form: {expected_form}{suffix}"
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
    resources: list[tuple[str, int]] = []
    for token in value.split(","):
        if ":" not in token:
            raise BadRequest("Invalid query string parameters")
        rc, amount = token.split(":", 1)
        try:
            resources.append((rc, int(amount)))
        except ValueError:
            raise BadRequest("Invalid query string parameters")
    return resources


def _parse_member_of(value: str) -> list[str]:
    """Parse member_of query parameter.

    Formats supported:
        - Single UUID: <uuid>
        - With 'in:' prefix: in:<uuid1>,<uuid2>,...

    Returns:
        List of aggregate UUIDs.
    """
    if value.startswith("in:"):
        uuid_str = value[3:]
    else:
        uuid_str = value

    aggregates = []
    for agg in uuid_str.split(","):
        agg = agg.strip()
        if not agg:
            continue
        try:
            normalized = str(uuidlib.UUID(agg))
            aggregates.append(normalized)
        except Exception:
            raise BadRequest(
                "Invalid query string parameters: Expected 'member_of' parameter "
                "to contain valid UUID(s)."
            )

    return aggregates


def _missing_traits(session, traits: list[str]) -> list[str]:
    if not traits:
        return []
    result = session.run(
        "MATCH (t:Trait) WHERE t.name IN $names RETURN t.name AS name", names=traits
    )
    existing = {row["name"] for row in result}
    return [t for t in traits if t not in existing]


def _provider_traits_match(
    session, rp_uuid: str, required: list[str], forbidden: list[str], mv: Microversion
) -> bool:
    """Check provider satisfies required and forbidden trait sets."""
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

    traits = set(res["traits"] or [])

    if any(req not in traits for req in required):
        return False
    if any(forb in traits for forb in forbidden):
        return False
    return True


def _provider_in_aggregates(
    session, rp_uuid: str, aggregate_uuids: list[str]
) -> bool:
    """Check if provider is a member of any of the specified aggregates."""
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

    return res and res["cnt"] > 0


def _provider_has_capacity(
    session, rp_uuid: str, requirements: list[tuple[str, int]]
) -> bool:
    """Check provider has capacity for all requested resources."""
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
    rp: dict,
    mv: Microversion,
    root_uuid: str | None = None,
    parent_uuid: str | None = None,
) -> dict:
    """Format a resource provider node for API response."""

    body = {
        "uuid": rp.get("uuid"),
        "name": rp.get("name"),
        "generation": rp.get("generation", 0),
    }

    if mv.is_at_least(14):
        body["root_provider_uuid"] = root_uuid or rp.get("uuid")
        body["parent_provider_uuid"] = parent_uuid

    if mv.is_at_least(10):
        body["links"] = _build_links(rp.get("uuid"), mv)

    return body


@bp.route("", methods=["GET"])
def list_resource_providers() -> tuple[Response, int]:
    """List resource providers with optional filtering.

    Query Parameters:
        name: Filter by name (contains match).
        uuid: Filter by exact UUID.
        in_tree: Filter to providers in the tree rooted at this UUID.
        member_of: Filter to providers in specified aggregate(s).
        required: Filter to providers with required/forbidden traits.
        resources: Filter to providers with capacity for specified resources.
    """
    _require_admin()
    mv = _mv()

    allowed_params = {"name", "uuid", "in_tree", "member_of", "required", "resources"}
    unknown = set(request.args.keys()) - allowed_params
    if unknown:
        raise BadRequest("Invalid query string parameters")

    name = request.args.get("name")
    uuid_filter = request.args.get("uuid")
    in_tree = request.args.get("in_tree")
    member_of_param = request.args.get("member_of")
    required_param = request.args.get("required")
    resources_param = request.args.get("resources")

    # member_of requires microversion >= 1.3
    if member_of_param is not None and not mv.is_at_least(3):
        raise BadRequest("Invalid query string parameters")

    if uuid_filter:
        try:
            uuid_filter = _validate_uuid(uuid_filter, "uuid")
        except BadRequest:
            raise BadRequest("Invalid query string parameters")
    if in_tree:
        in_tree = _validate_uuid(in_tree, "in_tree")

    required_traits: list[str] = []
    forbidden_traits: list[str] = []
    if required_param is not None:
        # required supported starting at mv 1.18
        if mv.minor < 18:
            raise BadRequest("Additional properties are not allowed")
        required_traits, forbidden_traits = _parse_required(required_param, mv)

    required_resources = _parse_resources(resources_param) if resources_param else []

    # Parse member_of parameter
    member_of_aggregates: list[str] = []
    if member_of_param:
        member_of_aggregates = _parse_member_of(member_of_param)

    with _driver().session() as session:
        if required_traits:
            missing = _missing_traits(session, required_traits)
            if missing:
                raise BadRequest(f"No such trait(s): {', '.join(missing)}.")

        cypher = "MATCH (rp:ResourceProvider)"
        clauses = []
        params: dict = {}
        if name:
            clauses.append("rp.name CONTAINS $name")
            params["name"] = name
        if uuid_filter:
            clauses.append("rp.uuid = $uuid_filter")
            params["uuid_filter"] = uuid_filter
        if in_tree:
            # Find all providers in the same tree as the specified provider
            # First find the root of the tree containing the specified provider,
            # then get all descendants of that root
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
        result = session.run(
            f"""
            {cypher}
        WHERE {where_str}
        OPTIONAL MATCH (parent:ResourceProvider)-[:PARENT_OF]->(rp)
        OPTIONAL MATCH path = (root:ResourceProvider)-[:PARENT_OF*0..]->(rp)
        WHERE NOT EXISTS {{ MATCH (:ResourceProvider)-[:PARENT_OF]->(root) }}
        WITH rp, parent, root
        ORDER BY length(path) DESC
        WITH rp, parent, collect(root)[0] AS root_provider
        RETURN rp, parent.uuid AS parent_uuid, root_provider.uuid AS root_uuid
            """,
            **params,
        )

        providers = []
        for record in result:
            rp = dict(record["rp"])
            rp_uuid = rp.get("uuid")

            if required_traits or forbidden_traits:
                if not _provider_traits_match(
                    session, rp_uuid, required_traits, forbidden_traits, mv
                ):
                    continue

            if required_resources:
                if not _provider_has_capacity(session, rp_uuid, required_resources):
                    continue

            # Check member_of filter
            if member_of_aggregates:
                if not _provider_in_aggregates(session, rp_uuid, member_of_aggregates):
                    continue

            providers.append(
                _format_provider(
                    rp,
                    mv,
                    root_uuid=record["root_uuid"],
                    parent_uuid=record["parent_uuid"],
                )
            )

    resp = jsonify({"resource_providers": providers})
    if mv.is_at_least(15):
        resp.headers["cache-control"] = "no-cache"
        resp.headers["last-modified"] = _httpdate()
    return resp, 200


@bp.route("", methods=["POST"])
def create_resource_provider() -> tuple[Response, int]:
    """Create a new resource provider.

    Request Body:
        name: Required. Provider name (must be unique).
        uuid: Optional. Provider UUID (generated if not provided).
        parent_provider_uuid: Optional. UUID of parent provider.
    """
    _require_admin()
    mv = _mv()

    try:
        data = request.get_json(force=True, silent=False) or {}
    except Exception as exc:
        raise BadRequest(f"Malformed JSON: {exc}")

    name = data.get("name")
    parent_uuid = data.get("parent_provider_uuid")
    rp_uuid_raw = data.get("uuid") or str(uuidlib.uuid4())
    rp_uuid = _validate_uuid(rp_uuid_raw, "uuid")

    if not name:
        raise BadRequest("'name' is a required property")
    if len(name) > 200:
        raise BadRequest("Failed validating 'maxLength'")

    if parent_uuid:
        parent_uuid = _validate_uuid(parent_uuid, "parent_provider_uuid")
        if parent_uuid == rp_uuid:
            raise BadRequest(
                "parent provider UUID cannot be same as UUID. "
                f"Unable to create resource provider \"{name}\", {rp_uuid}:"
            )
        if not mv.is_at_least(14):
            raise BadRequest("JSON does not validate")

    status_code = 200 if mv.is_at_least(20) else 201

    with _driver().session() as session:
        # Uniqueness checks
        duplicate_uuid = session.run(
            "MATCH (rp:ResourceProvider {uuid: $uuid}) RETURN rp", uuid=rp_uuid
        ).single()
        if duplicate_uuid:
            raise Conflict(
                f"Conflicting resource provider uuid: {rp_uuid} already exists"
            )

        duplicate_name = session.run(
            "MATCH (rp:ResourceProvider {name: $name}) RETURN rp", name=name
        ).single()
        if duplicate_name:
            raise Conflict(
                f"Conflicting resource provider name: {name} already exists",
                code="placement.duplicate_name",
            )

        parent_node = None
        if parent_uuid:
            parent_node = session.run(
                "MATCH (p:ResourceProvider {uuid: $uuid}) RETURN p", uuid=parent_uuid
            ).single()
            if not parent_node:
                raise BadRequest("parent provider UUID does not exist")

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
            raise BadRequest("Failed to create resource provider.")

        root_uuid = parent_uuid or rp_uuid
        body = _format_provider(
            {"uuid": rp_uuid, "name": name, "generation": 0},
            mv,
            root_uuid=root_uuid,
            parent_uuid=parent_uuid,
        )

    location = _abs_url(f"/resource_providers/{rp_uuid}")
    if status_code == 201:
        resp = Response(status=201)
        resp.headers["Location"] = location
        resp.headers.pop("Content-Type", None)
        return resp, 201

    resp = jsonify(body)
    resp.headers["Location"] = location
    return resp, 200


@bp.route("/<string:uuid>", methods=["GET"])
def get_resource_provider(uuid: str) -> tuple[Response, int]:
    """Get a specific resource provider by UUID."""
    _require_admin()
    mv = _mv()
    try:
        uuid = _validate_uuid(uuid, "uuid")
    except BadRequest:
        raise NotFound(f"No resource provider with uuid {uuid} found.")

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
            raise NotFound(f"No resource provider with uuid {uuid} found.")

    resp = jsonify(
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


@bp.route("/<string:uuid>", methods=["PUT"])
def update_resource_provider(uuid: str) -> tuple[Response, int]:
    """Update a resource provider.

    Request Body:
        name: Optional. New provider name.
        generation: Required. Current generation for optimistic concurrency.
        parent_provider_uuid: Optional. New parent UUID (re-parenting).
    """
    _require_admin()
    mv = _mv()
    uuid = _validate_uuid(uuid, "uuid")

    try:
        data = request.get_json(force=True, silent=False) or {}
    except Exception as exc:
        raise BadRequest(f"Malformed JSON: {exc}")

    allowed_keys = {"name", "generation", "parent_provider_uuid"}
    extra_keys = set(data.keys()) - allowed_keys
    if extra_keys:
        if "uuid" in extra_keys:
            raise BadRequest("Additional properties are not allowed")
        raise BadRequest("JSON does not validate")

    name = data.get("name")
    generation = data.get("generation")
    # Use a sentinel to distinguish between "key not present" and "key is null"
    _NOT_SET = object()
    new_parent = data.get("parent_provider_uuid", _NOT_SET)
    has_parent_update = new_parent is not _NOT_SET

    if name and len(name) > 200:
        raise BadRequest("Failed validating 'maxLength'")

    if has_parent_update:
        if new_parent is not None:
            if new_parent == uuid:
                raise BadRequest("creating loop in the provider tree is not allowed.")
            new_parent = _validate_uuid(new_parent, "parent_provider_uuid")
        if not mv.is_at_least(14):
            raise BadRequest("JSON does not validate")

    # Before microversion 1.17, generation was optional and not incremented
    require_generation = mv.is_at_least(17)

    with _driver().session() as session:
        existing = session.run(
            """
            MATCH (rp:ResourceProvider {uuid: $uuid})
            OPTIONAL MATCH (parent:ResourceProvider)-[:PARENT_OF]->(rp)
            RETURN rp, parent.uuid AS parent_uuid
            """,
            uuid=uuid,
        ).single()
        if not existing:
            raise NotFound(f"No resource provider with uuid {uuid} found")

        current_parent_uuid = existing["parent_uuid"]

        if name:
            dup_name = session.run(
                "MATCH (rp:ResourceProvider {name: $name}) WHERE rp.uuid <> $uuid RETURN rp",
                name=name,
                uuid=uuid,
            ).single()
            if dup_name:
                raise Conflict(
                    "Conflicting resource provider name: %s already exists" % name,
                    code="placement.duplicate_name",
                )

        current_generation = existing["rp"].get("generation", 0)
        if require_generation and generation is None:
            raise BadRequest("'generation' is a required field for updates.")

        if generation is not None and generation != current_generation:
            raise ResourceProviderGenerationConflict(
                f"Generation mismatch for resource provider {uuid}."
            )

        if has_parent_update:
            # Re-parenting rules: only allowed from 1.37 onwards
            if not mv.is_at_least(37):
                if new_parent is None and current_parent_uuid is not None:
                    raise BadRequest("un-parenting a provider is not currently allowed")
                if (
                    new_parent is not None
                    and current_parent_uuid is not None
                    and new_parent != current_parent_uuid
                ):
                    raise BadRequest("re-parenting a provider is not currently allowed")

            if new_parent is not None:
                parent_exists = session.run(
                    "MATCH (p:ResourceProvider {uuid: $uuid}) RETURN p", uuid=new_parent
                ).single()
                if not parent_exists:
                    raise BadRequest("parent provider UUID does not exist")

                # Prevent cycles
                cycle = session.run(
                    """
                    MATCH (rp:ResourceProvider {uuid: $uuid})
                    MATCH (parent:ResourceProvider {uuid: $parent_uuid})
                    MATCH (rp)-[:PARENT_OF*]->(desc)
                    WHERE desc.uuid = $parent_uuid
                    RETURN desc
                    """,
                    uuid=uuid,
                    parent_uuid=new_parent,
                ).single()
                if cycle:
                    raise BadRequest("creating loop in the provider tree is not allowed.")

        # Perform update
        result = session.run(
            """
            MATCH (rp:ResourceProvider {uuid: $uuid})
            SET rp.name = COALESCE($name, rp.name),
                rp.updated_at = datetime()
            WITH rp
            OPTIONAL MATCH (rp)<-[rel:PARENT_OF]-(:ResourceProvider)
            RETURN rp, rel
            """,
            uuid=uuid,
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
                uuid=uuid,
            )
            if new_parent:
                session.run(
                    """
                    MATCH (rp:ResourceProvider {uuid: $uuid})
                    MATCH (parent:ResourceProvider {uuid: $parent_uuid})
                    CREATE (parent)-[:PARENT_OF]->(rp)
                    """,
                    uuid=uuid,
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
                uuid=uuid,
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
            uuid=uuid,
        ).single()

    body = _format_provider(
        {**dict(record["rp"]), "generation": new_generation},
        mv,
        root_uuid=record["root_uuid"],
        parent_uuid=record["parent_uuid"],
    )
    resp = jsonify(body)
    if mv.is_at_least(15):
        resp.headers["cache-control"] = "no-cache"
        resp.headers["last-modified"] = _httpdate()
    return resp, 200


@bp.route("/<string:uuid>", methods=["DELETE"])
def delete_resource_provider(uuid: str) -> Response:
    """Delete a resource provider.

    Will fail if the provider has allocations or child providers.
    """
    _require_admin()
    with _driver().session() as session:
        # Check if provider exists
        exists = session.run(
            "MATCH (rp:ResourceProvider {uuid: $uuid}) RETURN rp",
            uuid=uuid,
        ).single()
        if not exists:
            raise NotFound(
                f"No resource provider with uuid {uuid} found for delete"
            )

        # Check for child providers
        has_children = session.run(
            "MATCH (rp:ResourceProvider {uuid: $uuid})-[:PARENT_OF]->() RETURN count(*) as cnt",
            uuid=uuid,
        ).single()
        if has_children and has_children["cnt"] > 0:
            raise ResourceProviderInUse(
                f"Unable to delete parent resource provider {uuid}: It has child resource providers.",
                code="placement.resource_provider.cannot_delete_parent"
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

    resp = Response(status=204)
    resp.headers.pop("Content-Type", None)
    return resp
