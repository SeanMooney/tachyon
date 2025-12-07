---
title: Sharing Providers
description: Shared storage and cross-tree resource sharing
keywords: [sharing, shared-storage, misc-shares-via-aggregate, disk-gb]
related:
  - 02-patterns/provider-trees.md
  - 01-schema/relationships/scheduling.md
implements:
  - "Sharing resource providers"
  - "Shared storage pools"
section: patterns
---

# Sharing Providers

Sharing providers (e.g., shared storage) share resources with multiple trees.

## Sharing Provider Pattern

```
(:ResourceProvider {name: "shared-storage-001"})
    │
    ├── Inventory: DISK_GB (total: 100000)
    │
    ├──[:HAS_TRAIT]──► (:Trait {name: 'MISC_SHARES_VIA_AGGREGATE'})
    │
    ├──[:MEMBER_OF]──► (:Aggregate {name: "shared-storage-agg"})
    │                       │
    │                       ├──[:MEMBER_OF]── (:ResourceProvider {name: "compute-001"})
    │                       ├──[:MEMBER_OF]── (:ResourceProvider {name: "compute-002"})
    │                       └──[:MEMBER_OF]── (:ResourceProvider {name: "compute-003"})
    │
    └──[:SHARES_RESOURCES {resource_classes: ['DISK_GB']}]──► (:ResourceProvider compute-001)
       [:SHARES_RESOURCES {resource_classes: ['DISK_GB']}]──► (:ResourceProvider compute-002)
       [:SHARES_RESOURCES {resource_classes: ['DISK_GB']}]──► (:ResourceProvider compute-003)
```

## Sharing Provider Creation

```cypher
// Create shared storage provider
CREATE (storage:ResourceProvider {
  uuid: randomUUID(),
  name: 'shared-storage-001',
  generation: 1,
  created_at: datetime(),
  updated_at: datetime()
})

// Add DISK_GB inventory
MATCH (rc:ResourceClass {name: 'DISK_GB'})
CREATE (storage)-[:HAS_INVENTORY]->(inv:Inventory {
  total: 100000,
  reserved: 1000,
  min_unit: 1,
  max_unit: 10000,
  step_size: 1,
  allocation_ratio: 1.0,
  created_at: datetime(),
  updated_at: datetime()
})-[:OF_CLASS]->(rc)

// Add sharing trait
MERGE (sharing_trait:Trait {name: 'MISC_SHARES_VIA_AGGREGATE'})
CREATE (storage)-[:HAS_TRAIT]->(sharing_trait)

// Create aggregate and memberships
CREATE (agg:Aggregate {
  uuid: randomUUID(), 
  name: 'shared-storage-agg', 
  created_at: datetime(), 
  updated_at: datetime()
})
CREATE (storage)-[:MEMBER_OF]->(agg)

// Add compute nodes to aggregate and create SHARES_RESOURCES relationships
MATCH (compute:ResourceProvider)
WHERE compute.name STARTS WITH 'compute-'
CREATE (compute)-[:MEMBER_OF]->(agg)
CREATE (storage)-[:SHARES_RESOURCES {resource_classes: ['DISK_GB']}]->(compute)
```

## Allocation Candidates with Shared Storage

```cypher
// Find allocation candidates including shared DISK_GB
MATCH (compute:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(compute)

// Get compute's own inventories
MATCH (compute)-[:HAS_INVENTORY]->(vcpu_inv)-[:OF_CLASS]->(:ResourceClass {name: 'VCPU'})
MATCH (compute)-[:HAS_INVENTORY]->(mem_inv)-[:OF_CLASS]->(:ResourceClass {name: 'MEMORY_MB'})

// Include shared storage
OPTIONAL MATCH (storage:ResourceProvider)-[:SHARES_RESOURCES]->(compute)
MATCH (storage)-[:HAS_INVENTORY]->(disk_inv)-[:OF_CLASS]->(:ResourceClass {name: 'DISK_GB'})

// Check capacities
OPTIONAL MATCH (vcpu_inv)<-[vc:CONSUMES]-()
OPTIONAL MATCH (mem_inv)<-[mc:CONSUMES]-()
OPTIONAL MATCH (disk_inv)<-[dc:CONSUMES]-()

WITH compute, storage, 
     vcpu_inv, mem_inv, disk_inv,
     (vcpu_inv.total - vcpu_inv.reserved) - COALESCE(sum(vc.used), 0) AS vcpu_avail,
     (mem_inv.total - mem_inv.reserved) - COALESCE(sum(mc.used), 0) AS mem_avail,
     (disk_inv.total - disk_inv.reserved) - COALESCE(sum(dc.used), 0) AS disk_avail

WHERE vcpu_avail >= $vcpus AND mem_avail >= $memory_mb AND disk_avail >= $disk_gb

RETURN compute, storage, vcpu_avail, mem_avail, disk_avail
```

## Finding Sharing Providers via Aggregate

Traditional aggregate-based sharing lookup:

```cypher
// Find sharing providers for a compute node via aggregate
MATCH (compute:ResourceProvider {uuid: $compute_uuid})
      -[:MEMBER_OF]->(agg:Aggregate)<-[:MEMBER_OF]-(sharing:ResourceProvider)
      -[:HAS_TRAIT]->(:Trait {name: 'MISC_SHARES_VIA_AGGREGATE'})
MATCH (sharing)-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(rc:ResourceClass)
RETURN sharing, rc.name AS resource_class, inv
```

## SHARES_RESOURCES vs Aggregate Query

The `SHARES_RESOURCES` relationship provides a direct path:

```cypher
// Direct relationship (faster)
MATCH (sharing)-[:SHARES_RESOURCES]->(compute:ResourceProvider {uuid: $compute_uuid})
MATCH (sharing)-[:HAS_INVENTORY]->(inv)
RETURN sharing, inv

// vs Aggregate traversal (traditional)
MATCH (compute:ResourceProvider {uuid: $compute_uuid})
      -[:MEMBER_OF]->(agg)<-[:MEMBER_OF]-(sharing)
      -[:HAS_TRAIT]->(:Trait {name: 'MISC_SHARES_VIA_AGGREGATE'})
MATCH (sharing)-[:HAS_INVENTORY]->(inv)
RETURN sharing, inv
```

## Multiple Sharing Providers

A compute node can have multiple sharing providers:

```cypher
// Compute with shared storage and shared IP pool
MATCH (compute:ResourceProvider {uuid: $compute_uuid})

// Shared storage
OPTIONAL MATCH (storage)-[:SHARES_RESOURCES {resource_classes: ['DISK_GB']}]->(compute)
OPTIONAL MATCH (storage)-[:HAS_INVENTORY]->(disk_inv)-[:OF_CLASS]->(:ResourceClass {name: 'DISK_GB'})

// Shared IP pool
OPTIONAL MATCH (ip_pool)-[:SHARES_RESOURCES {resource_classes: ['IPV4_ADDRESS']}]->(compute)
OPTIONAL MATCH (ip_pool)-[:HAS_INVENTORY]->(ip_inv)-[:OF_CLASS]->(:ResourceClass {name: 'IPV4_ADDRESS'})

RETURN compute, storage, disk_inv, ip_pool, ip_inv
```

