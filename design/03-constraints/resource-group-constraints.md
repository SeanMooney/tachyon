---
title: Resource Group Constraints
description: group_policy (isolate/none), in_tree, same_subtree
keywords: [group-policy, isolate, in-tree, resource-group, granular-request]
related:
  - 02-patterns/provider-trees.md
  - 04-queries/allocation-candidates.md
implements:
  - "Granular resource groups"
  - "group_policy isolation"
  - "in_tree filtering"
section: constraints
---

# Resource Group Constraints

## Resource Groups Overview

Placement API supports granular resource requests with numbered groups:

- Unnumbered group: Main resources (VCPU, MEMORY_MB)
- Group `1`, `2`, etc.: Additional requirements (PCI, bandwidth)
- `group_policy`: Controls how groups map to providers

## group_policy Values

| Policy | Behavior |
|--------|----------|
| `none` | Groups can share providers |
| `isolate` | Each group uses different providers |

## Group Policy: None

Groups can share the same provider.

```cypher
// Find providers that can satisfy multiple groups (may overlap)
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// Unnumbered group: VCPU, MEMORY_MB
MATCH (host)-[:HAS_INVENTORY]->(vcpu_inv)-[:OF_CLASS]->(:ResourceClass {name: 'VCPU'})
MATCH (host)-[:HAS_INVENTORY]->(mem_inv)-[:OF_CLASS]->(:ResourceClass {name: 'MEMORY_MB'})

// Group 1: SRIOV_NET_VF
MATCH (host)-[:PARENT_OF*0..]->(net_provider)
      -[:HAS_INVENTORY]->(net_inv)
      -[:OF_CLASS]->(:ResourceClass {name: 'SRIOV_NET_VF'})

// Check availability (groups may use same provider)
OPTIONAL MATCH (vcpu_inv)<-[vc:CONSUMES]-()
OPTIONAL MATCH (mem_inv)<-[mc:CONSUMES]-()
OPTIONAL MATCH (net_inv)<-[nc:CONSUMES]-()

WITH host, net_provider,
     vcpu_inv.total - COALESCE(sum(vc.used), 0) AS vcpu_avail,
     mem_inv.total - COALESCE(sum(mc.used), 0) AS mem_avail,
     net_inv.total - COALESCE(sum(nc.used), 0) AS net_avail

WHERE vcpu_avail >= $vcpus AND mem_avail >= $memory_mb AND net_avail >= 1

RETURN host, net_provider
```

## Group Policy: Isolate

Each numbered resource group must use different providers.

```cypher
// Find candidates where each group uses distinct providers
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// For group 1: find providers for group 1 resources
MATCH (host)-[:PARENT_OF*0..]->(g1_provider)
      -[:HAS_INVENTORY]->(g1_inv)
      -[:OF_CLASS]->(:ResourceClass {name: $group1_rc})
      -[:HAS_TRAIT]->(:Trait {name: $group1_trait})
WHERE NOT (g1_inv)<-[:CONSUMES]-()

// For group 2: find DIFFERENT providers for group 2 resources
MATCH (host)-[:PARENT_OF*0..]->(g2_provider)
      -[:HAS_INVENTORY]->(g2_inv)
      -[:OF_CLASS]->(:ResourceClass {name: $group2_rc})
      -[:HAS_TRAIT]->(:Trait {name: $group2_trait})
WHERE NOT (g2_inv)<-[:CONSUMES]-()
  AND g2_provider <> g1_provider  // Isolation constraint

RETURN host, g1_provider, g2_provider
```

## in_tree Constraint

Limit resource search to specific provider tree.

```cypher
// resources=VCPU:4&in_tree=<compute_uuid>
MATCH (root:ResourceProvider {uuid: $in_tree_uuid})
MATCH (root)-[:PARENT_OF*0..]->(provider)
      -[:HAS_INVENTORY]->(inv)
      -[:OF_CLASS]->(:ResourceClass {name: 'VCPU'})

OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
WITH root, provider, inv,
     inv.total - inv.reserved - COALESCE(sum(alloc.used), 0) AS available

WHERE available >= $vcpus
RETURN root, provider, available
```

## same_subtree Constraint

Resources from different groups must share a common ancestor.

```cypher
// Resources in groups must come from providers under same ancestor
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// Find common ancestor (e.g., NUMA node)
MATCH (host)-[:PARENT_OF*0..]->(ancestor:NUMANode)

// Group 1 provider under ancestor
MATCH (ancestor)-[:PARENT_OF*0..]->(g1_provider)
      -[:HAS_INVENTORY]->(g1_inv)
      -[:OF_CLASS]->(:ResourceClass {name: $group1_rc})
WHERE NOT (g1_inv)<-[:CONSUMES]-()

// Group 2 provider under SAME ancestor
MATCH (ancestor)-[:PARENT_OF*0..]->(g2_provider)
      -[:HAS_INVENTORY]->(g2_inv)
      -[:OF_CLASS]->(:ResourceClass {name: $group2_rc})
WHERE NOT (g2_inv)<-[:CONSUMES]-()

RETURN host, ancestor, g1_provider, g2_provider
```

## Complete Granular Request Example

```cypher
// Request: VCPU:4,MEMORY_MB:8192 + resources1:SRIOV_NET_VF:1 + resources2:VGPU:1
// With group_policy=isolate

MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// Unnumbered group: root provider
MATCH (host)-[:HAS_INVENTORY]->(vcpu_inv)-[:OF_CLASS]->(:ResourceClass {name: 'VCPU'})
MATCH (host)-[:HAS_INVENTORY]->(mem_inv)-[:OF_CLASS]->(:ResourceClass {name: 'MEMORY_MB'})

// Group 1: SRIOV from some provider
MATCH (host)-[:PARENT_OF*]->(sriov_provider)
      -[:HAS_INVENTORY]->(sriov_inv)
      -[:OF_CLASS]->(:ResourceClass {name: 'SRIOV_NET_VF'})
      -[:HAS_TRAIT]->(:Trait {name: $sriov_trait})

// Group 2: VGPU from DIFFERENT provider (isolate policy)
MATCH (host)-[:PARENT_OF*]->(vgpu_provider)
      -[:HAS_INVENTORY]->(vgpu_inv)
      -[:OF_CLASS]->(:ResourceClass {name: 'VGPU'})
WHERE vgpu_provider <> sriov_provider

// Check all availabilities
OPTIONAL MATCH (vcpu_inv)<-[vc:CONSUMES]-()
OPTIONAL MATCH (mem_inv)<-[mc:CONSUMES]-()
OPTIONAL MATCH (sriov_inv)<-[sc:CONSUMES]-()
OPTIONAL MATCH (vgpu_inv)<-[gc:CONSUMES]-()

WITH host, sriov_provider, vgpu_provider,
     vcpu_inv.total - COALESCE(sum(vc.used), 0) AS vcpu_avail,
     mem_inv.total - COALESCE(sum(mc.used), 0) AS mem_avail,
     sriov_inv.total - COALESCE(sum(sc.used), 0) AS sriov_avail,
     vgpu_inv.total - COALESCE(sum(gc.used), 0) AS vgpu_avail

WHERE vcpu_avail >= 4 AND mem_avail >= 8192
  AND sriov_avail >= 1 AND vgpu_avail >= 1

RETURN host, sriov_provider, vgpu_provider
```
