---
title: Topology Constraints
description: NUMA affinity, PCI-NUMA affinity, same-subtree constraints
keywords: [numa-affinity, pci-numa, same-subtree, topology]
related:
  - 02-patterns/numa-topology.md
  - 02-patterns/pci-hierarchy.md
  - 04-queries/filters/topology-filters.md
implements:
  - "NUMA topology filter"
  - "PCI-NUMA affinity"
  - "Same subtree constraints"
section: constraints
---

# Topology Constraints

## Same NUMA Node for Resources

Ensure all resources come from same NUMA node.

```cypher
// Find NUMA nodes that can satisfy all resource requirements
MATCH (host:ResourceProvider)-[:PARENT_OF]->(numa:NUMANode)

// Check each resource class
UNWIND $resource_requirements AS req
MATCH (numa)-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(:ResourceClass {name: req.resource_class})

// Calculate available capacity
OPTIONAL MATCH (inv)<-[c:CONSUMES]-()
WITH host, numa, inv, req,
     (inv.total - inv.reserved) * inv.allocation_ratio AS capacity,
     COALESCE(sum(c.used), 0) AS used

WHERE capacity - used >= req.amount
WITH host, numa, collect(inv) AS inventories
WHERE size(inventories) = size($resource_requirements)
RETURN host, numa, inventories
```

## PCI-NUMA Affinity Policies

### Policy: Required

PCI device must be on same NUMA as instance resources.

```cypher
// PCI-NUMA affinity: required
MATCH (host:ResourceProvider)-[:PARENT_OF]->(numa:NUMANode)

// PCI device under this NUMA
MATCH (numa)-[:PARENT_OF*]->(pci_provider)
      -[:HAS_INVENTORY]->(pci_inv)
      -[:OF_CLASS]->(:ResourceClass {name: 'SRIOV_NET_VF'})
WHERE NOT (pci_inv)<-[:CONSUMES]-()

// Instance resources from same NUMA
MATCH (numa)-[:HAS_INVENTORY]->(vcpu_inv)-[:OF_CLASS]->(:ResourceClass {name: 'VCPU'})
MATCH (numa)-[:HAS_INVENTORY]->(mem_inv)-[:OF_CLASS]->(:ResourceClass {name: 'MEMORY_MB'})

RETURN host, numa, pci_provider, vcpu_inv, mem_inv
```

### Policy: Preferred

Prefer same NUMA but allow cross-NUMA if necessary.

```cypher
// PCI-NUMA affinity: preferred (weigher)
MATCH (host:ResourceProvider)-[:PARENT_OF]->(cpu_numa:NUMANode)
MATCH (host)-[:PARENT_OF]->(pci_numa:NUMANode)
MATCH (pci_numa)-[:PARENT_OF*]->(pci_provider)
      -[:HAS_INVENTORY]->(pci_inv)
      -[:OF_CLASS]->(:ResourceClass {name: 'SRIOV_NET_VF'})
WHERE NOT (pci_inv)<-[:CONSUMES]-()

// Score: 1.0 for same NUMA, 0.5 for different NUMA
WITH host, cpu_numa, pci_numa, pci_provider,
     CASE WHEN cpu_numa = pci_numa THEN 1.0 ELSE 0.5 END AS numa_affinity_score

RETURN host, cpu_numa, pci_numa, pci_provider, numa_affinity_score
ORDER BY numa_affinity_score DESC
```

### Policy: Legacy

Allow any NUMA combination.

```cypher
// PCI-NUMA affinity: legacy (no constraint)
MATCH (host:ResourceProvider)-[:PARENT_OF*]->(pci_provider)
      -[:HAS_INVENTORY]->(pci_inv)
      -[:OF_CLASS]->(:ResourceClass {name: 'SRIOV_NET_VF'})
WHERE NOT (pci_inv)<-[:CONSUMES]-()

RETURN host, pci_provider
```

## Same Subtree Constraint

Resources must share a common ancestor.

```cypher
// Ensure resources from groups A and B share common subtree
MATCH (host:ResourceProvider)
      -[:PARENT_OF*0..]->(ancestor)
      -[:PARENT_OF*0..]->(provider_a)
MATCH (ancestor)-[:PARENT_OF*0..]->(provider_b)

// provider_a has resources for group A
MATCH (provider_a)-[:HAS_INVENTORY]->(inv_a)
      -[:OF_CLASS]->(:ResourceClass {name: $group_a_rc})

// provider_b has resources for group B
MATCH (provider_b)-[:HAS_INVENTORY]->(inv_b)
      -[:OF_CLASS]->(:ResourceClass {name: $group_b_rc})

// Both under common ancestor (e.g., same NUMA node)
WHERE ancestor:NUMANode  // or other appropriate label

RETURN host, ancestor, provider_a, provider_b
```

## In-Tree Constraint

Limit search to specific provider tree.

```cypher
// Only consider providers in specific tree
MATCH (root:ResourceProvider {uuid: $in_tree_uuid})
MATCH (root)-[:PARENT_OF*0..]->(rp)
RETURN rp
```

## Multi-NUMA Instance Validation

```cypher
// Validate NUMA topology for multi-NUMA instance
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// Find NUMA nodes meeting per-node requirements
MATCH (host)-[:PARENT_OF]->(numa:NUMANode)
MATCH (numa)-[:HAS_INVENTORY]->(vcpu_inv)-[:OF_CLASS]->(:ResourceClass {name: 'VCPU'})
MATCH (numa)-[:HAS_INVENTORY]->(mem_inv)-[:OF_CLASS]->(:ResourceClass {name: 'MEMORY_MB'})

OPTIONAL MATCH (vcpu_inv)<-[vc:CONSUMES]-()
OPTIONAL MATCH (mem_inv)<-[mc:CONSUMES]-()

WITH host, numa,
     (vcpu_inv.total - vcpu_inv.reserved) - COALESCE(sum(vc.used), 0) AS vcpu_avail,
     (mem_inv.total - mem_inv.reserved) - COALESCE(sum(mc.used), 0) AS mem_avail

WHERE vcpu_avail >= $vcpus_per_numa AND mem_avail >= $memory_per_numa

// Count qualifying NUMA nodes
WITH host, collect(numa) AS valid_numas
WHERE size(valid_numas) >= $required_numa_count

RETURN host, valid_numas
```

## CPU Thread Policy

```cypher
// Find NUMA with sibling info for thread policy
MATCH (host:ResourceProvider)-[:PARENT_OF]->(numa:NUMANode)
WHERE numa.siblings IS NOT NULL

// For 'isolate' policy: need exclusive sibling pairs
// For 'prefer' policy: prefer siblings, allow without
// For 'require' policy: must have siblings

WITH host, numa, numa.siblings AS siblings
WHERE $thread_policy = 'require' AND size(siblings) > 0

RETURN host, numa, siblings
```
