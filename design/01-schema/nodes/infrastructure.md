---
title: Infrastructure Nodes
description: Cell, NUMANode, PCIDevice, and vGPU nodes
keywords: [cell, numa, pci, sriov, vgpu, physical-gpu, virtual-function]
related:
  - 01-schema/nodes/resource-provider.md
  - 02-patterns/numa-topology.md
  - 02-patterns/pci-hierarchy.md
implements:
  - "Cell scheduling"
  - "NUMA topology"
  - "PCI passthrough and SR-IOV"
  - "vGPU support"
section: schema/nodes
---

# Infrastructure Nodes

## Cell

Nova cell structure.

```
:Cell
  uuid:       String!       # Cell UUID
  name:       String!       # Cell name
  disabled:   Boolean!      # Whether cell is disabled for scheduling
  created_at: DateTime!
  updated_at: DateTime!
```

### Relationships

| Relationship | Direction | Target | Description |
|--------------|-----------|--------|-------------|
| `LOCATED_IN` | incoming | ResourceProvider | Providers in this cell |

### Cell Queries

```cypher
// Only schedule to enabled cells
MATCH (rp:ResourceProvider)-[:LOCATED_IN]->(cell:Cell)
WHERE cell.disabled = false
RETURN rp
```

---

## NUMANode

NUMA topology node (child of ResourceProvider).

```
:NUMANode
  cell_id:      Integer!    # NUMA cell ID
  cpuset:       List<Int>!  # CPU IDs in this cell
  pcpuset:      List<Int>   # Physical CPU IDs for pinning
  memory_mb:    Integer!    # Total memory in MB
  siblings:     List<List>  # CPU sibling pairs [[0,8],[1,9],...]
  hugepages:    Map         # Hugepage configuration {size_kb: count}
  created_at:   DateTime!
  updated_at:   DateTime!
```

NUMANode is also a ResourceProvider with additional label.

### Example

```cypher
CREATE (numa:ResourceProvider:NUMANode {
  uuid: randomUUID(),
  name: 'compute-001_numa_0',
  cell_id: 0,
  cpuset: [0,1,2,3,4,5,6,7],
  pcpuset: [0,1,2,3],
  memory_mb: 65536,
  siblings: [[0,8],[1,9],[2,10],[3,11]],
  hugepages: {2048: 1024, 1048576: 4},
  generation: 1,
  created_at: datetime(),
  updated_at: datetime()
})
```

---

## PCIDevice

PCI device available for passthrough.

```
:PCIDevice
  address:      String!     # PCI address (0000:04:00.1)
  vendor_id:    String!     # PCI vendor ID (e.g., "8086")
  product_id:   String!     # PCI product ID (e.g., "10ed")
  dev_type:     String!     # type-PCI, type-PF, type-VF
  numa_node:    Integer     # NUMA affinity
  status:       String!     # available, claimed, allocated, unavailable
  created_at:   DateTime!
  updated_at:   DateTime!
```

### PCI Device Labels

| Label | Description |
|-------|-------------|
| `:PCIPF` | Physical Function (SR-IOV parent) |
| `:PCIVF` | Virtual Function (SR-IOV child) |

### Relationships

| Relationship | Direction | Target | Description |
|--------------|-----------|--------|-------------|
| `HAS_PCI_DEVICE` | incoming | ResourceProvider | Provider ownership |
| `PCI_PARENT_OF` | outgoing | PCIDevice | PF → VF relationship |
| `NUMA_AFFINITY` | outgoing | NUMANode | NUMA affinity |

### Example

```cypher
// Create PF with VFs
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

// Add physnet trait
MERGE (physnet:Trait {name: 'CUSTOM_PHYSNET_PROVIDER1'})
CREATE (pf)-[:HAS_TRAIT]->(physnet)
```

---

## GPU Nodes

### PhysicalGPU

Physical GPU device.

```
:PhysicalGPU (also :ResourceProvider)
  address:     String!      # PCI address
  vendor:      String       # nvidia, amd, intel
  model:       String       # A100, V100, etc.
```

### vGPUType

Virtual GPU type provider.

```
:vGPUType (also :ResourceProvider)
  vgpu_type:   String!      # nvidia-35, nvidia-36, etc.
```

### vGPU Hierarchy

```
(:ResourceProvider:PhysicalGPU)
    │
    └──[:PARENT_OF]──► (:ResourceProvider:vGPUType)
                           │
                           ├── Inventory: VGPU (total: 8)
                           │
                           └──[:HAS_TRAIT]──► (:Trait {name: 'CUSTOM_VGPU_NVIDIA_35'})
```
