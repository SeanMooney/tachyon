# SPDX-License-Identifier: Apache-2.0

"""Allocation Candidates API blueprint.

Implements Placement-compatible allocation candidate queries for scheduling.
"""

from __future__ import annotations

import datetime
import re
import uuid as uuid_module
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import flask
import os_resource_classes as orc

from oslo_log import log

from tachyon.api import errors
from tachyon.api import microversion
from tachyon.policies import allocation_candidate as ac_policies

LOG = log.getLogger(__name__)


@dataclass
class RequestGroup:
    """Represents a single request group with its constraints.

    Used to collect per-suffix constraints for granular resource requests.
    The suffix is "" for the unnumbered group, or "1", "2", "_COMPUTE", etc.
    """

    suffix: str
    resources: dict[str, int] = field(default_factory=dict)
    required_traits: list[str] = field(default_factory=list)
    forbidden_traits: list[str] = field(default_factory=list)
    any_of_trait_groups: list[list[str]] = field(default_factory=list)
    required_aggregates: list[list[str]] = field(default_factory=list)
    forbidden_aggregates: list[str] = field(default_factory=list)
    in_tree: str | None = None

    def to_cypher_dict(self) -> dict[str, Any]:
        """Convert to a dict suitable for passing as Cypher parameter."""
        return {
            "suffix": self.suffix,
            "resources": [
                {"rc": rc, "amount": amount}
                for rc, amount in self.resources.items()
            ],
            "required_traits": self.required_traits,
            "forbidden_traits": self.forbidden_traits,
            "member_of": [agg for agg_group in self.required_aggregates for agg in agg_group],
            "in_tree": self.in_tree,
        }

bp = flask.Blueprint(
    "allocation_candidates", __name__, url_prefix="/allocation_candidates"
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


def _parse_resources(resources_str: str) -> dict[str, int]:
    """Parse resources query parameter.

    Format: CLASS1:AMOUNT1,CLASS2:AMOUNT2,...

    :param resources_str: Resources string to parse
    :returns: Dict mapping resource class names to amounts
    :raises errors.BadRequest: If format is invalid
    """
    if not resources_str:
        raise errors.BadRequest(
            "Badly formed resources parameter. Expected resources query string "
            "parameter in form: VCPU:1,MEMORY_MB:2048. "
            "Got: empty string."
        )

    result: dict[str, int] = {}
    for part in resources_str.split(","):
        if ":" not in part:
            raise errors.BadRequest(
                "Badly formed resources parameter. Expected resources query "
                "string parameter in form: VCPU:1,MEMORY_MB:2048. Got: %s"
                % resources_str
            )
        rc, amount_str = part.split(":", 1)
        try:
            amount = int(amount_str)
        except ValueError:
            raise errors.BadRequest(
                "Badly formed resources parameter. Expected resources query "
                "string parameter in form: VCPU:1,MEMORY_MB:2048. Got: %s"
                % resources_str
            )
        result[rc] = amount

    return result


def _parse_required_traits(
    traits_str: str, mv: microversion.Microversion
) -> tuple[list[str], list[str], list[list[str]]]:
    """Parse the required query parameter into required, forbidden, and any-of traits.

    Format: TRAIT1,TRAIT2,!TRAIT3,!TRAIT4,in:TRAIT5,TRAIT6
    - Traits without prefix are required (must all be present)
    - Traits with ! prefix are forbidden (must not be present) - only at 1.22+
    - Traits with in: prefix (1.39+) are any-of (at least one must be present)

    :param traits_str: Comma-separated traits string
    :param mv: Microversion for validation rules
    :returns: Tuple of (required_traits, forbidden_traits, any_of_groups)
        any_of_groups is a list of lists, where each inner list is an OR group
    :raises errors.BadRequest: If format is invalid
    """
    # Determine expected format based on microversion
    if mv.is_at_least(39):
        expected_form = "HW_CPU_X86_VMX,!CUSTOM_MAGIC,in:TRAIT1,TRAIT2."
    elif mv.is_at_least(22):
        expected_form = "HW_CPU_X86_VMX,!CUSTOM_MAGIC."
    else:
        expected_form = "HW_CPU_X86_VMX,CUSTOM_MAGIC."

    def _invalid(got: str | None = None) -> None:
        suffix = " Got: %s" % got if got is not None else ""
        raise errors.BadRequest(
            "Invalid query string parameters: Expected 'required' "
            "parameter value of the form: %s%s" % (expected_form, suffix)
        )

    if traits_str == "":
        _invalid()

    required: list[str] = []
    forbidden: list[str] = []
    any_of_groups: list[list[str]] = []

    # Check for any-of syntax (in:TRAIT1,TRAIT2) first
    # The in: prefix applies to the entire comma-separated list after it
    if traits_str.startswith("in:"):
        if not mv.is_at_least(39):
            _invalid(traits_str)
        # Parse the traits after 'in:'
        any_of_str = traits_str[3:]
        if not any_of_str:
            _invalid()
        any_of_traits = [t.strip() for t in any_of_str.split(",")]
        if any(t == "" for t in any_of_traits):
            _invalid()
        any_of_groups.append(any_of_traits)
        return required, forbidden, any_of_groups

    tokens = [t.strip() for t in traits_str.split(",")]
    if any(t == "" for t in tokens):
        _invalid()

    for token in tokens:
        if token.startswith("!"):
            if not mv.is_at_least(22):
                _invalid(traits_str)
            if len(token) == 1:
                _invalid()
            forbidden.append(token[1:])
        elif token.startswith("in:"):
            if not mv.is_at_least(39):
                _invalid(traits_str)
            # For inline in: syntax, we'd need more complex parsing
            # but for now handle the simple case where in: is the whole value
            raise errors.BadRequest(
                "Invalid query string parameters: 'in:' must be at the start "
                "of the required parameter value"
            )
        else:
            required.append(token)

    return required, forbidden, any_of_groups


def _parse_traits(traits_str: str) -> tuple[list[str], list[str]]:
    """Parse a traits query parameter into required and forbidden lists.

    This is a lenient parser used for root_required parameter.
    Format: TRAIT1,TRAIT2,!TRAIT3,!TRAIT4
    - Traits without prefix are required (must be present)
    - Traits with ! prefix are forbidden (must not be present)

    :param traits_str: Comma-separated traits string
    :returns: Tuple of (required_traits, forbidden_traits)
    """
    if not traits_str:
        return [], []

    required: list[str] = []
    forbidden: list[str] = []

    for trait in traits_str.split(","):
        trait = trait.strip()
        if not trait:
            continue
        if trait.startswith("!"):
            forbidden.append(trait[1:])
        else:
            required.append(trait)

    return required, forbidden


def _validate_traits_exist(
    session: Any, traits: list[str]
) -> None:
    """Validate that all traits exist in the database.

    :param session: Neo4j session
    :param traits: List of trait names to validate
    :raises errors.BadRequest: If any trait doesn't exist
    """
    if not traits:
        return

    result = session.run(
        "MATCH (t:Trait) WHERE t.name IN $names RETURN t.name AS name",
        names=traits,
    )
    existing = {row["name"] for row in result}
    missing = set(traits) - existing

    if missing:
        raise errors.BadRequest("No such trait(s): %s" % ", ".join(sorted(missing)))


def _parse_member_of(
    member_of_params: list[str], mv: microversion.Microversion
) -> tuple[list[list[str]], list[str]]:
    """Parse member_of query parameters.

    Supports formats:
        - Single UUID: <uuid>
        - With 'in:' prefix: in:<uuid1>,<uuid2>,... (any of these aggregates)
        - Negative (1.32+): !in:<uuid1>,<uuid2>,... (not in these aggregates)

    :param member_of_params: List of member_of parameter values
    :param mv: Microversion for validation rules
    :returns: Tuple of (required_aggregates, forbidden_aggregates)
        required_aggregates is a list of lists (AND of ORs)
        forbidden_aggregates is a flat list
    :raises errors.BadRequest: If format is invalid
    """
    required: list[list[str]] = []
    forbidden: list[str] = []

    for value in member_of_params:
        is_forbidden = False

        # Check for forbidden prefix (1.32+)
        if value.startswith("!"):
            if not mv.is_at_least(32):
                raise errors.BadRequest(
                    "Invalid query string parameters: "
                    "Forbidden aggregate filters require microversion 1.32+"
                )
            is_forbidden = True
            value = value[1:]

        # Check for 'in:' prefix
        if value.startswith("in:"):
            uuid_str = value[3:]
        else:
            uuid_str = value

        # Parse and validate UUIDs
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

        if not aggregates:
            raise errors.BadRequest(
                "Invalid query string parameters: Expected 'member_of' "
                "parameter to contain valid UUID(s)."
            )

        if is_forbidden:
            forbidden.extend(aggregates)
        else:
            required.append(aggregates)

    return required, forbidden


def _filter_by_aggregates(
    session: Any,
    providers: list[dict[str, Any]],
    required_aggregates: list[list[str]],
    forbidden_aggregates: list[str],
) -> list[dict[str, Any]]:
    """Filter providers by aggregate membership.

    :param session: Neo4j session
    :param providers: List of provider dicts with uuid
    :param required_aggregates: List of aggregate UUID lists (AND of ORs)
    :param forbidden_aggregates: List of forbidden aggregate UUIDs
    :returns: Filtered list of providers
    """
    if not required_aggregates and not forbidden_aggregates:
        return providers

    provider_uuids = [p["uuid"] for p in providers]
    if not provider_uuids:
        return providers

    # Query to get aggregate membership for each provider
    result = session.run(
        """
        UNWIND $uuids AS rp_uuid
        MATCH (rp:ResourceProvider {uuid: rp_uuid})
        OPTIONAL MATCH (rp)-[:MEMBER_OF]->(agg:Aggregate)
        WITH rp.uuid AS provider_uuid, collect(agg.uuid) AS aggregate_uuids
        RETURN provider_uuid, aggregate_uuids
        """,
        uuids=provider_uuids,
    )

    # Build a map of provider uuid -> aggregate uuids
    agg_map: dict[str, set[str]] = {}
    for row in result:
        agg_map[row["provider_uuid"]] = set(row["aggregate_uuids"] or [])

    # Filter providers based on aggregate requirements
    filtered: list[dict[str, Any]] = []
    forbidden_set = set(forbidden_aggregates)

    for provider in providers:
        uuid = provider["uuid"]
        provider_aggs = agg_map.get(uuid, set())

        # Check required aggregates (provider must be in at least one from each group)
        matches_required = True
        for agg_group in required_aggregates:
            if not provider_aggs.intersection(agg_group):
                matches_required = False
                break

        if not matches_required:
            continue

        # Check forbidden aggregates (provider must not be in any)
        if forbidden_set and provider_aggs.intersection(forbidden_set):
            continue

        filtered.append(provider)

    return filtered


# Trait that identifies sharing providers
MISC_SHARES_VIA_AGGREGATE = "MISC_SHARES_VIA_AGGREGATE"


def _find_sharing_providers(
    session: Any,
    tree_provider_uuid: str,
    required_resources: dict[str, int],
) -> list[dict[str, Any]]:
    """Find sharing providers that can satisfy requested resources.

    A sharing provider is one that:
    1. Has the MISC_SHARES_VIA_AGGREGATE trait
    2. Has inventory for the requested resource with sufficient capacity
    3. Is in the same aggregate as any provider in the tree containing tree_provider_uuid

    :param session: Neo4j session
    :param tree_provider_uuid: UUID of a provider in the target tree
    :param required_resources: Dict of resource_class -> amount needed
    :returns: List of sharing provider dicts with uuid, resources, and capacity info
    """
    if not required_resources:
        return []

    # Find all sharing providers that:
    # 1. Have the MISC_SHARES_VIA_AGGREGATE trait
    # 2. Are in the same aggregate as any provider in the tree
    # 3. Have capacity for all requested resources
    result = session.run(
        """
        // Find the root of the tree containing the given provider
        MATCH (tree_provider:ResourceProvider {uuid: $tree_provider_uuid})
        OPTIONAL MATCH path = (root:ResourceProvider)-[:PARENT_OF*0..]->(tree_provider)
        WHERE NOT EXISTS { MATCH (:ResourceProvider)-[:PARENT_OF]->(root) }
        WITH COALESCE(root, tree_provider) AS tree_root

        // Find all providers in this tree
        MATCH (tree_root)-[:PARENT_OF*0..]->(tree_member:ResourceProvider)

        // Find aggregates that any tree member belongs to
        MATCH (tree_member)-[:MEMBER_OF]->(agg:Aggregate)

        // Find sharing providers in the same aggregates
        MATCH (sp:ResourceProvider)-[:MEMBER_OF]->(agg)
        WHERE sp <> tree_member
          AND EXISTS {
            MATCH (sp)-[:HAS_TRAIT]->(t:Trait {name: $sharing_trait})
          }

        RETURN DISTINCT sp.uuid AS uuid, sp.generation AS generation
        """,
        tree_provider_uuid=tree_provider_uuid,
        sharing_trait=MISC_SHARES_VIA_AGGREGATE,
    )

    sharing_providers: list[dict[str, Any]] = []
    for row in result:
        sp_uuid = row["uuid"]
        sp_gen = row["generation"]

        # Check if this sharing provider has capacity for all requested resources
        has_all_resources = True
        sp_resources: dict[str, dict[str, Any]] = {}

        for rc_name, amount in required_resources.items():
            cap_result = session.run(
                """
                MATCH (sp:ResourceProvider {uuid: $sp_uuid})
                      -[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(rc:ResourceClass {name: $rc})
                OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
                WITH sp, inv, rc,
                     COALESCE(sum(alloc.used), 0) AS used,
                     inv.total AS total,
                     COALESCE(inv.reserved, 0) AS reserved,
                     COALESCE(inv.allocation_ratio, 1.0) AS allocation_ratio,
                     COALESCE(inv.min_unit, 1) AS min_unit,
                     COALESCE(inv.max_unit, inv.total) AS max_unit,
                     COALESCE(inv.step_size, 1) AS step_size
                WITH sp, inv, rc.name AS rc_name,
                     (total - reserved) * allocation_ratio - used AS available,
                     total, reserved, used, allocation_ratio, min_unit, max_unit, step_size
                WHERE available >= $amount
                  AND $amount >= min_unit
                  AND $amount <= max_unit
                  AND ($amount - min_unit) % step_size = 0
                RETURN rc_name, total, reserved, used, allocation_ratio,
                       (total - reserved) * allocation_ratio AS capacity
                """,
                sp_uuid=sp_uuid,
                rc=rc_name,
                amount=amount,
            )
            cap_row = cap_result.single()
            if not cap_row:
                has_all_resources = False
                break

            sp_resources[rc_name] = {
                "total": cap_row["total"],
                "reserved": cap_row["reserved"],
                "used": cap_row["used"],
                "allocation_ratio": cap_row["allocation_ratio"],
                "capacity": int(cap_row["capacity"]),
            }

        if has_all_resources:
            sharing_providers.append({
                "uuid": sp_uuid,
                "generation": sp_gen,
                "resources": sp_resources,
                "is_sharing": True,
            })

    return sharing_providers


def _get_tree_aggregates(session: Any, tree_provider_uuid: str) -> set[str]:
    """Get all aggregate UUIDs that any provider in the tree belongs to.

    :param session: Neo4j session
    :param tree_provider_uuid: UUID of any provider in the tree
    :returns: Set of aggregate UUIDs
    """
    result = session.run(
        """
        MATCH (tree_provider:ResourceProvider {uuid: $uuid})
        OPTIONAL MATCH path = (root:ResourceProvider)-[:PARENT_OF*0..]->(tree_provider)
        WHERE NOT EXISTS { MATCH (:ResourceProvider)-[:PARENT_OF]->(root) }
        WITH COALESCE(root, tree_provider) AS tree_root
        MATCH (tree_root)-[:PARENT_OF*0..]->(member:ResourceProvider)
        MATCH (member)-[:MEMBER_OF]->(agg:Aggregate)
        RETURN DISTINCT agg.uuid AS agg_uuid
        """,
        uuid=tree_provider_uuid,
    )
    return {row["agg_uuid"] for row in result}


def _filter_by_in_tree(
    session: Any,
    providers: list[dict[str, Any]],
    in_tree_uuid: str,
) -> list[dict[str, Any]]:
    """Filter providers to only those in the specified tree.

    :param session: Neo4j session
    :param providers: List of provider dicts with uuid
    :param in_tree_uuid: UUID of the root provider of the tree to filter by
    :returns: Filtered list of providers within the tree
    """
    if not in_tree_uuid:
        return providers

    provider_uuids = [p["uuid"] for p in providers]
    if not provider_uuids:
        return providers

    # Query to find providers that are in the same tree as in_tree_uuid
    # A provider is in the tree if:
    # 1. It is the root itself
    # 2. It is a descendant of the root
    result = session.run(
        """
        UNWIND $uuids AS rp_uuid
        MATCH (rp:ResourceProvider {uuid: rp_uuid})
        // Find root of this provider's tree
        OPTIONAL MATCH path = (root:ResourceProvider)-[:PARENT_OF*0..]->(rp)
        WHERE NOT EXISTS { MATCH (:ResourceProvider)-[:PARENT_OF]->(root) }
        WITH rp, COALESCE(root, rp) AS tree_root
        WHERE tree_root.uuid = $in_tree_uuid
        RETURN rp.uuid AS provider_uuid
        """,
        uuids=provider_uuids,
        in_tree_uuid=in_tree_uuid,
    )

    # Build set of providers that are in the tree
    in_tree_providers = {row["provider_uuid"] for row in result}

    # Filter to only include providers in the tree
    return [p for p in providers if p["uuid"] in in_tree_providers]


def _filter_by_provider_traits(
    session: Any,
    providers: list[dict[str, Any]],
    required_traits: list[str],
    forbidden_traits: list[str],
    any_of_groups: list[list[str]] | None = None,
) -> list[dict[str, Any]]:
    """Filter providers by traits on the providers themselves.

    :param session: Neo4j session
    :param providers: List of provider dicts with uuid
    :param required_traits: Traits the provider must have (all of them)
    :param forbidden_traits: Traits the provider must not have (none of them)
    :param any_of_groups: List of trait groups where provider must have at least
        one trait from each group (1.39+)
    :returns: Filtered list of providers
    """
    if not required_traits and not forbidden_traits and not any_of_groups:
        return providers

    provider_uuids = [p["uuid"] for p in providers]
    if not provider_uuids:
        return providers

    # Query to get traits for each provider
    result = session.run(
        """
        UNWIND $uuids AS rp_uuid
        MATCH (rp:ResourceProvider {uuid: rp_uuid})
        OPTIONAL MATCH (rp)-[:HAS_TRAIT]->(t:Trait)
        WITH rp.uuid AS provider_uuid, collect(t.name) AS traits
        RETURN provider_uuid, traits
        """,
        uuids=provider_uuids,
    )

    # Build a map of provider uuid -> traits
    traits_map: dict[str, set[str]] = {}
    for row in result:
        traits_map[row["provider_uuid"]] = set(row["traits"] or [])

    # Filter providers based on trait requirements
    filtered: list[dict[str, Any]] = []
    required_set = set(required_traits)
    forbidden_set = set(forbidden_traits)

    for provider in providers:
        uuid = provider["uuid"]
        provider_traits = traits_map.get(uuid, set())

        # Check required traits (provider must have all of them)
        if required_set and not required_set.issubset(provider_traits):
            continue

        # Check forbidden traits (provider must have none of them)
        if forbidden_set and forbidden_set.intersection(provider_traits):
            continue

        # Check any-of groups (provider must have at least one trait from each group)
        if any_of_groups:
            matches_all_groups = True
            for group in any_of_groups:
                group_set = set(group)
                if not provider_traits.intersection(group_set):
                    matches_all_groups = False
                    break
            if not matches_all_groups:
                continue

        filtered.append(provider)

    return filtered


def _validate_resource_classes(session: Any, resource_classes: list[str]) -> None:
    """Check that all resource classes exist.

    :param session: Neo4j session
    :param resource_classes: List of resource class names
    :raises errors.BadRequest: If any resource class doesn't exist
    """
    # Standard resource classes from os-resource-classes library
    STANDARD_RCS = set(orc.STANDARDS)

    for rc in resource_classes:
        # Standard classes and custom classes (CUSTOM_ prefix) are implicitly valid
        if rc in STANDARD_RCS or orc.is_custom(rc):
            continue

        result = session.run(
            "MATCH (rc:ResourceClass {name: $name}) RETURN rc",
            name=rc,
        ).single()

        if not result:
            raise errors.BadRequest(
                "Invalid resource class in resources parameter: %s" % rc
            )


def _get_granular_allocation_candidates(
    session: Any,
    groups: list[dict[str, Any]],
    group_policy: str | None,
    same_subtree_groups: list[list[str]] | None,
    root_required_traits: list[str],
    root_forbidden_traits: list[str],
    limit: int | None,
) -> list[dict[str, Any]]:
    """Find allocation candidates for granular resource requests.

    This executes a single Neo4j query that handles:
    - Per-group resource, trait, and aggregate constraints
    - group_policy enforcement (isolate: numbered groups use different providers)
    - same_subtree enforcement (specified groups share common ancestor)

    :param session: Neo4j session
    :param groups: List of group dicts with resources, traits, aggregates, in_tree
    :param group_policy: 'none' or 'isolate'
    :param same_subtree_groups: List of suffix lists that must share ancestor
    :param root_required_traits: Traits required on root provider
    :param root_forbidden_traits: Traits forbidden on root provider
    :param limit: Maximum number of candidates to return
    :returns: List of allocation candidate dicts with provider mappings per group
    """
    if not groups:
        return []

    # Normalize same_subtree_groups to use consistent suffix format
    # same_subtree uses _SUFFIX format (e.g., _1, _2) but our groups use
    # just the suffix (e.g., "1", "2", "" for unnumbered)
    normalized_same_subtree: list[list[str]] = []
    if same_subtree_groups:
        for stg in same_subtree_groups:
            normalized = []
            for suffix in stg:
                # Strip leading underscore if present for matching
                if suffix.startswith("_"):
                    normalized.append(suffix[1:])
                else:
                    normalized.append(suffix)
            normalized_same_subtree.append(normalized)

    # Build the Cypher query for granular allocation candidates
    # This query:
    # 1. Finds root providers that satisfy root-level constraints
    # 2. For each group, finds providers in the tree that satisfy group constraints
    # 3. Applies group_policy (isolate) constraint
    # 4. Applies same_subtree constraint
    query = """
    // Find root providers (compute hosts)
    MATCH (root:ResourceProvider)
    WHERE NOT ()-[:PARENT_OF]->(root)
      AND COALESCE(root.disabled, false) = false
      // Root-level trait constraints
      AND ($root_required = [] OR ALL(t IN $root_required WHERE
        EXISTS { MATCH (root)-[:HAS_TRAIT]->(:Trait {name: t}) }
      ))
      AND ($root_forbidden = [] OR NONE(t IN $root_forbidden WHERE
        EXISTS { MATCH (root)-[:HAS_TRAIT]->(:Trait {name: t}) }
      ))

    // For each request group, find matching providers
    WITH root
    UNWIND $groups AS grp

    // Find providers in the tree that can satisfy this group
    MATCH (root)-[:PARENT_OF*0..]->(provider:ResourceProvider)
    WHERE
      // Per-group trait constraints
      (grp.required_traits = [] OR ALL(t IN grp.required_traits WHERE
        EXISTS { MATCH (provider)-[:HAS_TRAIT]->(:Trait {name: t}) }
      ))
      AND (grp.forbidden_traits = [] OR NONE(t IN grp.forbidden_traits WHERE
        EXISTS { MATCH (provider)-[:HAS_TRAIT]->(:Trait {name: t}) }
      ))
      // Per-group aggregate constraints
      AND (grp.member_of = [] OR EXISTS {
        MATCH (provider)-[:MEMBER_OF]->(agg:Aggregate)
        WHERE agg.uuid IN grp.member_of
      })
      // Per-group in_tree constraint
      AND (grp.in_tree IS NULL OR provider.uuid = grp.in_tree OR EXISTS {
        MATCH (tree_root:ResourceProvider {uuid: grp.in_tree})-[:PARENT_OF*0..]->(provider)
      })

    // Check that provider has inventory for all resources in this group
    // Also validates inventory constraints: min_unit, max_unit, step_size
    WITH root, grp, provider
    WHERE size(grp.resources) = 0 OR ALL(req IN grp.resources WHERE
      EXISTS {
        MATCH (provider)-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(rc:ResourceClass {name: req.rc})
        OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
        WITH inv, COALESCE(SUM(alloc.used), 0) AS used,
             COALESCE(inv.min_unit, 1) AS min_unit,
             COALESCE(inv.max_unit, inv.total) AS max_unit,
             COALESCE(inv.step_size, 1) AS step_size,
             req.amount AS amount
        WHERE (inv.total - COALESCE(inv.reserved, 0)) * COALESCE(inv.allocation_ratio, 1.0) - used >= amount
          AND amount >= min_unit
          AND amount <= max_unit
          AND (amount - min_unit) % step_size = 0
      }
    )

    // Collect valid providers per group per root
    WITH root, grp.suffix AS suffix, collect(DISTINCT provider) AS group_providers
    WHERE size(group_providers) > 0 OR size($groups) = 0

    // Collect all groups for this root
    WITH root, collect({suffix: suffix, providers: group_providers}) AS groups_data

    // Ensure we found providers for ALL requested groups
    WHERE size(groups_data) = size($groups)

    // Generate combinations: pick one provider per group
    // For simplicity, we'll return all valid combinations for the root
    // using a REDUCE pattern to build cross-product
    WITH root, groups_data,
         // Extract just the first valid provider per group for now
         // Full cross-product would require APOC or recursive query
         [g IN groups_data | {
           suffix: g.suffix,
           provider_uuid: g.providers[0].uuid,
           provider_gen: g.providers[0].generation
         }] AS combination

    // Apply group_policy=isolate check
    // All numbered groups (suffix != '') must use different providers
    WITH root, combination, groups_data,
         [c IN combination WHERE c.suffix <> '' | c.provider_uuid] AS numbered_uuids
    WHERE $group_policy <> 'isolate' OR
          size(numbered_uuids) = 0 OR
          size(numbered_uuids) = size(apoc.coll.toSet(numbered_uuids))

    // Apply same_subtree constraints
    // For each same_subtree group, verify providers share common ancestor
    WITH root, combination, groups_data
    WHERE size($same_subtree_groups) = 0 OR ALL(stg IN $same_subtree_groups WHERE
      // Get providers for suffixes in this subtree group
      size([c IN combination WHERE c.suffix IN stg]) < 2 OR
      // Check they share a common ancestor (simplest: they're in the same tree = root)
      // More precise: find actual common ancestor
      size(apoc.coll.toSet([c IN combination WHERE c.suffix IN stg | c.provider_uuid])) <= 1 OR
      EXISTS {
        WITH [c IN combination WHERE c.suffix IN stg | c.provider_uuid] AS st_uuids
        MATCH (root)-[:PARENT_OF*0..]->(ancestor)-[:PARENT_OF*0..]->(p:ResourceProvider)
        WHERE p.uuid IN st_uuids
        WITH ancestor, collect(DISTINCT p.uuid) AS covered, st_uuids
        WHERE size(covered) = size(st_uuids)
      }
    )

    RETURN root.uuid AS root_uuid,
           root.generation AS root_generation,
           combination AS allocation_data,
           groups_data
    LIMIT $limit
    """

    # Handle limit - Neo4j needs a non-null value
    effective_limit = limit if limit else 1000

    try:
        result = session.run(
            query,
            groups=[g if isinstance(g, dict) else g.to_cypher_dict()
                    if hasattr(g, 'to_cypher_dict') else g
                    for g in groups],
            group_policy=group_policy or "none",
            same_subtree_groups=normalized_same_subtree,
            root_required=root_required_traits,
            root_forbidden=root_forbidden_traits,
            limit=effective_limit,
        )

        candidates = []
        for row in result:
            candidates.append({
                "root_uuid": row["root_uuid"],
                "root_generation": row["root_generation"],
                "allocation_data": row["allocation_data"],
                "groups_data": row["groups_data"],
            })

        return candidates

    except Exception as e:
        # If the query fails (e.g., APOC not available), fall back to simpler approach
        LOG.warning("Granular query failed, using fallback: %s", e)
        return _get_granular_allocation_candidates_fallback(
            session, groups, group_policy, same_subtree_groups,
            root_required_traits, root_forbidden_traits, limit
        )


def _get_granular_allocation_candidates_fallback(
    session: Any,
    groups: list[dict[str, Any]],
    group_policy: str | None,
    same_subtree_groups: list[list[str]] | None,
    root_required_traits: list[str],
    root_forbidden_traits: list[str],
    limit: int | None,
) -> list[dict[str, Any]]:
    """Fallback implementation without APOC for granular allocation candidates.

    This queries each group separately and combines results in Python,
    but still pushes most filtering to Neo4j.
    """
    # Normalize same_subtree suffixes
    normalized_same_subtree: list[list[str]] = []
    if same_subtree_groups:
        for stg in same_subtree_groups:
            normalized = []
            for suffix in stg:
                if suffix.startswith("_"):
                    normalized.append(suffix[1:])
                else:
                    normalized.append(suffix)
            normalized_same_subtree.append(normalized)

    # Query to find valid providers per group within each root
    # Uses a simpler approach: filter by traits/aggregates first,
    # then check capacity separately for each resource
    base_query = """
    MATCH (root:ResourceProvider)
    WHERE NOT ()-[:PARENT_OF]->(root)
      AND COALESCE(root.disabled, false) = false
      AND ($root_required = [] OR ALL(t IN $root_required WHERE
        EXISTS { MATCH (root)-[:HAS_TRAIT]->(:Trait {name: t}) }
      ))
      AND ($root_forbidden = [] OR NONE(t IN $root_forbidden WHERE
        EXISTS { MATCH (root)-[:HAS_TRAIT]->(:Trait {name: t}) }
      ))

    WITH root
    MATCH (root)-[:PARENT_OF*0..]->(provider:ResourceProvider)
    WHERE
      ($required_traits = [] OR ALL(t IN $required_traits WHERE
        EXISTS { MATCH (provider)-[:HAS_TRAIT]->(:Trait {name: t}) }
      ))
      AND ($forbidden_traits = [] OR NONE(t IN $forbidden_traits WHERE
        EXISTS { MATCH (provider)-[:HAS_TRAIT]->(:Trait {name: t}) }
      ))
      AND ($member_of = [] OR EXISTS {
        MATCH (provider)-[:MEMBER_OF]->(agg:Aggregate)
        WHERE agg.uuid IN $member_of
      })
      AND ($in_tree IS NULL OR provider.uuid = $in_tree OR EXISTS {
        MATCH (tree_root:ResourceProvider {uuid: $in_tree})-[:PARENT_OF*0..]->(provider)
      })

    RETURN root.uuid AS root_uuid, root.generation AS root_generation,
           provider.uuid AS provider_uuid, provider.generation AS provider_generation
    """

    # Query for checking capacity for a single resource
    # Also validates inventory constraints: min_unit, max_unit, step_size
    capacity_query = """
    MATCH (provider:ResourceProvider {uuid: $provider_uuid})
          -[:HAS_INVENTORY]->(inv)
          -[:OF_CLASS]->(rc:ResourceClass {name: $rc})
    OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
    WITH inv,
         COALESCE(SUM(alloc.used), 0) AS used,
         (inv.total - COALESCE(inv.reserved, 0)) * COALESCE(inv.allocation_ratio, 1.0) AS capacity,
         COALESCE(inv.min_unit, 1) AS min_unit,
         COALESCE(inv.max_unit, inv.total) AS max_unit,
         COALESCE(inv.step_size, 1) AS step_size
    WHERE capacity - used >= $amount
      AND $amount >= min_unit
      AND $amount <= max_unit
      AND ($amount - min_unit) % step_size = 0
    RETURN capacity - used AS available
    """

    # Query each group separately
    groups_by_root: dict[str, dict[str, Any]] = {}

    for group in groups:
        g = group if isinstance(group, dict) else (
            group.to_cypher_dict() if hasattr(group, 'to_cypher_dict') else group
        )
        suffix = g.get("suffix", "")
        resources = g.get("resources", [])

        # First, get all providers that match trait/aggregate filters
        result = session.run(
            base_query,
            root_required=root_required_traits,
            root_forbidden=root_forbidden_traits,
            required_traits=g.get("required_traits", []),
            forbidden_traits=g.get("forbidden_traits", []),
            member_of=g.get("member_of", []),
            in_tree=g.get("in_tree"),
        )

        # Collect candidate providers per root
        candidates_by_root: dict[str, list[dict]] = {}
        for row in result:
            root_uuid = row["root_uuid"]
            if root_uuid not in candidates_by_root:
                candidates_by_root[root_uuid] = []
            candidates_by_root[root_uuid].append({
                "uuid": row["provider_uuid"],
                "generation": row["provider_generation"],
                "root_generation": row["root_generation"],
            })

        # Filter candidates by capacity for each resource
        for root_uuid, providers in candidates_by_root.items():
            valid_providers = []
            for prov in providers:
                has_capacity = True
                # Check capacity for each resource
                for req in resources:
                    cap_result = session.run(
                        capacity_query,
                        provider_uuid=prov["uuid"],
                        rc=req["rc"],
                        amount=req["amount"],
                    )
                    if not cap_result.single():
                        has_capacity = False
                        break

                if has_capacity or not resources:
                    valid_providers.append(prov)

            if valid_providers:
                if root_uuid not in groups_by_root:
                    groups_by_root[root_uuid] = {
                        "root_uuid": root_uuid,
                        "root_generation": valid_providers[0]["root_generation"],
                        "groups": {},
                    }
                groups_by_root[root_uuid]["groups"][suffix] = [
                    {"uuid": p["uuid"], "generation": p["generation"]}
                    for p in valid_providers
                ]

    # Build allocation candidates from the grouped results
    candidates = []
    for root_uuid, root_data in groups_by_root.items():
        # Check that all groups have providers for this root
        if len(root_data["groups"]) != len(groups):
            continue

        # For now, just pick the first provider from each group
        # Full cross-product would be done here if needed
        combination = []
        numbered_providers = []
        for group in groups:
            g = group if isinstance(group, dict) else (
                group.to_cypher_dict() if hasattr(group, 'to_cypher_dict') else group
            )
            suffix = g.get("suffix", "")
            providers = root_data["groups"].get(suffix, [])
            if not providers:
                continue
            provider = providers[0]
            combination.append({
                "suffix": suffix,
                "provider_uuid": provider["uuid"],
                "provider_gen": provider["generation"],
            })
            if suffix != "":
                numbered_providers.append(provider["uuid"])

        # Apply group_policy=isolate: numbered groups use different providers
        if group_policy == "isolate" and len(numbered_providers) > 0:
            if len(numbered_providers) != len(set(numbered_providers)):
                continue

        # Apply same_subtree constraints
        if normalized_same_subtree:
            valid = True
            for stg in normalized_same_subtree:
                stg_providers = [c["provider_uuid"] for c in combination if c["suffix"] in stg]
                if len(stg_providers) < 2:
                    continue
                # Check if they share common ancestor - for now, they're in same root tree
                # which is always true since we're iterating per root
                # More precise check would query ancestry
            if not valid:
                continue

        candidates.append({
            "root_uuid": root_uuid,
            "root_generation": root_data["root_generation"],
            "allocation_data": combination,
            "groups_data": [
                {"suffix": g.get("suffix", "") if isinstance(g, dict) else g.to_cypher_dict().get("suffix", ""),
                 "providers": root_data["groups"].get(
                     g.get("suffix", "") if isinstance(g, dict) else g.to_cypher_dict().get("suffix", ""), []
                 )}
                for g in groups
            ],
        })

        if limit and len(candidates) >= limit:
            break

    return candidates


def _get_providers_with_capacity(
    session: Any, resources: dict[str, int]
) -> list[dict[str, Any]]:
    """Find providers with capacity for all requested resources.

    Validates inventory constraints: min_unit, max_unit, and step_size.

    :param session: Neo4j session
    :param resources: Dict of resource_class -> amount
    :returns: List of provider dicts with uuid, resources, and capacity info
    """
    # For each resource class, find providers that have inventory
    # and sufficient capacity, respecting inventory constraints
    providers: dict[str, dict[str, Any]] = {}

    for rc_name, amount in resources.items():
        result = session.run(
            """
            MATCH (rp:ResourceProvider)-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(rc:ResourceClass {name: $rc})
            OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
            WITH rp, inv, rc,
                 COALESCE(sum(alloc.used), 0) AS used,
                 inv.total AS total,
                 COALESCE(inv.reserved, 0) AS reserved,
                 COALESCE(inv.allocation_ratio, 1.0) AS allocation_ratio,
                 COALESCE(inv.min_unit, 1) AS min_unit,
                 COALESCE(inv.max_unit, inv.total) AS max_unit,
                 COALESCE(inv.step_size, 1) AS step_size
            WITH rp, rc.name AS rc_name,
                 (total - reserved) * allocation_ratio - used AS available,
                 total, reserved, used, allocation_ratio, min_unit, max_unit, step_size
            // Check capacity and inventory constraints
            WHERE available >= $amount
              AND $amount >= min_unit
              AND $amount <= max_unit
              AND ($amount - min_unit) % step_size = 0
            RETURN rp.uuid AS uuid, rp.generation AS generation,
                   rc_name, total, reserved, used, allocation_ratio,
                   (total - reserved) * allocation_ratio AS capacity
            """,
            rc=rc_name,
            amount=amount,
        )

        rc_providers: dict[str, dict[str, Any]] = {}
        for row in result:
            rp_uuid = row["uuid"]
            rc_providers[rp_uuid] = {
                "uuid": rp_uuid,
                "generation": row["generation"],
                "rc_name": rc_name,
                "total": row["total"],
                "reserved": row["reserved"],
                "used": row["used"],
                "allocation_ratio": row["allocation_ratio"],
                "capacity": int(row["capacity"]),
            }

        if not providers:
            providers = rc_providers
        else:
            # Intersect - keep only providers that have all resources
            providers = {
                rp_uuid: prov
                for rp_uuid, prov in providers.items()
                if rp_uuid in rc_providers
            }

    return list(providers.values())


def _get_tree_resources(
    session: Any,
    root_uuid: str,
    resources: dict[str, int],
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    """Find which requested resources can be satisfied by providers in a tree.

    :param session: Neo4j session
    :param root_uuid: UUID of the root provider of the tree
    :param resources: Dict of resource_class -> amount requested
    :returns: Tuple of (dict mapping rc -> provider info, dict of unsatisfied resources)
    """
    satisfied: dict[str, dict[str, Any]] = {}
    unsatisfied: dict[str, int] = {}

    for rc_name, amount in resources.items():
        # Find any provider in the tree that can satisfy this resource
        result = session.run(
            """
            MATCH (root:ResourceProvider {uuid: $root_uuid})-[:PARENT_OF*0..]->(rp:ResourceProvider)
            MATCH (rp)-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(rc:ResourceClass {name: $rc})
            OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
            WITH rp, inv, rc,
                 COALESCE(sum(alloc.used), 0) AS used,
                 inv.total AS total,
                 COALESCE(inv.reserved, 0) AS reserved,
                 COALESCE(inv.allocation_ratio, 1.0) AS allocation_ratio,
                 COALESCE(inv.min_unit, 1) AS min_unit,
                 COALESCE(inv.max_unit, inv.total) AS max_unit,
                 COALESCE(inv.step_size, 1) AS step_size
            WITH rp, inv, rc.name AS rc_name,
                 (total - reserved) * allocation_ratio - used AS available,
                 total, reserved, used, allocation_ratio, min_unit, max_unit, step_size
            WHERE available >= $amount
              AND $amount >= min_unit
              AND $amount <= max_unit
              AND ($amount - min_unit) % step_size = 0
            RETURN rp.uuid AS provider_uuid, rp.generation AS generation,
                   rc_name, total, reserved, used, allocation_ratio,
                   (total - reserved) * allocation_ratio AS capacity
            LIMIT 1
            """,
            root_uuid=root_uuid,
            rc=rc_name,
            amount=amount,
        )
        row = result.single()
        if row:
            satisfied[rc_name] = {
                "provider_uuid": row["provider_uuid"],
                "generation": row["generation"],
                "rc_name": rc_name,
                "total": row["total"],
                "reserved": row["reserved"],
                "used": row["used"],
                "allocation_ratio": row["allocation_ratio"],
                "capacity": int(row["capacity"]),
            }
        else:
            unsatisfied[rc_name] = amount

    return satisfied, unsatisfied


def _get_allocation_candidates_with_sharing(
    session: Any,
    resources: dict[str, int],
    required_traits: list[str] | None = None,
    forbidden_traits: list[str] | None = None,
    required_aggregates: list[list[str]] | None = None,
    forbidden_aggregates: list[str] | None = None,
    in_tree_uuid: str | None = None,
    root_required_traits: list[str] | None = None,
    root_forbidden_traits: list[str] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Find allocation candidates, including sharing providers where needed.

    This implements the full allocation candidates algorithm:
    1. Find all provider trees (by their roots)
    2. For each tree, find which resources can be satisfied within the tree
    3. For unsatisfied resources, check for sharing providers in shared aggregates
    4. Build allocation candidates combining tree and sharing providers

    :param session: Neo4j session
    :param resources: Dict of resource_class -> amount requested
    :param required_traits: Traits required on the satisfying provider
    :param forbidden_traits: Traits forbidden on the satisfying provider
    :param required_aggregates: Aggregate membership requirements (AND of OR lists)
    :param forbidden_aggregates: Aggregates the provider must not be in
    :param in_tree_uuid: If set, only consider this tree
    :param root_required_traits: Traits required on root provider
    :param root_forbidden_traits: Traits forbidden on root provider
    :param limit: Maximum number of candidates to return
    :returns: List of allocation candidate dicts
    """
    required_traits = required_traits or []
    forbidden_traits = forbidden_traits or []
    required_aggregates = required_aggregates or []
    forbidden_aggregates = forbidden_aggregates or []
    root_required_traits = root_required_traits or []
    root_forbidden_traits = root_forbidden_traits or []

    # Find all root providers (potential trees)
    # Apply in_tree filter if specified
    if in_tree_uuid:
        # Get the root of the specified tree
        root_result = session.run(
            """
            MATCH (p:ResourceProvider {uuid: $uuid})
            OPTIONAL MATCH path = (root:ResourceProvider)-[:PARENT_OF*0..]->(p)
            WHERE NOT EXISTS { MATCH (:ResourceProvider)-[:PARENT_OF]->(root) }
            RETURN COALESCE(root, p).uuid AS root_uuid
            """,
            uuid=in_tree_uuid,
        )
        root_row = root_result.single()
        if not root_row:
            return []
        root_uuids = [root_row["root_uuid"]]
    else:
        # Find all root providers
        result = session.run(
            """
            MATCH (root:ResourceProvider)
            WHERE NOT EXISTS { MATCH (:ResourceProvider)-[:PARENT_OF]->(root) }
            RETURN root.uuid AS root_uuid
            """
        )
        root_uuids = [row["root_uuid"] for row in result]

    # Filter by root provider traits if specified
    if root_required_traits or root_forbidden_traits:
        filtered_roots: list[str] = []
        for root_uuid in root_uuids:
            traits_result = session.run(
                """
                MATCH (root:ResourceProvider {uuid: $uuid})
                OPTIONAL MATCH (root)-[:HAS_TRAIT]->(t:Trait)
                RETURN collect(t.name) AS traits
                """,
                uuid=root_uuid,
            )
            traits_row = traits_result.single()
            root_traits = set(traits_row["traits"] or []) if traits_row else set()

            if root_required_traits and not set(root_required_traits).issubset(root_traits):
                continue
            if root_forbidden_traits and set(root_forbidden_traits).intersection(root_traits):
                continue

            filtered_roots.append(root_uuid)
        root_uuids = filtered_roots

    candidates: list[dict[str, Any]] = []

    for root_uuid in root_uuids:
        # Find which resources the tree can satisfy
        tree_satisfied, unsatisfied = _get_tree_resources(session, root_uuid, resources)

        if not tree_satisfied and not unsatisfied:
            # No resources requested - skip
            continue

        # Check trait requirements on tree providers
        if required_traits or forbidden_traits:
            all_tree_providers_valid = True
            for rc_info in tree_satisfied.values():
                provider_uuid = rc_info["provider_uuid"]
                traits_result = session.run(
                    """
                    MATCH (rp:ResourceProvider {uuid: $uuid})
                    OPTIONAL MATCH (rp)-[:HAS_TRAIT]->(t:Trait)
                    RETURN collect(t.name) AS traits
                    """,
                    uuid=provider_uuid,
                )
                traits_row = traits_result.single()
                provider_traits = set(traits_row["traits"] or []) if traits_row else set()

                if required_traits and not set(required_traits).issubset(provider_traits):
                    all_tree_providers_valid = False
                    break
                if forbidden_traits and set(forbidden_traits).intersection(provider_traits):
                    all_tree_providers_valid = False
                    break

            if not all_tree_providers_valid:
                continue

        # Check aggregate requirements on tree providers
        if required_aggregates or forbidden_aggregates:
            all_tree_providers_valid = True
            for rc_info in tree_satisfied.values():
                provider_uuid = rc_info["provider_uuid"]
                aggs_result = session.run(
                    """
                    MATCH (rp:ResourceProvider {uuid: $uuid})
                    OPTIONAL MATCH (rp)-[:MEMBER_OF]->(agg:Aggregate)
                    RETURN collect(agg.uuid) AS aggregates
                    """,
                    uuid=provider_uuid,
                )
                aggs_row = aggs_result.single()
                provider_aggs = set(aggs_row["aggregates"] or []) if aggs_row else set()

                # Check required aggregates (AND of OR lists)
                for agg_group in required_aggregates:
                    if not provider_aggs.intersection(set(agg_group)):
                        all_tree_providers_valid = False
                        break

                if not all_tree_providers_valid:
                    break

                # Check forbidden aggregates
                if forbidden_aggregates and provider_aggs.intersection(set(forbidden_aggregates)):
                    all_tree_providers_valid = False
                    break

            if not all_tree_providers_valid:
                continue

        # If tree can satisfy all resources, add candidate
        if not unsatisfied:
            # Build allocation from tree providers only
            allocations: dict[str, dict[str, Any]] = {}
            for rc_name, rc_info in tree_satisfied.items():
                provider_uuid = rc_info["provider_uuid"]
                if provider_uuid not in allocations:
                    allocations[provider_uuid] = {"resources": {}}
                allocations[provider_uuid]["resources"][rc_name] = resources[rc_name]

            candidates.append({
                "allocations": allocations,
                "tree_root_uuid": root_uuid,
            })
        else:
            # Try to find sharing providers for unsatisfied resources
            # Get any tree provider to find shared aggregates
            if tree_satisfied:
                tree_provider_uuid = next(iter(tree_satisfied.values()))["provider_uuid"]
            else:
                # No resources satisfied by tree - use root
                tree_provider_uuid = root_uuid

            sharing_providers = _find_sharing_providers(
                session, tree_provider_uuid, unsatisfied
            )

            if sharing_providers:
                # We found sharing providers that can satisfy the remaining resources
                # Build allocation combining tree and sharing providers
                allocations = {}

                # Add tree allocations
                for rc_name, rc_info in tree_satisfied.items():
                    provider_uuid = rc_info["provider_uuid"]
                    if provider_uuid not in allocations:
                        allocations[provider_uuid] = {"resources": {}}
                    allocations[provider_uuid]["resources"][rc_name] = resources[rc_name]

                # Add sharing provider allocations
                # For simplicity, use the first sharing provider that satisfies all
                sp = sharing_providers[0]
                sp_uuid = sp["uuid"]
                if sp_uuid not in allocations:
                    allocations[sp_uuid] = {"resources": {}}
                for rc_name, amount in unsatisfied.items():
                    allocations[sp_uuid]["resources"][rc_name] = amount

                candidates.append({
                    "allocations": allocations,
                    "tree_root_uuid": root_uuid,
                    "sharing_provider_uuids": [sp_uuid],
                })

        if limit and len(candidates) >= limit:
            break

    return candidates


def _filter_by_root_traits(
    session: Any,
    providers: list[dict[str, Any]],
    required_traits: list[str],
    forbidden_traits: list[str],
) -> list[dict[str, Any]]:
    """Filter providers by traits on their root provider.

    :param session: Neo4j session
    :param providers: List of provider dicts with uuid
    :param required_traits: Traits the root provider must have
    :param forbidden_traits: Traits the root provider must not have
    :returns: Filtered list of providers
    """
    if not required_traits and not forbidden_traits:
        return providers

    provider_uuids = [p["uuid"] for p in providers]
    if not provider_uuids:
        return providers

    # Query to find root provider and its traits for each provider
    result = session.run(
        """
        UNWIND $uuids AS rp_uuid
        MATCH (rp:ResourceProvider {uuid: rp_uuid})
        // Find root provider (provider with no parent in the tree containing rp)
        OPTIONAL MATCH path = (root:ResourceProvider)-[:PARENT_OF*0..]->(rp)
        WHERE NOT EXISTS { MATCH (:ResourceProvider)-[:PARENT_OF]->(root) }
        WITH rp, COALESCE(root, rp) AS root_provider
        // Get root provider traits
        OPTIONAL MATCH (root_provider)-[:HAS_TRAIT]->(t:Trait)
        WITH rp.uuid AS provider_uuid, collect(t.name) AS root_traits
        RETURN provider_uuid, root_traits
        """,
        uuids=provider_uuids,
    )

    # Build a map of provider uuid -> root traits
    root_traits_map: dict[str, set[str]] = {}
    for row in result:
        root_traits_map[row["provider_uuid"]] = set(row["root_traits"] or [])

    # Filter providers based on root trait requirements
    filtered: list[dict[str, Any]] = []
    required_set = set(required_traits)
    forbidden_set = set(forbidden_traits)

    for provider in providers:
        uuid = provider["uuid"]
        root_traits = root_traits_map.get(uuid, set())

        # Check required traits (root must have all of them)
        if required_set and not required_set.issubset(root_traits):
            continue

        # Check forbidden traits (root must have none of them)
        if forbidden_set and forbidden_set.intersection(root_traits):
            continue

        filtered.append(provider)

    return filtered


def _build_allocation_requests_dict(
    providers: list[dict[str, Any]],
    resources: dict[str, int],
    include_mappings: bool = False,
) -> list[dict[str, Any]]:
    """Build allocation requests in dict format (1.12+).

    :param providers: List of provider dicts
    :param resources: Dict of resource_class -> amount
    :param include_mappings: Whether to include mappings field (1.34+)
    :returns: List of allocation request dicts
    """
    result: list[dict[str, Any]] = []
    for prov in providers:
        ar: dict[str, Any] = {
            "allocations": {prov["uuid"]: {"resources": resources}}
        }
        if include_mappings:
            # Mappings maps request group suffixes to lists of provider UUIDs.
            # Empty string "" represents the unnumbered/default request group.
            # Format: {"": [rp_uuid1, ...], "1": [rp_uuid2, ...], ...}
            ar["mappings"] = {"": [prov["uuid"]]}
        result.append(ar)
    return result


def _build_allocation_requests_list(
    providers: list[dict[str, Any]], resources: dict[str, int]
) -> list[dict[str, Any]]:
    """Build allocation requests in list format (<1.12).

    :param providers: List of provider dicts
    :param resources: Dict of resource_class -> amount
    :returns: List of allocation request dicts
    """
    return [
        {
            "allocations": [
                {"resource_provider": {"uuid": prov["uuid"]}, "resources": resources}
            ]
        }
        for prov in providers
    ]


def _format_granular_allocation_requests(
    candidates: list[dict[str, Any]],
    request_groups: dict[str, "RequestGroup"],
    include_mappings: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Format granular allocation candidates into API response format.

    Transforms the results from _get_granular_allocation_candidates() into
    the allocation_requests format expected by the API, with proper
    multi-provider allocations and mappings.

    :param candidates: List of candidate dicts from granular query
    :param request_groups: Dict of suffix -> RequestGroup with resource requirements
    :param include_mappings: Whether to include mappings field (1.34+)
    :returns: Tuple of (allocation_requests list, provider_uuids list)
    """
    allocation_requests: list[dict[str, Any]] = []
    all_provider_uuids: set[str] = set()

    for candidate in candidates:
        allocation_data = candidate.get("allocation_data", [])

        # Build allocations dict: consolidate resources per provider
        # If multiple groups use the same provider, sum their resources
        allocations: dict[str, dict[str, Any]] = {}
        mappings: dict[str, list[str]] = {}

        for group_alloc in allocation_data:
            suffix = group_alloc.get("suffix", "")
            provider_uuid = group_alloc.get("provider_uuid")

            if not provider_uuid:
                continue

            all_provider_uuids.add(provider_uuid)

            # Get resources for this group
            group = request_groups.get(suffix)
            if group and group.resources:
                if provider_uuid not in allocations:
                    allocations[provider_uuid] = {"resources": {}}

                # Add/sum resources from this group
                for rc, amount in group.resources.items():
                    current = allocations[provider_uuid]["resources"].get(rc, 0)
                    allocations[provider_uuid]["resources"][rc] = current + amount

            # Build mappings: suffix -> list of provider UUIDs
            if include_mappings:
                if suffix not in mappings:
                    mappings[suffix] = []
                if provider_uuid not in mappings[suffix]:
                    mappings[suffix].append(provider_uuid)

        if not allocations:
            continue

        ar: dict[str, Any] = {"allocations": allocations}
        if include_mappings:
            ar["mappings"] = mappings

        allocation_requests.append(ar)

    return allocation_requests, list(all_provider_uuids)


def _expand_to_full_trees(
    session: Any,
    provider_uuids: list[str],
) -> list[str]:
    """Expand a list of provider UUIDs to include all providers in their trees.

    For each provider, find its root and then include all descendants of that root.
    This implements the 1.29+ behavior where provider_summaries should include
    all providers in the tree, not just the matching ones.

    :param session: Neo4j session
    :param provider_uuids: List of provider UUIDs to expand
    :returns: List of all provider UUIDs in the trees
    """
    if not provider_uuids:
        return []

    # Query to find all providers in the trees containing the given providers
    # For each provider, find its root, then find all descendants of that root
    result = session.run(
        """
        UNWIND $uuids AS provider_uuid
        MATCH (p:ResourceProvider {uuid: provider_uuid})
        OPTIONAL MATCH path = (root:ResourceProvider)-[:PARENT_OF*0..]->(p)
        WHERE NOT EXISTS { MATCH (:ResourceProvider)-[:PARENT_OF]->(root) }
        WITH COALESCE(root, p) AS tree_root
        MATCH (tree_root)-[:PARENT_OF*0..]->(descendant:ResourceProvider)
        RETURN DISTINCT descendant.uuid AS uuid
        """,
        uuids=provider_uuids,
    )

    return [row["uuid"] for row in result]


def _build_provider_summaries(
    session: Any,
    provider_uuids: list[str],
    resources: dict[str, int],
    mv: microversion.Microversion,
) -> dict[str, dict[str, Any]]:
    """Build provider summaries with capacity and usage.

    :param session: Neo4j session
    :param provider_uuids: List of provider UUIDs
    :param resources: Dict of requested resources
    :param mv: Microversion instance
    :returns: Dict of provider summaries
    """
    summaries: dict[str, dict[str, Any]] = {}

    for rp_uuid in provider_uuids:
        result = session.run(
            """
            MATCH (rp:ResourceProvider {uuid: $uuid})
            OPTIONAL MATCH (rp)-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(rc:ResourceClass)
            OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
            WITH rp, rc.name AS rc_name, inv,
                 COALESCE(sum(alloc.used), 0) AS used
            WHERE inv IS NOT NULL
            RETURN rp.uuid AS uuid, rp.generation AS generation,
                   rc_name, inv.total AS total,
                   COALESCE(inv.reserved, 0) AS reserved,
                   COALESCE(inv.allocation_ratio, 1.0) AS allocation_ratio,
                   used
            """,
            uuid=rp_uuid,
        )

        resource_data: dict[str, dict[str, int]] = {}
        for row in result:
            rc_name = row["rc_name"]
            # Before 1.27, only show requested resources
            if not mv.is_at_least(27) and rc_name not in resources:
                continue

            total = row["total"]
            reserved = row["reserved"]
            ratio = row["allocation_ratio"]
            used = int(row["used"])

            resource_data[rc_name] = {
                "capacity": int((total - reserved) * ratio),
                "used": used,
            }

        summary: dict[str, Any] = {"resources": resource_data}

        # Add traits at 1.17+
        if mv.is_at_least(17):
            traits_result = session.run(
                """
                MATCH (rp:ResourceProvider {uuid: $uuid})-[:HAS_TRAIT]->(t:Trait)
                RETURN collect(t.name) AS traits
                """,
                uuid=rp_uuid,
            ).single()
            summary["traits"] = traits_result["traits"] if traits_result else []

        # Add parent/root at 1.29+
        if mv.is_at_least(29):
            tree_result = session.run(
                """
                MATCH (rp:ResourceProvider {uuid: $uuid})
                OPTIONAL MATCH (parent:ResourceProvider)-[:PARENT_OF]->(rp)
                OPTIONAL MATCH path = (root:ResourceProvider)-[:PARENT_OF*0..]->(rp)
                WHERE NOT EXISTS { MATCH (:ResourceProvider)-[:PARENT_OF]->(root) }
                WITH rp, parent, root
                ORDER BY length(path) DESC
                WITH rp, parent, collect(root)[0] AS root_provider
                RETURN parent.uuid AS parent_uuid, root_provider.uuid AS root_uuid
                """,
                uuid=rp_uuid,
            ).single()
            if tree_result:
                summary["parent_provider_uuid"] = tree_result["parent_uuid"]
                summary["root_provider_uuid"] = tree_result["root_uuid"] or rp_uuid

        summaries[rp_uuid] = summary

    return summaries


@bp.route("", methods=["GET"])
def list_allocation_candidates() -> tuple[flask.Response, int]:
    """Get allocation candidates for requested resources.

    Query Parameters:
        resources: Required. Format: CLASS1:AMOUNT1,CLASS2:AMOUNT2
        limit: Optional (1.16+). Maximum number of candidates to return.
        required: Optional (1.17+). Required traits.
        member_of: Optional (1.21+). Aggregate membership filter.
        in_tree: Optional (1.25+). Provider tree filter.
        root_required: Optional (1.35+). Traits required/forbidden on root provider.
            Format: TRAIT1,TRAIT2,!TRAIT3 (! prefix means forbidden)

    :returns: Tuple of (response, status_code)
    """
    flask.g.context.can(ac_policies.LIST)
    mv = _mv()

    # Allocation candidates requires microversion >= 1.10
    if not mv.is_at_least(10):
        raise errors.NotFound("The resource could not be found.")

    # Validate allowed query parameters based on microversion
    allowed_params: set[str] = {"resources"}
    if mv.is_at_least(16):
        allowed_params.add("limit")
    if mv.is_at_least(17):
        allowed_params.add("required")
    if mv.is_at_least(21):
        allowed_params.add("member_of")
    if mv.is_at_least(25):
        # Granular request groups: resourcesN, requiredN, member_ofN, group_policy
        allowed_params.add("in_tree")
        allowed_params.add("group_policy")
    if mv.is_at_least(35):
        allowed_params.add("root_required")
    if mv.is_at_least(36):
        allowed_params.add("same_subtree")

    # Check for unknown parameters, allowing numbered parameters at 1.25+
    # At 1.33+, suffixes can be alphanumeric (e.g., resources_COMPUTE)
    # Before 1.33, only numeric suffixes are allowed (e.g., resources1)
    if mv.is_at_least(33):
        # Alphanumeric suffixes allowed: resourcesN, resources_NAME, etc.
        numbered_pattern = re.compile(
            r"^(resources|required|member_of|in_tree)([a-zA-Z0-9_-]{1,64})?$"
        )
    else:
        # Only numeric suffixes allowed: resources1, resources2, etc.
        numbered_pattern = re.compile(r"^(resources|required|member_of|in_tree)(\d+)?$")

    # Track all suffixes used in the request
    all_suffixes: set[str] = set()
    resource_suffixes: set[str] = set()
    has_numbered_resources = False

    for param in flask.request.args:
        if param in allowed_params:
            continue
        # Check for numbered parameters at 1.25+
        match = numbered_pattern.match(param)
        if match and mv.is_at_least(25):
            base_param = match.group(1)
            suffix = match.group(2)
            if suffix:
                all_suffixes.add(suffix)
                if base_param == "resources":
                    resource_suffixes.add(suffix)
                    has_numbered_resources = True
            continue
        raise errors.BadRequest(
            "Invalid query string parameters: '%s' was unexpected" % param
        )

    resources_param = flask.request.args.get("resources")
    # At 1.25+, 'resources' is optional if numbered groups (e.g., resources1) exist
    if resources_param is None and not has_numbered_resources:
        raise errors.BadRequest("'resources' is a required property")

    # Parse unnumbered resources if present
    resources: dict[str, int] = {}
    if resources_param is not None:
        resources = _parse_resources(resources_param)

    # Build per-suffix RequestGroup objects for granular support (1.25+)
    # The groups dict maps suffix -> RequestGroup
    # Empty string "" suffix represents the unnumbered group
    request_groups: dict[str, RequestGroup] = {}

    # Initialize unnumbered group if it has resources
    if resources:
        request_groups[""] = RequestGroup(suffix="", resources=resources.copy())

    # Parse numbered resources groups (1.25+)
    numbered_resources: dict[str, dict[str, int]] = {}
    if mv.is_at_least(25):
        for param in flask.request.args:
            match = numbered_pattern.match(param)
            if match and match.group(1) == "resources" and match.group(2):
                suffix = match.group(2)
                parsed_resources = _parse_resources(flask.request.args.get(param, ""))
                numbered_resources[suffix] = parsed_resources
                # Create or update RequestGroup for this suffix
                if suffix not in request_groups:
                    request_groups[suffix] = RequestGroup(suffix=suffix)
                request_groups[suffix].resources = parsed_resources

    # For backward compatibility, combine all resources for simple capacity queries
    # This is used when granular query is not needed
    combined_resources = resources.copy()
    if not resources and numbered_resources:
        for suffix, res in numbered_resources.items():
            for rc, amount in res.items():
                combined_resources[rc] = combined_resources.get(rc, 0) + amount
    elif numbered_resources:
        for suffix, res in numbered_resources.items():
            for rc, amount in res.items():
                combined_resources[rc] = combined_resources.get(rc, 0) + amount

    # Parse limit
    limit: int | None = None
    if "limit" in flask.request.args:
        limit_str = flask.request.args.get("limit")
        # Validate limit format (positive integer)
        if not limit_str or not limit_str.isdigit() or int(limit_str) < 1:
            raise errors.BadRequest(
                "Invalid query string parameters: Failed validating 'pattern' for limit"
            )
        limit = int(limit_str)

    # Parse required parameter (1.17+) - filter by traits on the provider
    # These go into the unnumbered group
    required_traits: list[str] = []
    forbidden_traits: list[str] = []
    any_of_trait_groups: list[list[str]] = []
    if "required" in flask.request.args:
        required_param = flask.request.args.get("required", "")
        required_traits, forbidden_traits, any_of_trait_groups = _parse_required_traits(
            required_param, mv
        )
        # Add to unnumbered group
        if "" not in request_groups:
            request_groups[""] = RequestGroup(suffix="")
        request_groups[""].required_traits = required_traits
        request_groups[""].forbidden_traits = forbidden_traits
        request_groups[""].any_of_trait_groups = any_of_trait_groups

    # Parse numbered required parameters (required1, required2, etc.) at 1.25+
    # Store per-suffix, but also maintain combined list for backward compatibility
    numbered_required_by_suffix: dict[str, tuple[list[str], list[str], list[list[str]]]] = {}
    if mv.is_at_least(25):
        for param in flask.request.args:
            match = numbered_pattern.match(param)
            if match and match.group(1) == "required" and match.group(2):
                suffix = match.group(2)
                param_value = flask.request.args.get(param, "")
                numbered_req, numbered_forb, numbered_any_of = _parse_required_traits(
                    param_value, mv
                )
                numbered_required_by_suffix[suffix] = (
                    numbered_req, numbered_forb, numbered_any_of
                )
                # Create or update RequestGroup for this suffix
                if suffix not in request_groups:
                    request_groups[suffix] = RequestGroup(suffix=suffix)
                request_groups[suffix].required_traits = numbered_req
                request_groups[suffix].forbidden_traits = numbered_forb
                request_groups[suffix].any_of_trait_groups = numbered_any_of
                # Also extend combined lists for backward compatibility
                required_traits.extend(numbered_req)
                forbidden_traits.extend(numbered_forb)
                any_of_trait_groups.extend(numbered_any_of)

    # Parse root_required parameter (1.35+) - filter by traits on root provider
    # This applies globally, not per-group
    root_required_traits: list[str] = []
    root_forbidden_traits: list[str] = []
    if "root_required" in flask.request.args:
        root_required_param = flask.request.args.get("root_required", "")
        root_required_traits, root_forbidden_traits = _parse_traits(root_required_param)

    # Parse member_of parameter (1.21+) - filter by aggregate membership
    # This goes into the unnumbered group
    required_aggregates: list[list[str]] = []
    forbidden_aggregates: list[str] = []
    if "member_of" in flask.request.args:
        member_of_params = flask.request.args.getlist("member_of")
        required_aggregates, forbidden_aggregates = _parse_member_of(member_of_params, mv)
        # Add to unnumbered group
        if "" not in request_groups:
            request_groups[""] = RequestGroup(suffix="")
        request_groups[""].required_aggregates = required_aggregates
        request_groups[""].forbidden_aggregates = forbidden_aggregates

    # Parse numbered member_of parameters (member_of1, member_of2, etc.) at 1.25+
    if mv.is_at_least(25):
        for param in flask.request.args:
            match = numbered_pattern.match(param)
            if match and match.group(1) == "member_of" and match.group(2):
                suffix = match.group(2)
                param_value = flask.request.args.get(param, "")
                # member_of format: single UUID or "in:uuid1,uuid2,..."
                numbered_aggs, numbered_forb_aggs = _parse_member_of([param_value], mv)
                # Create or update RequestGroup for this suffix
                if suffix not in request_groups:
                    request_groups[suffix] = RequestGroup(suffix=suffix)
                request_groups[suffix].required_aggregates = numbered_aggs
                request_groups[suffix].forbidden_aggregates = numbered_forb_aggs

    # Parse group_policy parameter (1.25+)
    # - 'none': resources may be satisfied by any combination of providers
    # - 'isolate': resources in a numbered group must come from a single provider
    group_policy: str | None = None
    if "group_policy" in flask.request.args:
        if not mv.is_at_least(25):
            raise errors.BadRequest(
                "Invalid query string parameters: 'group_policy' was unexpected"
            )
        group_policy = flask.request.args.get("group_policy")
        if group_policy not in ("none", "isolate"):
            raise errors.BadRequest(
                "Invalid query string parameters: Expected 'group_policy' parameter "
                "value of 'none' or 'isolate'. Got: %s" % group_policy
            )

    # Count numbered resource groups (suffixes like 1, 2, _COMPUTE, etc.)
    numbered_resource_suffixes = [s for s in resource_suffixes if s]
    if len(numbered_resource_suffixes) > 1 and not group_policy:
        # Error message matches Placement API exactly
        raise errors.BadRequest(
            'The "group_policy" parameter is required when specifying '
            'more than one "resources{N}" parameter.'
        )

    # Parse same_subtree parameter (1.36+)
    # This constrains numbered request groups to providers in the same subtree.
    # Format: same_subtree=_SUFFIX1,_SUFFIX2,... (e.g., same_subtree=_1,_2)
    # The suffixes in same_subtree always include a leading underscore.
    same_subtree_groups: list[list[str]] | None = None
    same_subtree_suffixes: set[str] = set()
    if "same_subtree" in flask.request.args:
        if not mv.is_at_least(36):
            raise errors.BadRequest(
                "Invalid query string parameters: 'same_subtree' was unexpected"
            )
        # Parse comma-separated suffixes, can have multiple same_subtree params
        all_same_subtree = flask.request.args.getlist("same_subtree")
        same_subtree_groups = []
        for param in all_same_subtree:
            suffixes = [s.strip() for s in param.split(",") if s.strip()]
            if suffixes:
                same_subtree_groups.append(suffixes)
                for suffix in suffixes:
                    # same_subtree uses _SUFFIX format. Request params use:
                    # - resources1 -> suffix "1" (numeric, no underscore)
                    # - resources_COMPUTE -> suffix "_COMPUTE" (alphanumeric, with underscore)
                    # So we need to try matching both with and without the underscore.
                    if suffix.startswith("_"):
                        # Add both forms to handle both cases
                        same_subtree_suffixes.add(suffix[1:])  # For numeric: _1 -> 1
                        same_subtree_suffixes.add(suffix)  # For alphanumeric: _COMPUTE
                    else:
                        same_subtree_suffixes.add(suffix)

    # Identify resourceless request groups (suffixes with required/member_of
    # but no resources). Per spec, these MUST be used with same_subtree.
    resourceless_suffixes = all_suffixes - resource_suffixes
    if resourceless_suffixes:
        # Validate that all resourceless suffixes appear in a same_subtree group
        # Error message matches Placement API exactly
        bad_suffixes = [suffix for suffix in resourceless_suffixes
                        if suffix not in same_subtree_suffixes]
        if bad_suffixes:
            raise errors.BadRequest(
                "Resourceless suffixed group request should be specified "
                "in `same_subtree` query param: bad group(s) - %s."
                % bad_suffixes
            )

    # Validate same_subtree suffixes reference existing request groups
    if same_subtree_suffixes:
        # All suffixes in same_subtree must correspond to a request group
        # (either with resources or resourceless with required/member_of)
        # Since we added both _SUFFIX and SUFFIX forms, check if at least
        # one form exists in all_suffixes
        bad_suffixes = []
        for suffix in list(same_subtree_suffixes):
            # Empty string "" references the unnumbered group - always valid
            if suffix == "":
                continue
            # Check if this suffix or its alternate form exists
            alt_suffix = "_" + suffix if not suffix.startswith("_") else suffix[1:]
            if suffix not in all_suffixes and alt_suffix not in all_suffixes:
                bad_suffixes.append(suffix)
        if bad_suffixes:
            # Error message matches Placement API exactly
            raise errors.BadRequest(
                "Real suffixes should be specified in `same_subtree`: "
                "%s not found in %s."
                % (bad_suffixes, list(all_suffixes))
            )

    # NOTE: Full same_subtree enforcement is implemented via the granular
    # Neo4j query which checks for common ancestors between groups.

    # Parse in_tree parameter (1.31+) - restrict to providers in a specific tree
    # This goes into the unnumbered group
    in_tree_uuid: str | None = None
    if "in_tree" in flask.request.args and mv.is_at_least(31):
        in_tree_param = flask.request.args.get("in_tree")
        if in_tree_param:
            try:
                # Validate UUID format
                in_tree_uuid = str(uuid_module.UUID(in_tree_param))
                # Add to unnumbered group
                if "" not in request_groups:
                    request_groups[""] = RequestGroup(suffix="")
                request_groups[""].in_tree = in_tree_uuid
            except (ValueError, TypeError, AttributeError):
                raise errors.BadRequest(
                    "Invalid query string parameters: Expected 'in_tree' parameter "
                    "to be a valid UUID. Got: %s" % in_tree_param
                )

    # Parse numbered in_tree parameters (in_tree1, in_tree2, etc.) at 1.31+
    if mv.is_at_least(31):
        for param in flask.request.args:
            match = numbered_pattern.match(param)
            if match and match.group(1) == "in_tree" and match.group(2):
                suffix = match.group(2)
                param_value = flask.request.args.get(param, "")
                if param_value:
                    try:
                        validated_uuid = str(uuid_module.UUID(param_value))
                        # Create or update RequestGroup for this suffix
                        if suffix not in request_groups:
                            request_groups[suffix] = RequestGroup(suffix=suffix)
                        request_groups[suffix].in_tree = validated_uuid
                    except (ValueError, TypeError, AttributeError):
                        raise errors.BadRequest(
                            "Invalid query string parameters: Expected '%s' parameter "
                            "to be a valid UUID. Got: %s" % (param, param_value)
                        )

    # Determine if we should use the granular query path
    # Only use granular query if there are actually numbered resource groups
    # The group_policy parameter without numbered groups doesn't require granular handling
    use_granular_query = has_numbered_resources

    with _driver().session() as session:
        # Validate resource classes exist - use combined_resources which has all
        _validate_resource_classes(session, list(combined_resources.keys()))

        # Validate required traits exist
        all_traits = required_traits + forbidden_traits
        _validate_traits_exist(session, all_traits)

        allocation_requests: list[dict[str, Any]]
        provider_uuids: list[str]

        if use_granular_query and request_groups:
            # Use granular query for multi-group requests
            LOG.debug(
                "Using granular allocation candidates query for %d groups",
                len(request_groups)
            )

            # Convert request_groups to list of dicts for Cypher
            groups_list = [g.to_cypher_dict() for g in request_groups.values()]

            # Execute granular query
            candidates = _get_granular_allocation_candidates(
                session,
                groups_list,
                group_policy,
                same_subtree_groups,
                root_required_traits,
                root_forbidden_traits,
                limit,
            )

            # Format response
            include_mappings = mv.is_at_least(34)
            allocation_requests, provider_uuids = _format_granular_allocation_requests(
                candidates, request_groups, include_mappings
            )

        else:
            # Use simple query for single-group requests
            # First try to find providers that can satisfy all resources within a single tree
            providers = _get_providers_with_capacity(session, combined_resources)

            # Filter by provider traits (1.17+)
            if required_traits or forbidden_traits or any_of_trait_groups:
                providers = _filter_by_provider_traits(
                    session,
                    providers,
                    required_traits,
                    forbidden_traits,
                    any_of_trait_groups,
                )

            # Filter by aggregate membership (1.21+)
            if required_aggregates or forbidden_aggregates:
                providers = _filter_by_aggregates(
                    session, providers, required_aggregates, forbidden_aggregates
                )

            # Filter by in_tree (1.31+)
            if in_tree_uuid:
                providers = _filter_by_in_tree(session, providers, in_tree_uuid)

            # Filter by root provider traits (1.35+)
            if root_required_traits or root_forbidden_traits:
                providers = _filter_by_root_traits(
                    session, providers, root_required_traits, root_forbidden_traits
                )

            # If no providers found, try using sharing providers
            allocation_requests = []
            provider_uuids_set: set[str] = set()

            if not providers:
                # No single provider can satisfy all resources - try sharing providers
                candidates = _get_allocation_candidates_with_sharing(
                    session,
                    combined_resources,
                    required_traits=required_traits if required_traits else None,
                    forbidden_traits=forbidden_traits if forbidden_traits else None,
                    required_aggregates=required_aggregates if required_aggregates else None,
                    forbidden_aggregates=forbidden_aggregates if forbidden_aggregates else None,
                    in_tree_uuid=in_tree_uuid,
                    root_required_traits=root_required_traits if root_required_traits else None,
                    root_forbidden_traits=root_forbidden_traits if root_forbidden_traits else None,
                    limit=limit,
                )

                include_mappings = mv.is_at_least(34)
                for candidate in candidates:
                    allocations = candidate.get("allocations", {})
                    if not allocations:
                        continue

                    for prov_uuid in allocations.keys():
                        provider_uuids_set.add(prov_uuid)

                    if mv.is_at_least(12):
                        ar: dict[str, Any] = {"allocations": allocations}
                        if include_mappings:
                            ar["mappings"] = {"": list(allocations.keys())}
                        allocation_requests.append(ar)
                    else:
                        ar_list = []
                        for prov_uuid, prov_alloc in allocations.items():
                            ar_list.append({
                                "resource_provider": {"uuid": prov_uuid},
                                "resources": prov_alloc["resources"],
                            })
                        allocation_requests.append({"allocations": ar_list})
            else:
                # Apply limit
                if limit and len(providers) > limit:
                    providers = providers[:limit]

                # Build response based on microversion
                if mv.is_at_least(12):
                    include_mappings = mv.is_at_least(34)
                    allocation_requests = _build_allocation_requests_dict(
                        providers, combined_resources, include_mappings=include_mappings
                    )
                else:
                    allocation_requests = _build_allocation_requests_list(
                        providers, combined_resources
                    )

                provider_uuids_set = {p["uuid"] for p in providers}

            provider_uuids = list(provider_uuids_set)

        # At 1.29+, provider_summaries should include all providers in the tree
        # of matching providers, not just the matching ones
        if mv.is_at_least(29):
            summary_uuids = _expand_to_full_trees(session, provider_uuids)
        else:
            summary_uuids = provider_uuids

        provider_summaries = _build_provider_summaries(
            session, summary_uuids, combined_resources, mv
        )

    response_data: dict[str, Any] = {
        "allocation_requests": allocation_requests,
        "provider_summaries": provider_summaries,
    }

    resp = flask.jsonify(response_data)
    if mv.is_at_least(15):
        resp.headers["cache-control"] = "no-cache"
        resp.headers["last-modified"] = _httpdate()

    return resp, 200
