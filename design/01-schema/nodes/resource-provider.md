---
title: ResourceProvider Node
description: Core entity representing a source of resources, forms hierarchical trees
keywords: [resource-provider, compute-node, hierarchy, tree, generation, uuid]
related:
  - 01-schema/relationships/hierarchy.md
  - 02-patterns/provider-trees.md
implements:
  - "Nested resource provider trees"
  - "Compute host modeling"
section: schema/nodes
---

# ResourceProvider Node

The fundamental entity representing a source of resources. Forms hierarchical trees with parent-child relationships.

## Schema

```
:ResourceProvider
  uuid:         String!    # External identifier (UUID format)
  name:         String!    # Human-readable name (unique, max 200 chars)
  generation:   Integer!   # Optimistic concurrency version (auto-increment)
  disabled:     Boolean    # Whether provider is disabled for scheduling
  created_at:   DateTime!
  updated_at:   DateTime!
```

## Constraints

- `uuid` must be unique across all ResourceProvider nodes
- `name` must be unique across all ResourceProvider nodes
- Root providers have no incoming `:PARENT_OF` relationship
- `generation` increments on inventory, trait, or aggregate changes

## Example

```cypher
CREATE (rp:ResourceProvider {
  uuid: 'c0f3dbf7-0e32-4d4f-8f7c-4c2a5c6e8d9b',
  name: 'compute-node-001',
  generation: 1,
  disabled: false,
  created_at: datetime(),
  updated_at: datetime()
})
```

## Placement API Mapping

| Placement Field | Tachyon Property |
|-----------------|------------------|
| `id` | (not stored, use uuid) |
| `uuid` | `uuid` |
| `name` | `name` |
| `generation` | `generation` |
| `root_provider_id` | (computed via PARENT_OF traversal) |
| `parent_provider_id` | (incoming PARENT_OF relationship) |

## Common Queries

```cypher
// Find root provider for any node
MATCH (rp:ResourceProvider {uuid: $uuid})
MATCH path = (root:ResourceProvider)-[:PARENT_OF*0..]->(rp)
WHERE NOT ()-[:PARENT_OF]->(root)
RETURN root

// Find all descendants
MATCH (root:ResourceProvider {uuid: $uuid})
MATCH (root)-[:PARENT_OF*]->(descendant)
RETURN descendant
```

## Additional Labels

ResourceProvider nodes may have additional labels for specialization:

| Label | Description |
|-------|-------------|
| `:ComputeHost` | Root compute node |
| `:NUMANode` | NUMA cell within compute host |
| `:PCIPF` | PCI Physical Function |
| `:PCIVF` | PCI Virtual Function |
| `:PhysicalGPU` | Physical GPU device |
| `:vGPUType` | Virtual GPU type provider |

