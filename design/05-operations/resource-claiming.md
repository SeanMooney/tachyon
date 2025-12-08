---
title: Resource Claiming
description: Allocation creation with optimistic concurrency
keywords: [claiming, allocation, generation, concurrency, transaction]
related:
  - 01-schema/relationships/consumption.md
  - 04-queries/allocation-candidates.md
implements:
  - "Allocation creation"
  - "Optimistic concurrency"
section: operations
---

# Resource Claiming

Atomic allocation with generation checks.

## Simple Allocation

```cypher
// Parameters:
// $consumer_uuid: 'instance-uuid'
// $allocations: [{rp_uuid: 'rp-1', resource_class: 'VCPU', used: 4}, ...]
// $project_id: 'project-uuid'
// $user_id: 'user-uuid'
// $consumer_generation: null (new) or current generation (update)
// $provider_generations: {'rp-1': 5, 'rp-2': 3}  // Expected generations

// Check provider generations haven't changed
UNWIND keys($provider_generations) AS rp_uuid
MATCH (rp:ResourceProvider {uuid: rp_uuid})
WHERE rp.generation = $provider_generations[rp_uuid]
WITH collect(rp) AS verified_providers
WHERE size(verified_providers) = size(keys($provider_generations))

// Get or create consumer
MERGE (consumer:Consumer {uuid: $consumer_uuid})
ON CREATE SET
  consumer.generation = 0,
  consumer.created_at = datetime(),
  consumer.updated_at = datetime()
ON MATCH SET
  consumer.updated_at = datetime()

// Verify consumer generation if updating
WITH consumer
WHERE $consumer_generation IS NULL OR consumer.generation = $consumer_generation

// Link to project and user
MERGE (project:Project {external_id: $project_id})
MERGE (user:User {external_id: $user_id})
MERGE (consumer)-[:OWNED_BY]->(project)
MERGE (consumer)-[:CREATED_BY]->(user)

// Remove existing allocations (for replacement)
OPTIONAL MATCH (consumer)-[old_alloc:CONSUMES]->()
DELETE old_alloc

// Create new allocations
WITH consumer
UNWIND $allocations AS alloc
MATCH (rp:ResourceProvider {uuid: alloc.rp_uuid})
      -[:HAS_INVENTORY]->(inv)
      -[:OF_CLASS]->(:ResourceClass {name: alloc.resource_class})

// Verify capacity
OPTIONAL MATCH (inv)<-[existing:CONSUMES]-()
WITH consumer, rp, inv, alloc,
     (inv.total - inv.reserved) * inv.allocation_ratio AS capacity,
     COALESCE(sum(existing.used), 0) AS current_usage
WHERE capacity - current_usage >= alloc.used

// Create allocation
CREATE (consumer)-[:CONSUMES {
  used: alloc.used,
  created_at: datetime(),
  updated_at: datetime()
}]->(inv)

// Increment consumer generation
WITH consumer
SET consumer.generation = consumer.generation + 1

RETURN consumer
```

## Multi-Provider Allocation with Nested Providers

```cypher
// Allocate across root, NUMA, and PCI providers in same tree
// $allocations: [
//   {provider_uuid: 'root-uuid', resource_class: 'VCPU', used: 4},
//   {provider_uuid: 'numa-0-uuid', resource_class: 'MEMORY_MB', used: 8192},
//   {provider_uuid: 'vf-uuid', resource_class: 'SRIOV_NET_VF', used: 1}
// ]

MATCH (consumer:Consumer {uuid: $consumer_uuid})

UNWIND $allocations AS alloc
MATCH (provider:ResourceProvider {uuid: alloc.provider_uuid})
MATCH (provider)-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(:ResourceClass {name: alloc.resource_class})

// Verify all providers are in same tree
MATCH (root:ResourceProvider)-[:PARENT_OF*0..]->(provider)
WHERE NOT ()-[:PARENT_OF]->(root)
WITH consumer, provider, inv, alloc, root

// All allocations should have same root
WITH consumer, collect({provider: provider, inv: inv, alloc: alloc}) AS all_allocs, collect(DISTINCT root) AS roots
WHERE size(roots) = 1  // All in same tree

// Create allocations
UNWIND all_allocs AS a
CREATE (consumer)-[:CONSUMES {
  used: a.alloc.used,
  created_at: datetime(),
  updated_at: datetime()
}]->(a.inv)

RETURN consumer
```

## Delete Allocations

```cypher
// Delete all allocations for consumer
MATCH (consumer:Consumer {uuid: $consumer_uuid})
WHERE consumer.generation = $consumer_generation

// Remove allocations
MATCH (consumer)-[alloc:CONSUMES]->()
DELETE alloc

// Remove consumer if no allocations remain
WITH consumer
OPTIONAL MATCH (consumer)-[remaining:CONSUMES]->()
WITH consumer, count(remaining) AS remaining_count
WHERE remaining_count = 0
DETACH DELETE consumer
```

## Atomic Reshaper (Bulk Allocation Update)

```cypher
// Atomically update allocations for multiple consumers
UNWIND $changes AS change

// For each consumer
MATCH (consumer:Consumer {uuid: change.consumer_uuid})
WHERE consumer.generation = change.consumer_generation

// Remove old allocations
OPTIONAL MATCH (consumer)-[old:CONSUMES]->()
DELETE old

// Create new allocations
WITH consumer, change
UNWIND change.allocations AS alloc
MATCH (rp:ResourceProvider {uuid: alloc.rp_uuid})
WHERE rp.generation = alloc.rp_generation
MATCH (rp)-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(:ResourceClass {name: alloc.resource_class})

CREATE (consumer)-[:CONSUMES {
  used: alloc.used,
  created_at: datetime(),
  updated_at: datetime()
}]->(inv)

SET consumer.generation = consumer.generation + 1

RETURN consumer
```

## Generation Conflict Detection

```cypher
// Check for generation conflicts before claiming
UNWIND $provider_uuids AS uuid
MATCH (rp:ResourceProvider {uuid: uuid})
WITH collect({uuid: rp.uuid, generation: rp.generation}) AS current_generations

// Compare with expected
WITH current_generations, $expected_generations AS expected
WHERE ALL(c IN current_generations WHERE
  ANY(e IN expected WHERE e.uuid = c.uuid AND e.generation = c.generation)
)

// If we get here, no conflicts
RETURN true AS generations_valid
```

## Optimistic Concurrency Pattern

```cypher
// Pattern for safe updates with retries
// 1. Read current state
MATCH (rp:ResourceProvider {uuid: $uuid})
RETURN rp.generation AS current_generation

// 2. Attempt update with generation check
MATCH (rp:ResourceProvider {uuid: $uuid})
WHERE rp.generation = $expected_generation
SET rp.generation = rp.generation + 1,
    rp.updated_at = datetime()
// ... make changes ...
RETURN rp

// 3. If no rows returned, generation changed - retry from step 1
```
