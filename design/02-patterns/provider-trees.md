---
title: Resource Provider Trees
description: Modeling hierarchical resource providers (compute hosts with nested resources)
keywords: [provider-tree, hierarchy, root-provider, nested, forest]
related:
  - 01-schema/nodes/resource-provider.md
  - 01-schema/relationships/hierarchy.md
implements:
  - "Nested resource provider trees"
section: patterns
---

# Resource Provider Trees

Resource providers form forest structures (multiple trees) where each tree represents a compute host with its nested resources.

## Basic Tree Structure

```
┌─────────────────────────────────────────────────────────────────┐
│                    COMPUTE HOST TREE                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  (:ResourceProvider {name: "compute-001"})  ◄─── Root Provider  │
│       │                                                         │
│       ├──[:PARENT_OF]──► (:ResourceProvider {name: "numa-0"})   │
│       │                       │                                 │
│       │                       ├──[:PARENT_OF]──► (:RP "pf-0")   │
│       │                       │                    │            │
│       │                       │        ┌───────────┴───────┐    │
│       │                       │        ▼                   ▼    │
│       │                       │   (:RP "vf-0-0")    (:RP "vf-0-1")
│       │                       │                                 │
│       │                       └──[:PARENT_OF]──► (:RP "pf-1")   │
│       │                                                         │
│       └──[:PARENT_OF]──► (:ResourceProvider {name: "numa-1"})   │
│                               │                                 │
│                               └──[:PARENT_OF]──► (:RP "gpu-0")  │
│                                                    │            │
│                                        ┌───────────┴───────┐    │
│                                        ▼                   ▼    │
│                                  (:RP "vgpu-0")    (:RP "vgpu-1")│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Tree Creation Pattern

```cypher
// Create compute host (root provider)
CREATE (root:ResourceProvider {
  uuid: randomUUID(),
  name: 'compute-001',
  generation: 1,
  disabled: false,
  created_at: datetime(),
  updated_at: datetime()
})

// Create NUMA node 0 as child
CREATE (numa0:ResourceProvider {
  uuid: randomUUID(),
  name: 'compute-001_numa_0',
  generation: 1,
  created_at: datetime(),
  updated_at: datetime()
})
CREATE (root)-[:PARENT_OF]->(numa0)

// Create NUMA node 1 as child
CREATE (numa1:ResourceProvider {
  uuid: randomUUID(),
  name: 'compute-001_numa_1',
  generation: 1,
  created_at: datetime(),
  updated_at: datetime()
})
CREATE (root)-[:PARENT_OF]->(numa1)
```

## Root Provider Queries

```cypher
// Find root provider for any provider in tree
MATCH (rp:ResourceProvider {uuid: $uuid})
MATCH path = (root:ResourceProvider)-[:PARENT_OF*0..]->(rp)
WHERE NOT ()-[:PARENT_OF]->(root)
RETURN root

// Alternative: Follow PARENT_OF backwards
MATCH (rp:ResourceProvider {uuid: $uuid})
OPTIONAL MATCH (rp)<-[:PARENT_OF*]-(root)
WHERE NOT ()-[:PARENT_OF]->(root)
RETURN COALESCE(root, rp) AS root
```

## Tree Traversal Queries

```cypher
// Get entire tree from root
MATCH (root:ResourceProvider {uuid: $root_uuid})
OPTIONAL MATCH (root)-[:PARENT_OF*]->(descendant)
RETURN root, collect(descendant) AS descendants

// Get subtree from any node
MATCH (node:ResourceProvider {uuid: $uuid})
MATCH path = (node)-[:PARENT_OF*0..]->(descendant)
RETURN node, collect(DISTINCT descendant) AS subtree

// Find depth of provider in tree
MATCH (rp:ResourceProvider {uuid: $uuid})
MATCH path = (root)-[:PARENT_OF*0..]->(rp)
WHERE NOT ()-[:PARENT_OF]->(root)
RETURN length(path) AS depth
```

## in_tree Constraint

Limit search to specific provider tree:

```cypher
// Only consider providers in specific tree
MATCH (root:ResourceProvider {uuid: $in_tree_uuid})
MATCH (root)-[:PARENT_OF*0..]->(rp)
RETURN rp
```

## Allocation Candidates with Tree

```cypher
// Find allocation candidates within tree
MATCH (root:ResourceProvider {uuid: $in_tree_uuid})
MATCH (root)-[:PARENT_OF*0..]->(provider)
MATCH (provider)-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(rc:ResourceClass)
WHERE rc.name IN $required_resources
RETURN root, provider, inv, rc
```

## Constraints

- No cycles in PARENT_OF relationships
- Each provider has at most one parent
- Root providers have no incoming PARENT_OF
- Deleting a provider requires deleting children first

