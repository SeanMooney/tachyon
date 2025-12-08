"""Resource Classes API blueprint.

Implements Placement-compatible resource class management.
"""

from __future__ import annotations

from flask import Blueprint, Response, jsonify

from tachyon.api.errors import BadRequest, Conflict, NotFound

bp = Blueprint("resource_classes", __name__, url_prefix="/resource_classes")

# Standard resource classes (cannot be deleted)
STANDARD_RESOURCE_CLASSES = frozenset(
    {
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
    }
)


def _driver():
    """Get the Neo4j driver from the Flask app."""
    from tachyon.api.app import get_driver

    return get_driver()


def _is_custom(name: str) -> bool:
    """Check if a resource class name is custom (user-defined)."""
    return name.startswith("CUSTOM_")


@bp.route("", methods=["GET"])
def list_resource_classes() -> tuple[Response, int]:
    """List all resource classes."""
    with _driver().session() as session:
        rows = session.run(
            "MATCH (rc:ResourceClass) RETURN rc.name AS name ORDER BY name"
        )
        names = [r["name"] for r in rows]

    return jsonify({"resource_classes": names}), 200


@bp.route("/<string:name>", methods=["PUT"])
def create_resource_class(name: str) -> Response:
    """Create a custom resource class.

    Custom resource classes must start with 'CUSTOM_'.
    Standard resource classes are pre-defined and cannot be created.
    """
    # Validate name format
    if not name.isupper():
        raise BadRequest(f"Resource class name '{name}' must be uppercase.")

    if not _is_custom(name) and name not in STANDARD_RESOURCE_CLASSES:
        raise BadRequest(
            f"Resource class '{name}' must start with 'CUSTOM_' "
            "or be a standard resource class."
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

    return Response(status=204)


@bp.route("/<string:name>", methods=["GET"])
def get_resource_class(name: str) -> tuple[Response, int]:
    """Get a specific resource class."""
    with _driver().session() as session:
        result = session.run(
            "MATCH (rc:ResourceClass {name: $name}) RETURN rc",
            name=name,
        ).single()

        if not result:
            raise NotFound(f"Resource class {name} not found.")

    return jsonify({"name": name}), 200


@bp.route("/<string:name>", methods=["DELETE"])
def delete_resource_class(name: str) -> Response:
    """Delete a custom resource class.

    Standard resource classes cannot be deleted.
    Resource classes with inventory cannot be deleted.
    """
    with _driver().session() as session:
        # First check if exists (Placement API expects 404 for nonexistent)
        exists = session.run(
            "MATCH (rc:ResourceClass {name: $name}) RETURN rc",
            name=name,
        ).single()

        if not exists:
            raise NotFound(f"Resource class {name} not found.")

        # Then check if it's a standard or non-custom class
        if name in STANDARD_RESOURCE_CLASSES:
            raise BadRequest(f"Cannot delete standard resource class '{name}'.")

        if not _is_custom(name):
            raise BadRequest(f"Cannot delete non-custom resource class '{name}'.")

        # Check if in use by any inventory
        in_use = session.run(
            """
            MATCH (:Inventory)-[:OF_CLASS]->(rc:ResourceClass {name: $name})
            RETURN count(*) AS cnt
            """,
            name=name,
        ).single()

        if in_use and in_use["cnt"] > 0:
            raise Conflict(
                f"Resource class {name} is in use by {in_use['cnt']} "
                "inventory record(s) and cannot be deleted."
            )

        session.run(
            "MATCH (rc:ResourceClass {name: $name}) DELETE rc",
            name=name,
        )

    return Response(status=204)
