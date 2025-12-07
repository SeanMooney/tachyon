---
title: Topology Filters
description: NUMATopologyFilter, PciPassthroughFilter implementations
keywords: [numa-filter, pci-filter, topology-filter, passthrough]
related:
  - 03-constraints/topology-constraints.md
  - 02-patterns/numa-topology.md
  - 02-patterns/pci-hierarchy.md
implements:
  - "NUMATopologyFilter"
  - "PciPassthroughFilter"
section: queries/filters
---

# Topology Filters

## NUMATopologyFilter

Validate NUMA topology requirements.

```cypher
// Parameters:
// $numa_nodes: 2  // Required number of NUMA nodes
// $min_vcpus_per_node: 4  // Minimum vCPUs per NUMA node
// $min_mem_per_node: 4096  // Minimum memory per NUMA node (MB)

MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// Find NUMA nodes with sufficient resources
MATCH (host)-[:PARENT_OF]->(numa:NUMANode)
MATCH (numa)-[:HAS_INVENTORY]->(vcpu_inv)-[:OF_CLASS]->(:ResourceClass {name: 'VCPU'})
MATCH (numa)-[:HAS_INVENTORY]->(mem_inv)-[:OF_CLASS]->(:ResourceClass {name: 'MEMORY_MB'})

OPTIONAL MATCH (vcpu_inv)<-[vc:CONSUMES]-()
OPTIONAL MATCH (mem_inv)<-[mc:CONSUMES]-()

WITH host, numa,
     (vcpu_inv.total - vcpu_inv.reserved) * vcpu_inv.allocation_ratio - COALESCE(sum(vc.used), 0) AS avail_vcpus,
     (mem_inv.total - mem_inv.reserved) * mem_inv.allocation_ratio - COALESCE(sum(mc.used), 0) AS avail_mem

// Collect NUMA nodes that meet minimum requirements
WITH host, collect({
  numa: numa,
  avail_vcpus: avail_vcpus,
  avail_mem: avail_mem
}) AS numa_nodes

// Check if we have enough suitable NUMA nodes
WHERE size([n IN numa_nodes WHERE n.avail_vcpus >= $min_vcpus_per_node 
                               AND n.avail_mem >= $min_mem_per_node]) >= $numa_nodes

RETURN host, numa_nodes
```

## PciPassthroughFilter

Match PCI device requirements.

```cypher
// Parameters:
// $pci_requests: [
//   {alias: 'gpu', count: 1, traits: ['CUSTOM_NVIDIA_A100']},
//   {alias: 'nic', count: 2, traits: ['CUSTOM_PHYSNET_DATA']}
// ]

MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// For each PCI request, find matching devices
UNWIND $pci_requests AS req
MATCH (host)-[:PARENT_OF*]->(pci_provider)
      -[:HAS_INVENTORY]->(inv)
WHERE ALL(trait IN req.traits WHERE (pci_provider)-[:HAS_TRAIT]->(:Trait {name: trait}))

// Check available count
OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
WITH host, req, pci_provider, inv,
     (inv.total - inv.reserved) - COALESCE(sum(alloc.used), 0) AS available

WHERE available >= 1
WITH host, req, collect(pci_provider) AS matching_providers
WHERE size(matching_providers) >= req.count

WITH host, collect({request: req, providers: matching_providers}) AS pci_matches
WHERE size(pci_matches) = size($pci_requests)

RETURN host, pci_matches
```

## Combined NUMA + PCI Filter

For PCI-NUMA affinity (required policy):

```cypher
MATCH (host:ResourceProvider)-[:PARENT_OF]->(numa:NUMANode)

// NUMA must have CPU and memory
MATCH (numa)-[:HAS_INVENTORY]->(vcpu_inv)-[:OF_CLASS]->(:ResourceClass {name: 'VCPU'})
MATCH (numa)-[:HAS_INVENTORY]->(mem_inv)-[:OF_CLASS]->(:ResourceClass {name: 'MEMORY_MB'})

// PCI must be under same NUMA
MATCH (numa)-[:PARENT_OF*]->(pci_provider)
      -[:HAS_INVENTORY]->(pci_inv)
      -[:OF_CLASS]->(:ResourceClass {name: 'SRIOV_NET_VF'})
WHERE ALL(t IN $pci_traits WHERE (pci_provider)-[:HAS_TRAIT]->(:Trait {name: t}))

// Check all availabilities
OPTIONAL MATCH (vcpu_inv)<-[vc:CONSUMES]-()
OPTIONAL MATCH (mem_inv)<-[mc:CONSUMES]-()
OPTIONAL MATCH (pci_inv)<-[pc:CONSUMES]-()

WITH host, numa, pci_provider,
     vcpu_inv.total - COALESCE(sum(vc.used), 0) AS vcpu_avail,
     mem_inv.total - COALESCE(sum(mc.used), 0) AS mem_avail,
     pci_inv.total - COALESCE(sum(pc.used), 0) AS pci_avail

WHERE vcpu_avail >= $vcpus AND mem_avail >= $memory_mb AND pci_avail >= 1

RETURN host, numa, pci_provider
```

## Hugepages Filter

```cypher
// Find hosts with sufficient hugepages
MATCH (host:ResourceProvider)-[:PARENT_OF]->(numa:NUMANode)
WHERE numa.hugepages[$hugepage_size_kb] >= $required_pages
RETURN DISTINCT host
```

## CPU Pinning Filter

```cypher
// Find NUMA nodes with available dedicated CPUs
MATCH (host:ResourceProvider)-[:PARENT_OF]->(numa:NUMANode)
MATCH (numa)-[:HAS_INVENTORY]->(pcpu_inv)-[:OF_CLASS]->(:ResourceClass {name: 'PCPU'})

OPTIONAL MATCH (pcpu_inv)<-[alloc:CONSUMES]-()
WITH host, numa, pcpu_inv,
     pcpu_inv.total - COALESCE(sum(alloc.used), 0) AS avail_pcpus

WHERE avail_pcpus >= $required_pcpus

RETURN host, numa, avail_pcpus
```

