# SPDX-License-Identifier: Apache-2.0

"""Usages API blueprint.

Implements Placement-compatible usage reporting.
"""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Any

import flask

from oslo_log import log

from tachyon.api import errors
from tachyon.api import microversion
from tachyon.policies import usage as usage_policies

LOG = log.getLogger(__name__)

bp = flask.Blueprint("usages", __name__)


def _mv() -> microversion.Microversion:
    """Return the parsed microversion from the request context.

    :returns: Microversion instance
    """
    mv: microversion.Microversion | None = getattr(flask.g, "microversion", None)
    if mv is None:
        return microversion.Microversion(1, 0)
    return mv


def _httpdate(dt: datetime | None = None) -> str:
    """Format a datetime as HTTP-date.

    :param dt: Datetime to format, or None for current time
    :returns: HTTP-date formatted string
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    return format_datetime(dt, usegmt=True)


def _add_cache_headers(resp: flask.Response) -> flask.Response:
    """Add cache control headers at microversion 1.15+.

    :param resp: Flask response object
    :returns: Response with cache headers
    """
    mv = _mv()
    if mv.is_at_least(15):
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["Last-Modified"] = _httpdate()
    return resp


def _driver() -> Any:
    """Get the Neo4j driver from the Flask app.

    :returns: Neo4j driver instance
    """
    from tachyon.api import app

    return app.get_driver()


@bp.route("/resource_providers/<string:rp_uuid>/usages", methods=["GET"])
def provider_usages(rp_uuid: str) -> tuple[flask.Response, int]:
    """Get resource usages for a resource provider.

    Returns the sum of allocations against each resource class
    on the specified provider.

    At microversion 1.15+, includes cache-control and last-modified headers.

    :param rp_uuid: Resource provider UUID
    :returns: Tuple of (response, status_code)
    """
    flask.g.context.can(usage_policies.PROVIDER_USAGES)

    with _driver().session() as session:
        # Check provider exists
        provider = session.run(
            "MATCH (rp:ResourceProvider {uuid: $uuid}) RETURN rp",
            uuid=rp_uuid,
        ).single()

        if not provider:
            raise errors.NotFound("Resource provider %s not found." % rp_uuid)

        rows = session.run(
            """
            MATCH (rp:ResourceProvider {uuid: $uuid})
                  -[:HAS_INVENTORY]->(inv)
                  -[:OF_CLASS]->(rc:ResourceClass)
            OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
            RETURN rc.name AS rc, COALESCE(sum(alloc.used), 0) AS used
            """,
            uuid=rp_uuid,
        )
        usages = {row["rc"]: int(row["used"]) for row in rows}

    resp = flask.jsonify(
        {
            "resource_provider_generation": provider["rp"].get("generation", 0),
            "usages": usages,
        }
    )
    return _add_cache_headers(resp), 200


@bp.route("/usages", methods=["GET"])
def project_usages() -> tuple[flask.Response, int]:
    """Get resource usages for a project.

    Query Parameters:
        project_id: Required. Project ID to get usages for.
        user_id: Optional. User ID to filter usages.
        consumer_type: Optional (1.38+). Consumer type to filter usages.

    Returns the sum of allocations for all consumers owned by the project.
    At microversion 1.38+, can filter by consumer_type and returns grouped
    response with consumer_count.
    At microversion 1.15+, includes cache-control and last-modified headers.

    This endpoint was added at microversion 1.9.

    :returns: Tuple of (response, status_code)
    """
    mv = _mv()
    # This endpoint was added at microversion 1.9
    if not mv.is_at_least(9):
        raise errors.NotFound("The resource could not be found.")

    project_id = flask.request.args.get("project_id")
    user_id = flask.request.args.get("user_id")
    consumer_type = flask.request.args.get("consumer_type") if mv.is_at_least(38) else None

    if not project_id:
        raise errors.BadRequest("'project_id' is a required property")

    # Check policy with project_id as target for project-level access
    flask.g.context.can(usage_policies.TOTAL_USAGES, target={"project_id": project_id})

    with _driver().session() as session:
        if mv.is_at_least(38):
            # At 1.38+, group usages by consumer_type with consumer_count
            # Build dynamic query based on filters
            base_match = """
                MATCH (c:Consumer)-[:OWNED_BY]->(proj:Project {external_id: $project_id})
            """
            params: dict[str, Any] = {"project_id": project_id}

            user_match = ""
            if user_id:
                user_match = """
                MATCH (c)-[:CREATED_BY]->(u:User {external_id: $user_id})
                """
                params["user_id"] = user_id

            type_filter = ""
            if consumer_type and consumer_type != "all":
                type_filter = """
                WHERE c.consumer_type = $consumer_type
                """
                params["consumer_type"] = consumer_type

            # First query: get consumer counts per consumer_type
            count_query = base_match + user_match + type_filter + """
                WITH COALESCE(c.consumer_type, 'unknown') AS ctype, count(DISTINCT c) AS cnt
                RETURN ctype, cnt
            """
            count_rows = list(session.run(count_query, **params))
            consumer_counts = {row["ctype"]: row["cnt"] for row in count_rows}

            # Second query: get usages per consumer_type and resource class
            usage_query = base_match + user_match + type_filter + """
                MATCH (c)-[alloc:CONSUMES]->(inv)-[:OF_CLASS]->(rc:ResourceClass)
                WITH COALESCE(c.consumer_type, 'unknown') AS ctype,
                     rc.name AS rc, sum(alloc.used) AS used
                RETURN ctype, rc, used
            """
            usage_rows = list(session.run(usage_query, **params))

            # Group by consumer_type - Placement uses dict keyed by consumer_type
            # Format: {"usages": {"INSTANCE": {"consumer_count": 1, "VCPU": 2}}}
            usages_by_type: dict[str, dict[str, Any]] = {}
            for row in usage_rows:
                ctype = row["ctype"]
                if ctype not in usages_by_type:
                    usages_by_type[ctype] = {
                        "consumer_count": consumer_counts.get(ctype, 0),
                    }
                usages_by_type[ctype][row["rc"]] = int(row["used"])

            # Handle 'all' consumer_type - aggregate everything
            if consumer_type == "all":
                total_count = sum(consumer_counts.values())
                total_usages: dict[str, int] = {}
                for ctype, data in usages_by_type.items():
                    for key, val in data.items():
                        if key != "consumer_count":
                            total_usages[key] = total_usages.get(key, 0) + val
                usages_by_type = {"all": {"consumer_count": total_count, **total_usages}}

            resp = flask.jsonify({"usages": usages_by_type})
        else:
            # Pre-1.38 behavior: simple aggregated usages
            query = """
                MATCH (c:Consumer)-[:OWNED_BY]->(proj:Project {external_id: $project_id})
            """
            params = {"project_id": project_id}

            if user_id:
                query += """
                MATCH (c)-[:CREATED_BY]->(u:User {external_id: $user_id})
                """
                params["user_id"] = user_id

            query += """
                MATCH (c)-[alloc:CONSUMES]->(inv)-[:OF_CLASS]->(rc:ResourceClass)
                RETURN rc.name AS rc, COALESCE(sum(alloc.used), 0) AS used
            """

            rows = session.run(query, **params)
            usages = {row["rc"]: int(row["used"]) for row in rows}
            resp = flask.jsonify({"usages": usages})

    return _add_cache_headers(resp), 200
