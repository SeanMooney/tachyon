---
title: NUMA Topology
description: Modeling NUMA nodes as nested resource providers
keywords: [numa, topology, cpu-pinning, memory, hugepages, cpuset, siblings]
related:
  - 02-patterns/provider-trees.md
  - 01-schema/nodes/infrastructure.md
  - 03-constraints/topology-constraints.md
implements:
  - "NUMA-aware scheduling"
  - "CPU pinning"
  - "Hugepages"
section: patterns
---

# NUMA Topology

NUMA topology is modeled as nested resource providers with specialized NUMANode labels and properties.

## NUMA Tree Structure

```
(:ResourceProvider:ComputeHost)
    │
    ├──[:PARENT_OF]──► (:ResourceProvider:NUMANode {cell_id: 0})
    │                       │
    │                       ├── Inventories: VCPU, MEMORY_MB, PCPU
    │                       │
    │                       └── Properties:
    │                             cpuset: [0,1,2,3,4,5,6,7]
    │                             pcpuset: [0,1,2,3]
    │                             memory_mb: 65536
    │                             siblings: [[0,8],[1,9],[2,10],[3,11],...]
    │                             hugepages: {2048: 1024, 1048576: 4}
    │
    └──[:PARENT_OF]──► (:ResourceProvider:NUMANode {cell_id: 1})
                            │
                            └── Properties:
                                  cpuset: [8,9,10,11,12,13,14,15]
                                  ...
```

## NUMA Creation Pattern

```cypher
// Create compute host with NUMA topology
CREATE (host:ResourceProvider:ComputeHost {
  uuid: randomUUID(),
  name: 'compute-001',
  generation: 1,
  created_at: datetime(),
  updated_at: datetime()
})

// Create NUMA node 0
CREATE (numa0:ResourceProvider:NUMANode {
  uuid: randomUUID(),
  name: 'compute-001_numa_0',
  cell_id: 0,
  cpuset: [0,1,2,3,4,5,6,7],
  pcpuset: [0,1,2,3],
  memory_mb: 65536,
  siblings: [[0,8],[1,9],[2,10],[3,11],[4,12],[5,13],[6,14],[7,15]],
  hugepages: {2048: 1024, 1048576: 4},
  generation: 1,
  created_at: datetime(),
  updated_at: datetime()
})
CREATE (host)-[:PARENT_OF]->(numa0)

// Add NUMA node inventories
MATCH (rc_vcpu:ResourceClass {name: 'VCPU'})
MATCH (rc_mem:ResourceClass {name: 'MEMORY_MB'})
MATCH (rc_pcpu:ResourceClass {name: 'PCPU'})

CREATE (numa0)-[:HAS_INVENTORY]->(inv_vcpu:Inventory {
  total: 8,
  reserved: 0,
  min_unit: 1,
  max_unit: 8,
  step_size: 1,
  allocation_ratio: 1.0,
  created_at: datetime(),
  updated_at: datetime()
})-[:OF_CLASS]->(rc_vcpu)

CREATE (numa0)-[:HAS_INVENTORY]->(inv_mem:Inventory {
  total: 65536,
  reserved: 512,
  min_unit: 1,
  max_unit: 65536,
  step_size: 1,
  allocation_ratio: 1.0,
  created_at: datetime(),
  updated_at: datetime()
})-[:OF_CLASS]->(rc_mem)
```

## NUMA Scheduling Query

Find NUMA nodes that can satisfy CPU and memory requirements:

```cypher
MATCH (host:ResourceProvider)-[:PARENT_OF]->(numa:NUMANode)
MATCH (numa)-[:HAS_INVENTORY]->(vcpu_inv)-[:OF_CLASS]->(:ResourceClass {name: 'VCPU'})
MATCH (numa)-[:HAS_INVENTORY]->(mem_inv)-[:OF_CLASS]->(:ResourceClass {name: 'MEMORY_MB'})

// Calculate available resources
OPTIONAL MATCH (vcpu_inv)<-[vc:CONSUMES]-()
OPTIONAL MATCH (mem_inv)<-[mc:CONSUMES]-()

WITH host, numa, vcpu_inv, mem_inv,
     (vcpu_inv.total - vcpu_inv.reserved) * vcpu_inv.allocation_ratio AS vcpu_capacity,
     COALESCE(sum(vc.used), 0) AS vcpu_used,
     (mem_inv.total - mem_inv.reserved) * mem_inv.allocation_ratio AS mem_capacity,
     COALESCE(sum(mc.used), 0) AS mem_used

WHERE vcpu_capacity - vcpu_used >= $required_vcpus
  AND mem_capacity - mem_used >= $required_memory_mb

RETURN host, numa, 
       vcpu_capacity - vcpu_used AS available_vcpus,
       mem_capacity - mem_used AS available_memory_mb
```

## Multi-NUMA Instance

For instances requiring multiple NUMA nodes:

```cypher
// Find hosts with N NUMA nodes that can satisfy requirements
MATCH (host:ResourceProvider)-[:PARENT_OF]->(numa:NUMANode)
MATCH (numa)-[:HAS_INVENTORY]->(vcpu_inv)-[:OF_CLASS]->(:ResourceClass {name: 'VCPU'})
MATCH (numa)-[:HAS_INVENTORY]->(mem_inv)-[:OF_CLASS]->(:ResourceClass {name: 'MEMORY_MB'})

OPTIONAL MATCH (vcpu_inv)<-[vc:CONSUMES]-()
OPTIONAL MATCH (mem_inv)<-[mc:CONSUMES]-()

WITH host, numa,
     (vcpu_inv.total - vcpu_inv.reserved) - COALESCE(sum(vc.used), 0) AS avail_vcpus,
     (mem_inv.total - mem_inv.reserved) - COALESCE(sum(mc.used), 0) AS avail_mem

// Collect suitable NUMA nodes per host
WITH host, collect({
  numa: numa,
  avail_vcpus: avail_vcpus,
  avail_mem: avail_mem
}) AS numa_nodes

// Filter to hosts with enough suitable NUMA nodes
WHERE size([n IN numa_nodes WHERE n.avail_vcpus >= $min_vcpus_per_node 
                               AND n.avail_mem >= $min_mem_per_node]) >= $numa_nodes

RETURN host, numa_nodes
```

## Hugepages Query

```cypher
// Find NUMA nodes with specific hugepage configuration
MATCH (host:ResourceProvider)-[:PARENT_OF]->(numa:NUMANode)
WHERE numa.hugepages[$hugepage_size_kb] >= $required_pages
RETURN host, numa
```

