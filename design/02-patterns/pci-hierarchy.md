---
title: PCI Device Hierarchy
description: Modeling PCI devices, SR-IOV PF/VF relationships
keywords: [pci, sriov, physical-function, virtual-function, passthrough, physnet]
related:
  - 02-patterns/numa-topology.md
  - 01-schema/nodes/infrastructure.md
  - 03-constraints/topology-constraints.md
implements:
  - "PCI passthrough"
  - "SR-IOV virtual functions"
  - "PCI-NUMA affinity"
section: patterns
---

# PCI Device Hierarchy

PCI devices form their own hierarchy with Physical Functions (PFs) as parents of Virtual Functions (VFs).

## PCI Tree Structure

```
(:ResourceProvider:ComputeHost)
    │
    ├──[:PARENT_OF]──► (:ResourceProvider:NUMANode {cell_id: 0})
    │                       │
    │                       └──[:PARENT_OF]──► (:ResourceProvider:PCIPF)
    │                                              │
    │                                              ├── address: "0000:04:00.0"
    │                                              ├── vendor_id: "15b3"
    │                                              ├── product_id: "1017"
    │                                              │
    │                                              ├──[:PARENT_OF]──► (:RP:PCIVF)
    │                                              │                    address: "0000:04:00.1"
    │                                              │
    │                                              ├──[:PARENT_OF]──► (:RP:PCIVF)
    │                                              │                    address: "0000:04:00.2"
    │                                              │
    │                                              └──[:PARENT_OF]──► (:RP:PCIVF)
    │                                                                   address: "0000:04:00.3"
    │
    └──[:HAS_PCI_DEVICE]──► (:PCIDevice)  // Flat reference for quick lookup
```

## PCI Device Creation Pattern

```cypher
// Create PF resource provider under NUMA node
MATCH (numa:ResourceProvider:NUMANode {name: 'compute-001_numa_0'})

CREATE (pf:ResourceProvider:PCIPF {
  uuid: randomUUID(),
  name: 'compute-001_0000:04:00.0',
  address: '0000:04:00.0',
  vendor_id: '15b3',
  product_id: '1017',
  generation: 1,
  created_at: datetime(),
  updated_at: datetime()
})
CREATE (numa)-[:PARENT_OF]->(pf)

// Add trait for physnet
MERGE (physnet:Trait {name: 'CUSTOM_PHYSNET_PROVIDER1'})
CREATE (pf)-[:HAS_TRAIT]->(physnet)

// Create VF resource providers
UNWIND range(1, 8) AS vf_num
CREATE (vf:ResourceProvider:PCIVF {
  uuid: randomUUID(),
  name: 'compute-001_0000:04:00.' + toString(vf_num),
  address: '0000:04:00.' + toString(vf_num),
  generation: 1,
  created_at: datetime(),
  updated_at: datetime()
})
CREATE (pf)-[:PARENT_OF]->(vf)

// Add SRIOV_NET_VF inventory to each VF
WITH vf
MATCH (rc:ResourceClass {name: 'SRIOV_NET_VF'})
CREATE (vf)-[:HAS_INVENTORY]->(inv:Inventory {
  total: 1,
  reserved: 0,
  min_unit: 1,
  max_unit: 1,
  step_size: 1,
  allocation_ratio: 1.0,
  created_at: datetime(),
  updated_at: datetime()
})-[:OF_CLASS]->(rc)
```

## Find Available VFs with Physnet

```cypher
// Find available VFs with specific physnet
MATCH (host:ResourceProvider)-[:PARENT_OF*]->(pf:PCIPF)
      -[:HAS_TRAIT]->(:Trait {name: $physnet_trait})
MATCH (pf)-[:PARENT_OF]->(vf:PCIVF)
      -[:HAS_INVENTORY]->(inv)
      -[:OF_CLASS]->(:ResourceClass {name: 'SRIOV_NET_VF'})
WHERE NOT (inv)<-[:CONSUMES]-()
RETURN host, pf, vf
```

## PCI-NUMA Affinity Query

```cypher
// Policy: required - PCI must be on same NUMA as instance
MATCH (host:ResourceProvider)-[:PARENT_OF]->(numa:NUMANode)
MATCH (numa)-[:PARENT_OF*]->(pci_provider)
      -[:HAS_INVENTORY]->(pci_inv)
      -[:OF_CLASS]->(:ResourceClass {name: 'SRIOV_NET_VF'})
WHERE NOT (pci_inv)<-[:CONSUMES]-()

// Instance resources must come from same NUMA
MATCH (numa)-[:HAS_INVENTORY]->(vcpu_inv)-[:OF_CLASS]->(:ResourceClass {name: 'VCPU'})
MATCH (numa)-[:HAS_INVENTORY]->(mem_inv)-[:OF_CLASS]->(:ResourceClass {name: 'MEMORY_MB'})

RETURN host, numa, pci_provider, vcpu_inv, mem_inv
```

## Find PCI Devices on Same NUMA as Instance

```cypher
// Find PCI devices on same NUMA node as existing instance
MATCH (consumer:Consumer {uuid: $instance_uuid})
      -[:CONSUMES]->()<-[:HAS_INVENTORY]-(numa:NUMANode)
MATCH (numa)-[:PARENT_OF*]->(vf:PCIVF)
      -[:HAS_INVENTORY]->(inv)
WHERE NOT (inv)<-[:CONSUMES]-()
RETURN vf, inv
```

## PCI Device by Vendor/Product

```cypher
// Find devices matching vendor and product ID
MATCH (host:ResourceProvider)-[:PARENT_OF*]->(pf:PCIPF)
WHERE pf.vendor_id = $vendor_id
  AND pf.product_id = $product_id
MATCH (pf)-[:PARENT_OF]->(vf:PCIVF)
      -[:HAS_INVENTORY]->(inv)
WHERE NOT (inv)<-[:CONSUMES]-()
RETURN host, pf, vf
```

## Trusted VF Pattern

```cypher
// Find trusted VFs (have CUSTOM_TRUSTED trait)
MATCH (host:ResourceProvider)-[:PARENT_OF*]->(vf:PCIVF)
      -[:HAS_TRAIT]->(:Trait {name: 'CUSTOM_TRUSTED'})
MATCH (vf)-[:HAS_INVENTORY]->(inv)
WHERE NOT (inv)<-[:CONSUMES]-()
RETURN host, vf
```
