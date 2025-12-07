---
title: vGPU Modeling
description: Virtual GPU as child resource providers of physical GPUs
keywords: [vgpu, gpu, nvidia, physical-gpu, vgpu-type]
related:
  - 02-patterns/pci-hierarchy.md
  - 01-schema/nodes/infrastructure.md
implements:
  - "vGPU resources"
  - "Multiple vGPU types per GPU"
section: patterns
---

# vGPU Modeling

Virtual GPUs are modeled as child resource providers of physical GPU providers.

## vGPU Tree Structure

```
(:ResourceProvider:ComputeHost)
    │
    └──[:PARENT_OF]──► (:ResourceProvider:NUMANode)
                            │
                            └──[:PARENT_OF]──► (:ResourceProvider:PhysicalGPU)
                                                   │
                                                   ├── name: "compute-001_pci_0000:82:00.0"
                                                   ├── address: "0000:82:00.0"
                                                   │
                                                   ├──[:HAS_TRAIT]──► (:Trait {name: 'CUSTOM_NVIDIA_A100'})
                                                   │
                                                   └──[:PARENT_OF]──► (:ResourceProvider:vGPUType)
                                                                          │
                                                                          ├── name: "nvidia-35"
                                                                          ├── Inventory: VGPU (total: 8)
                                                                          │
                                                                          └──[:HAS_TRAIT]──► (:Trait {name: 'CUSTOM_VGPU_NVIDIA_35'})
```

## vGPU Creation Pattern

```cypher
// Create physical GPU resource provider
MATCH (numa:ResourceProvider:NUMANode {name: 'compute-001_numa_1'})

CREATE (pgpu:ResourceProvider:PhysicalGPU {
  uuid: randomUUID(),
  name: 'compute-001_pci_0000:82:00.0',
  address: '0000:82:00.0',
  generation: 1,
  created_at: datetime(),
  updated_at: datetime()
})
CREATE (numa)-[:PARENT_OF]->(pgpu)

// Add GPU trait
MERGE (gpu_trait:Trait {
  name: 'CUSTOM_NVIDIA_A100', 
  standard: false, 
  created_at: datetime(), 
  updated_at: datetime()
})
CREATE (pgpu)-[:HAS_TRAIT]->(gpu_trait)

// Create vGPU type resource provider
CREATE (vgpu_type:ResourceProvider:vGPUType {
  uuid: randomUUID(),
  name: 'compute-001_pci_0000:82:00.0_nvidia-35',
  vgpu_type: 'nvidia-35',
  generation: 1,
  created_at: datetime(),
  updated_at: datetime()
})
CREATE (pgpu)-[:PARENT_OF]->(vgpu_type)

// Add VGPU inventory
MATCH (rc:ResourceClass {name: 'VGPU'})
CREATE (vgpu_type)-[:HAS_INVENTORY]->(inv:Inventory {
  total: 8,
  reserved: 0,
  min_unit: 1,
  max_unit: 8,
  step_size: 1,
  allocation_ratio: 1.0,
  created_at: datetime(),
  updated_at: datetime()
})-[:OF_CLASS]->(rc)

// Add vGPU type trait
MERGE (vgpu_trait:Trait {
  name: 'CUSTOM_VGPU_NVIDIA_35', 
  standard: false, 
  created_at: datetime(), 
  updated_at: datetime()
})
CREATE (vgpu_type)-[:HAS_TRAIT]->(vgpu_trait)
```

## Find Available vGPUs by Type

```cypher
// Find hosts with available vGPUs of specific type
MATCH (host:ResourceProvider)-[:PARENT_OF*]->(vgpu_type:vGPUType)
      -[:HAS_TRAIT]->(:Trait {name: $vgpu_type_trait})
MATCH (vgpu_type)-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(:ResourceClass {name: 'VGPU'})

OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
WITH host, vgpu_type, inv,
     inv.total - inv.reserved - COALESCE(sum(alloc.used), 0) AS available

WHERE available >= $required_count
RETURN host, vgpu_type, available
```

## Find vGPUs with GPU Model

```cypher
// Find vGPUs on specific GPU model
MATCH (host:ResourceProvider)-[:PARENT_OF*]->(pgpu:PhysicalGPU)
      -[:HAS_TRAIT]->(:Trait {name: $gpu_model_trait})
MATCH (pgpu)-[:PARENT_OF]->(vgpu_type:vGPUType)
      -[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(:ResourceClass {name: 'VGPU'})

OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
WITH host, pgpu, vgpu_type, inv,
     inv.total - inv.reserved - COALESCE(sum(alloc.used), 0) AS available

WHERE available >= 1
RETURN host, pgpu, vgpu_type, available
```

## Multiple vGPU Types per GPU

A single physical GPU can support multiple vGPU types:

```cypher
// Create additional vGPU type on same physical GPU
MATCH (pgpu:ResourceProvider:PhysicalGPU {name: 'compute-001_pci_0000:82:00.0'})

CREATE (vgpu_type2:ResourceProvider:vGPUType {
  uuid: randomUUID(),
  name: 'compute-001_pci_0000:82:00.0_nvidia-36',
  vgpu_type: 'nvidia-36',
  generation: 1,
  created_at: datetime(),
  updated_at: datetime()
})
CREATE (pgpu)-[:PARENT_OF]->(vgpu_type2)

// Different inventory for this type
MATCH (rc:ResourceClass {name: 'VGPU'})
CREATE (vgpu_type2)-[:HAS_INVENTORY]->(inv:Inventory {
  total: 4,  // Fewer, larger vGPUs
  reserved: 0,
  min_unit: 1,
  max_unit: 4,
  step_size: 1,
  allocation_ratio: 1.0,
  created_at: datetime(),
  updated_at: datetime()
})-[:OF_CLASS]->(rc)
```

## vGPU with NUMA Affinity

```cypher
// Find vGPUs on same NUMA as CPU/memory allocation
MATCH (host:ResourceProvider)-[:PARENT_OF]->(numa:NUMANode)
      -[:PARENT_OF]->(pgpu:PhysicalGPU)
      -[:PARENT_OF]->(vgpu_type:vGPUType)
MATCH (vgpu_type)-[:HAS_INVENTORY]->(vgpu_inv)-[:OF_CLASS]->(:ResourceClass {name: 'VGPU'})
MATCH (numa)-[:HAS_INVENTORY]->(vcpu_inv)-[:OF_CLASS]->(:ResourceClass {name: 'VCPU'})
MATCH (numa)-[:HAS_INVENTORY]->(mem_inv)-[:OF_CLASS]->(:ResourceClass {name: 'MEMORY_MB'})

// Check availability on same NUMA
OPTIONAL MATCH (vgpu_inv)<-[v:CONSUMES]-()
OPTIONAL MATCH (vcpu_inv)<-[c:CONSUMES]-()
OPTIONAL MATCH (mem_inv)<-[m:CONSUMES]-()

WITH host, numa, vgpu_type,
     vgpu_inv.total - COALESCE(sum(v.used), 0) AS vgpu_avail,
     vcpu_inv.total - COALESCE(sum(c.used), 0) AS vcpu_avail,
     mem_inv.total - COALESCE(sum(m.used), 0) AS mem_avail

WHERE vgpu_avail >= 1 AND vcpu_avail >= $vcpus AND mem_avail >= $memory_mb

RETURN host, numa, vgpu_type
```

