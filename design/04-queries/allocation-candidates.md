---
title: Allocation Candidates Query
description: Core scheduling query equivalent to GET /allocation_candidates
keywords: [allocation-candidates, scheduling, placement, resource-request]
related:
  - 03-constraints/trait-constraints.md
  - 03-constraints/aggregate-constraints.md
  - 05-operations/resource-claiming.md
implements:
  - "Allocation candidates API"
  - "Resource scheduling"
section: queries
---

# Allocation Candidates Query

The core scheduling query, equivalent to `GET /allocation_candidates`.

## Basic Allocation Candidates

Find providers that can satisfy resource requirements.

```cypher
// Parameters:
// $resources: [{resource_class: 'VCPU', amount: 4}, {resource_class: 'MEMORY_MB', amount: 8192}]
// $required_traits: ['HW_CPU_X86_AVX2']
// $forbidden_traits: ['COMPUTE_STATUS_DISABLED']
// $limit: 100

// Find root providers (compute hosts)
MATCH (root:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(root)
  AND NOT root.disabled = true

// Check required traits on root
WITH root
WHERE ALL(trait IN $required_traits WHERE
  (root)-[:HAS_TRAIT]->(:Trait {name: trait})
)

// Check forbidden traits
AND NONE(trait IN $forbidden_traits WHERE
  (root)-[:HAS_TRAIT]->(:Trait {name: trait})
)

// For each required resource, find inventory with capacity
UNWIND $resources AS req
MATCH (root)-[:PARENT_OF*0..]->(provider)
      -[:HAS_INVENTORY]->(inv)
      -[:OF_CLASS]->(rc:ResourceClass {name: req.resource_class})

// Calculate capacity and usage
OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
WITH root, provider, inv, rc, req,
     (inv.total - inv.reserved) * inv.allocation_ratio AS capacity,
     COALESCE(sum(alloc.used), 0) AS used

// Filter by available capacity
WHERE capacity - used >= req.amount
  AND req.amount >= inv.min_unit
  AND req.amount <= inv.max_unit
  AND req.amount % inv.step_size = 0

// Group results by root provider
WITH root, collect({
  provider: provider,
  inventory: inv,
  resource_class: rc.name,
  amount: req.amount,
  capacity: capacity,
  used: used
}) AS allocations

// Ensure all resources are satisfied
WHERE size(allocations) = size($resources)

RETURN root, allocations
LIMIT $limit
```

## With Aggregates

Include aggregate membership filtering.

```cypher
MATCH (root:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(root)

// member_of filter (any of)
AND (size($member_of) = 0 OR EXISTS {
  MATCH (root)-[:MEMBER_OF]->(agg:Aggregate)
  WHERE agg.uuid IN $member_of
})

// forbidden aggregates
AND NOT EXISTS {
  MATCH (root)-[:MEMBER_OF]->(agg:Aggregate)
  WHERE agg.uuid IN $forbidden_aggs
}

// ... continue with resource checks
RETURN root
```

## With Per-Group Traits

Support for granular resource requests with per-group traits.

```cypher
// Parameters:
// $groups: [
//   {suffix: '', resources: [{rc: 'VCPU', amount: 4}], required_traits: [], forbidden_traits: []},
//   {suffix: '1', resources: [{rc: 'SRIOV_NET_VF', amount: 1}], required_traits: ['CUSTOM_PHYSNET_DATA'], forbidden_traits: []}
// ]

MATCH (root:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(root)
  AND root.disabled <> true

// Process each group
UNWIND $groups AS grp
WITH root, grp

// Find providers that can satisfy this group
MATCH (root)-[:PARENT_OF*0..]->(provider)

// Check group-specific required traits
WHERE ALL(trait IN grp.required_traits WHERE
  (provider)-[:HAS_TRAIT]->(:Trait {name: trait})
)
AND NONE(trait IN grp.forbidden_traits WHERE
  (provider)-[:HAS_TRAIT]->(:Trait {name: trait})
)

// Check resources for this group
UNWIND grp.resources AS req
MATCH (provider)-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(rc:ResourceClass {name: req.rc})
OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
WITH root, grp, provider, inv, rc, req,
     (inv.total - inv.reserved) * inv.allocation_ratio AS capacity,
     COALESCE(sum(alloc.used), 0) AS used
WHERE capacity - used >= req.amount

WITH root, grp, provider, collect({
  inventory: inv,
  resource_class: rc.name,
  amount: req.amount
}) AS group_allocations
WHERE size(group_allocations) = size(grp.resources)

WITH root, collect({
  suffix: grp.suffix,
  provider: provider,
  allocations: group_allocations
}) AS groups

RETURN root, groups
```

## With Sharing Providers

Include resources from sharing providers.

```cypher
MATCH (root:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(root)

// Collect all providers that can contribute resources (including sharing)
OPTIONAL MATCH (sharing:ResourceProvider)-[:SHARES_RESOURCES]->(root)
WITH root, collect(DISTINCT sharing) + [root] AS all_providers

// Check each resource requirement
UNWIND $resources AS req
UNWIND all_providers AS provider

// For nested resources
OPTIONAL MATCH (root)-[:PARENT_OF*0..]->(provider)
MATCH (provider)-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(rc:ResourceClass {name: req.resource_class})

OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
WITH root, provider, inv, rc, req,
     (inv.total - inv.reserved) * inv.allocation_ratio AS capacity,
     COALESCE(sum(alloc.used), 0) AS used
WHERE capacity - used >= req.amount

WITH root, collect({
  provider: provider,
  inventory: inv,
  resource_class: rc.name,
  is_sharing: NOT (root)-[:PARENT_OF*0..]->(provider)
}) AS allocations

RETURN root, allocations
```

## Full Allocation Candidates

Complete query combining all filters.

```cypher
MATCH (root:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(root)
  AND COALESCE(root.disabled, false) = false

  // Required traits
  AND ALL(t IN $required_traits WHERE (root)-[:HAS_TRAIT]->(:Trait {name: t}))

  // Forbidden traits
  AND NONE(t IN $forbidden_traits WHERE (root)-[:HAS_TRAIT]->(:Trait {name: t}))

  // member_of aggregates
  AND (size($member_of) = 0 OR EXISTS {
    MATCH (root)-[:MEMBER_OF]->(agg:Aggregate)
    WHERE agg.uuid IN $member_of
  })

  // Availability zone
  AND ($az IS NULL OR EXISTS {
    MATCH (root)-[:MEMBER_OF]->(:Aggregate)-[:DEFINES_AZ]->(:AvailabilityZone {name: $az})
  })

  // Tenant isolation
  AND NOT EXISTS {
    MATCH (root)-[:MEMBER_OF]->(agg:Aggregate)-[:TENANT_ALLOWED]->(:Project)
    WHERE NOT (agg)-[:TENANT_ALLOWED]->(:Project {external_id: $project_id})
  }

// Check resources
UNWIND $resources AS req
MATCH (root)-[:PARENT_OF*0..]->(provider)
      -[:HAS_INVENTORY]->(inv)
      -[:OF_CLASS]->(:ResourceClass {name: req.resource_class})

OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
WITH root, req, provider, inv,
     (inv.total - inv.reserved) * inv.allocation_ratio - COALESCE(sum(alloc.used), 0) AS available

WHERE available >= req.amount

WITH root, collect({provider: provider.uuid, rc: req.resource_class, amount: req.amount}) AS allocs
WHERE size(allocs) = size($resources)

RETURN root.uuid AS provider_uuid, root.name AS provider_name, allocs
LIMIT $limit
```
