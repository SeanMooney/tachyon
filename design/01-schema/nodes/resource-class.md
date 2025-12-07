---
title: ResourceClass Node
description: Type of quantitative resource (VCPU, MEMORY_MB, CUSTOM_*)
keywords: [resource-class, vcpu, memory, disk, custom-resource]
related:
  - 01-schema/nodes/inventory.md
  - 01-schema/relationships/hierarchy.md
implements:
  - "Standard and custom resource classes"
section: schema/nodes
---

# ResourceClass Node

Type of quantitative resource.

## Schema

```
:ResourceClass
  name:       String!    # e.g., "VCPU", "MEMORY_MB", "CUSTOM_FPGA"
  id:         Integer    # Placement compatibility (0-9999 standard, 10000+ custom)
  standard:   Boolean!   # True for os-resource-classes, false for CUSTOM_*
  created_at: DateTime!
  updated_at: DateTime!
```

## Naming Rules

- Standard classes: synced from os-resource-classes library
- Custom classes: must start with "CUSTOM_" prefix
- Standard classes cannot be modified or deleted

## Standard Resource Classes

### Compute

| Name | Description |
|------|-------------|
| `VCPU` | Virtual CPU |
| `PCPU` | Physical (dedicated) CPU |
| `MEMORY_MB` | Memory in megabytes |
| `MEM_ENCRYPTION_CONTEXT` | Memory encryption context |

### Storage

| Name | Description |
|------|-------------|
| `DISK_GB` | Disk space in gigabytes |

### Network

| Name | Description |
|------|-------------|
| `SRIOV_NET_VF` | SR-IOV Virtual Function |
| `NET_BW_EGR_KILOBIT_PER_SEC` | Egress bandwidth |
| `NET_BW_IGR_KILOBIT_PER_SEC` | Ingress bandwidth |
| `NET_PACKET_RATE_KILOPACKET_PER_SEC` | Packet rate |
| `IPV4_ADDRESS` | IPv4 address |

### GPU

| Name | Description |
|------|-------------|
| `VGPU` | Virtual GPU |
| `VGPU_DISPLAY_HEAD` | vGPU display head |
| `PGPU` | Physical GPU |

### NUMA

| Name | Description |
|------|-------------|
| `NUMA_SOCKET` | NUMA socket |
| `NUMA_CORE` | NUMA core |
| `NUMA_THREAD` | NUMA thread |
| `NUMA_MEMORY_MB` | NUMA-local memory |

### Accelerator

| Name | Description |
|------|-------------|
| `FPGA` | FPGA device |
| `PCI_DEVICE` | Generic PCI device |

## Example

```cypher
CREATE (rc:ResourceClass {
  name: 'CUSTOM_GPU_NVIDIA_A100',
  standard: false,
  created_at: datetime(),
  updated_at: datetime()
})
```

## Relationships

| Relationship | Direction | Target | Description |
|--------------|-----------|--------|-------------|
| `OF_CLASS` | incoming | Inventory | Inventories of this class |
| `REQUIRES_RESOURCE` | incoming | Flavor | Flavors requiring this class |

