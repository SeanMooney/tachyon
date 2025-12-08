---
title: Resource Weighers
description: RAM, CPU, Disk, IO, PCI weigher implementations
keywords: [ram-weigher, cpu-weigher, disk-weigher, io-weigher, pci-weigher]
related:
  - 04-queries/allocation-candidates.md
  - 01-schema/nodes/inventory.md
implements:
  - "RAMWeigher"
  - "CPUWeigher"
  - "DiskWeigher"
  - "IoOpsWeigher"
  - "PCIWeigher"
section: queries/weighers
---

# Resource Weighers

## RAMWeigher

Weight by available RAM.

```cypher
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)
MATCH (host)-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(:ResourceClass {name: 'MEMORY_MB'})

OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
WITH host, inv,
     (inv.total - inv.reserved) * inv.allocation_ratio AS capacity,
     COALESCE(sum(alloc.used), 0) AS used

WITH host, capacity - used AS free_ram_mb

// Normalize: (value - min) / (max - min)
WITH collect({host: host, free_ram: free_ram_mb}) AS all_hosts
WITH all_hosts,
     reduce(min_val = all_hosts[0].free_ram, h IN all_hosts |
            CASE WHEN h.free_ram < min_val THEN h.free_ram ELSE min_val END) AS min_ram,
     reduce(max_val = all_hosts[0].free_ram, h IN all_hosts |
            CASE WHEN h.free_ram > max_val THEN h.free_ram ELSE max_val END) AS max_ram

UNWIND all_hosts AS h
WITH h.host AS host, h.free_ram AS free_ram,
     CASE WHEN max_ram = min_ram THEN 0.0
          ELSE toFloat(h.free_ram - min_ram) / (max_ram - min_ram)
     END AS normalized_weight

// Apply multiplier (positive = spread, negative = stack)
RETURN host, free_ram, normalized_weight * $ram_weight_multiplier AS ram_weight
ORDER BY ram_weight DESC
```

## CPUWeigher

Weight by available vCPUs.

```cypher
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)
MATCH (host)-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(:ResourceClass {name: 'VCPU'})

OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
WITH host, inv,
     (inv.total - inv.reserved) * inv.allocation_ratio AS capacity,
     COALESCE(sum(alloc.used), 0) AS used

WITH host, capacity - used AS free_vcpus

// Collect for normalization
WITH collect({host: host, free_vcpus: free_vcpus}) AS all_hosts

UNWIND all_hosts AS h
RETURN h.host AS host, h.free_vcpus AS free_vcpus,
       toFloat(h.free_vcpus) * $cpu_weight_multiplier AS cpu_weight
ORDER BY cpu_weight DESC
```

## DiskWeigher

Weight by available disk.

```cypher
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// Include shared storage
OPTIONAL MATCH (sharing)-[:SHARES_RESOURCES {resource_classes: ['DISK_GB']}]->(host)
MATCH (COALESCE(sharing, host))-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(:ResourceClass {name: 'DISK_GB'})

OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
WITH host, inv,
     (inv.total - inv.reserved) * inv.allocation_ratio AS capacity,
     COALESCE(sum(alloc.used), 0) AS used

WITH host, capacity - used AS free_disk_gb

RETURN host, free_disk_gb,
       free_disk_gb * $disk_weight_multiplier AS disk_weight
ORDER BY disk_weight DESC
```

## IoOpsWeigher

Weight by current I/O operations.

```cypher
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// Count instances in I/O heavy states
OPTIONAL MATCH (consumer:Consumer)-[:SCHEDULED_ON]->(host)
WHERE consumer.task_state IN ['spawning', 'resize_migrating', 'rebuilding',
                               'resize_prep', 'image_snapshot', 'image_backup',
                               'rescuing', 'unshelving']

WITH host, count(consumer) AS io_ops

// Lower is better (default negative multiplier)
RETURN host, io_ops, -1 * io_ops * $io_ops_weight_multiplier AS io_weight
ORDER BY io_weight DESC
```

## PCIWeigher

Weight by PCI device availability.

```cypher
// Prefer hosts that match PCI demand level
// $requested_pci_count: number of PCI devices requested

MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// Count available PCI devices
OPTIONAL MATCH (host)-[:PARENT_OF*]->(pci:PCIVF)
               -[:HAS_INVENTORY]->(inv)
               -[:OF_CLASS]->(:ResourceClass {name: 'SRIOV_NET_VF'})
OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
WITH host,
     COALESCE(sum(inv.total - inv.reserved - COALESCE(alloc.used, 0)), 0) AS available_pci

// Weight calculation
WITH host, available_pci,
     CASE
       WHEN $requested_pci_count = 0 AND available_pci = 0 THEN 1.0  // No PCI needed, no PCI available
       WHEN $requested_pci_count = 0 THEN 0.0  // Penalize wasting PCI-capable hosts
       WHEN available_pci >= $requested_pci_count THEN toFloat(available_pci) / 100
       ELSE -1.0  // Can't satisfy request
     END AS pci_weight

WHERE pci_weight >= 0 OR $requested_pci_count = 0
RETURN host, available_pci, pci_weight * $pci_weight_multiplier AS weighted_pci
ORDER BY weighted_pci DESC
```

## NumInstancesWeigher

Weight by number of instances.

```cypher
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

OPTIONAL MATCH (c:Consumer)-[:SCHEDULED_ON]->(host)
WITH host, count(c) AS instance_count

// Positive multiplier = prefer hosts with more instances (stack)
// Negative multiplier = prefer hosts with fewer instances (spread)
RETURN host, instance_count,
       instance_count * $num_instances_weight_multiplier AS instances_weight
ORDER BY instances_weight DESC
```

## Combined Resource Weigher

```cypher
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// RAM
MATCH (host)-[:HAS_INVENTORY]->(mem_inv)-[:OF_CLASS]->(:ResourceClass {name: 'MEMORY_MB'})
OPTIONAL MATCH (mem_inv)<-[m_alloc:CONSUMES]-()
WITH host, (mem_inv.total - mem_inv.reserved) * mem_inv.allocation_ratio - COALESCE(sum(m_alloc.used), 0) AS free_ram

// CPU
MATCH (host)-[:HAS_INVENTORY]->(cpu_inv)-[:OF_CLASS]->(:ResourceClass {name: 'VCPU'})
OPTIONAL MATCH (cpu_inv)<-[c_alloc:CONSUMES]-()
WITH host, free_ram,
     (cpu_inv.total - cpu_inv.reserved) * cpu_inv.allocation_ratio - COALESCE(sum(c_alloc.used), 0) AS free_vcpus

// I/O ops
OPTIONAL MATCH (consumer:Consumer)-[:SCHEDULED_ON]->(host)
WHERE consumer.task_state IN ['spawning', 'resize_migrating', 'rebuilding']
WITH host, free_ram, free_vcpus, count(consumer) AS io_ops

// Calculate total weight
WITH host, free_ram, free_vcpus, io_ops,
     (free_ram / 1024.0) * $ram_weight_multiplier +
     free_vcpus * $cpu_weight_multiplier -
     io_ops * $io_ops_weight_multiplier AS total_weight

RETURN host, free_ram, free_vcpus, io_ops, total_weight
ORDER BY total_weight DESC
LIMIT $host_subset_size
```
