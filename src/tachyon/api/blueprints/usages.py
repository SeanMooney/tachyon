# SPDX-License-Identifier: Apache-2.0

"""Usages API blueprint.

Implements Placement-compatible usage reporting.
"""

from __future__ import annotations

from typing import Any

import flask
from oslo_log import log

from tachyon.api import errors

LOG = log.getLogger(__name__)

bp = flask.Blueprint("usages", __name__)


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

    :param rp_uuid: Resource provider UUID
    :returns: Tuple of (response, status_code)
    """
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

    return flask.jsonify(
        {
            "resource_provider_generation": provider["rp"].get("generation", 0),
            "usages": usages,
        }
    ), 200


@bp.route("/usages", methods=["GET"])
def project_usages() -> tuple[flask.Response, int]:
    """Get resource usages for a project.

    Query Parameters:
        project_id: Required. Project ID to get usages for.

    Returns the sum of allocations for all consumers owned by the project.

    :returns: Tuple of (response, status_code)
    """
    project_id = flask.request.args.get("project_id")

    if not project_id:
        raise errors.BadRequest("'project_id' is a required query parameter.")

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

    return flask.jsonify({"usages": usages}), 200
