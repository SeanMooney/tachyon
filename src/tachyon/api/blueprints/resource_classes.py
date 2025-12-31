# SPDX-License-Identifier: Apache-2.0

"""Resource Classes API blueprint.

Implements Placement-compatible resource class management.
"""

from __future__ import annotations

import flask

from tachyon.api import errors

bp = flask.Blueprint("resource_classes", __name__, url_prefix="/resource_classes")

# Standard resource classes (cannot be deleted)
STANDARD_RESOURCE_CLASSES = frozenset({
    "VCPU",
    "MEMORY_MB",
    "DISK_GB",
    "PCI_DEVICE",
    "SRIOV_NET_VF",
    "NUMA_SOCKET",
    "NUMA_CORE",
    "NUMA_THREAD",
    "NUMA_MEMORY_MB",
    "NET_BW_IGR_KILOBIT_PER_SEC",
    "NET_BW_EGR_KILOBIT_PER_SEC",
    "PCPU",
    "VGPU",
    "VGPU_DISPLAY_HEAD",
    "FPGA",
    "MEM_ENCRYPTION_CONTEXT",
})


def _driver():
    """Get the Neo4j driver from the Flask app.

    :returns: Neo4j driver instance
    """
    from tachyon.api import app
    return app.get_driver()


def _is_custom(name):
    """Check if a resource class name is custom (user-defined).

    :param name: Resource class name
    :returns: True if custom resource class
    """
    return name.startswith("CUSTOM_")


@bp.route("", methods=["GET"])
def list_resource_classes():
    """List all resource classes.

    :returns: Tuple of (response, status_code)
    """
    with _driver().session() as session:
        rows = session.run(
            "MATCH (rc:ResourceClass) RETURN rc.name AS name ORDER BY name"
        )
        names = [r["name"] for r in rows]

    return flask.jsonify({"resource_classes": names}), 200


@bp.route("/<string:name>", methods=["PUT"])
def create_resource_class(name):
    """Create a custom resource class.

    Custom resource classes must start with 'CUSTOM_'.
    Standard resource classes are pre-defined and cannot be created.

    :param name: Resource class name
    :returns: Response with status 204
    """
    # Validate name format
    if not name.isupper():
        raise errors.BadRequest(
            "Resource class name '%s' must be uppercase." % name
        )

    if not _is_custom(name) and name not in STANDARD_RESOURCE_CLASSES:
        raise errors.BadRequest(
            "Resource class '%s' must start with 'CUSTOM_' "
            "or be a standard resource class." % name
        )

    with _driver().session() as session:
        session.run(
            """
            MERGE (rc:ResourceClass {name: $name})
            ON CREATE SET rc.created_at = datetime(), rc.updated_at = datetime()
            ON MATCH SET rc.updated_at = datetime()
            """,
            name=name,
        )

    return flask.Response(status=204)


@bp.route("/<string:name>", methods=["GET"])
def get_resource_class(name):
    """Get a specific resource class.

    :param name: Resource class name
    :returns: Tuple of (response, status_code)
    """
    with _driver().session() as session:
        result = session.run(
            "MATCH (rc:ResourceClass {name: $name}) RETURN rc",
            name=name,
        ).single()

        if not result:
            raise errors.NotFound("Resource class %s not found." % name)

    return flask.jsonify({"name": name}), 200


@bp.route("/<string:name>", methods=["DELETE"])
def delete_resource_class(name):
    """Delete a custom resource class.

    Standard resource classes cannot be deleted.
    Resource classes with inventory cannot be deleted.

    :param name: Resource class name
    :returns: Response with status 204
    """
    with _driver().session() as session:
        # First check if exists (Placement API expects 404 for nonexistent)
        exists = session.run(
            "MATCH (rc:ResourceClass {name: $name}) RETURN rc",
            name=name,
        ).single()

        if not exists:
            raise errors.NotFound("Resource class %s not found." % name)

        # Then check if it's a standard or non-custom class
        if name in STANDARD_RESOURCE_CLASSES:
            raise errors.BadRequest(
                "Cannot delete standard resource class '%s'." % name
            )

        if not _is_custom(name):
            raise errors.BadRequest(
                "Cannot delete non-custom resource class '%s'." % name
            )

        # Check if in use by any inventory
        in_use = session.run(
            """
            MATCH (:Inventory)-[:OF_CLASS]->(rc:ResourceClass {name: $name})
            RETURN count(*) AS cnt
            """,
            name=name,
        ).single()

        if in_use and in_use["cnt"] > 0:
            raise errors.Conflict(
                "Resource class %s is in use by %d "
                "inventory record(s) and cannot be deleted."
                % (name, in_use["cnt"])
            )

        session.run(
            "MATCH (rc:ResourceClass {name: $name}) DELETE rc",
            name=name,
        )

    return flask.Response(status=204)
