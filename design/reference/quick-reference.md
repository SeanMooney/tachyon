---
title: Quick Reference
description: Cheat sheet for node labels, relationships, and patterns
keywords: [quick-reference, cheat-sheet, labels, relationships]
related:
  - 00-overview/glossary.md
  - 01-schema/README.md
implements: []
section: reference
---

# Quick Reference

## Node Labels

```
:ResourceProvider, :Inventory, :Consumer, :ResourceClass, :Trait,
:Aggregate, :Project, :User, :ConsumerType, :Flavor, :Image,
:ServerGroup, :AvailabilityZone, :Cell, :NUMANode, :PCIDevice,
:PCIPF, :PCIVF, :PhysicalGPU, :vGPUType, :ComputeHost,
:MetricEndpoint, :ThresholdAlert, :Webhook
```

## Relationship Types

```
:PARENT_OF, :HAS_INVENTORY, :OF_CLASS, :HAS_TRAIT, :MEMBER_OF,
:CONSUMES, :OWNED_BY, :CREATED_BY, :OF_TYPE, :DEFINES_AZ,
:LOCATED_IN, :HAS_MEMBER, :SCHEDULED_ON, :REQUIRES_TRAIT,
:REQUIRES_RESOURCE, :SHARES_RESOURCES, :NUMA_AFFINITY,
:TENANT_ALLOWED, :IMAGE_ALLOWED, :HAS_PCI_DEVICE, :PCI_PARENT_OF,
:HAS_NUMA_NODE, :HAS_METRIC_SOURCE, :HAS_ALERT
```

## Key Property Patterns

```cypher
// Optimistic concurrency
WHERE node.generation = $expected_generation
SET node.generation = node.generation + 1

// Capacity calculation
(inv.total - inv.reserved) * inv.allocation_ratio AS capacity

// Usage calculation
OPTIONAL MATCH (inv)<-[c:CONSUMES]-()
WITH inv, COALESCE(sum(c.used), 0) AS usage

// Availability
capacity - usage AS available
```

## Trait Constraint Types

| Constraint | Type | Extra Spec | Behavior |
|------------|------|------------|----------|
| `required` | Hard | `trait:X=required` | MUST have |
| `forbidden` | Hard | `trait:X=forbidden` | MUST NOT have |
| `preferred` | Soft | `trait:X=preferred` | Weigher + |
| `avoided` | Soft | `trait:X=avoided` | Weigher - |

## Common Query Patterns

```cypher
// Find root provider
MATCH path = (root:ResourceProvider)-[:PARENT_OF*0..]->(rp)
WHERE NOT ()-[:PARENT_OF]->(root)
RETURN root

// Check required traits
WHERE ALL(t IN $required WHERE (rp)-[:HAS_TRAIT]->(:Trait {name: t}))

// Check forbidden traits
AND NONE(t IN $forbidden WHERE (rp)-[:HAS_TRAIT]->(:Trait {name: t}))

// Soft trait scoring
reduce(s = 0.0, p IN preferred | 
  s + CASE WHEN (rp)-[:HAS_TRAIT]->(:Trait {name: p.name}) THEN p.weight ELSE 0 END)
```

## Standard Resource Classes

| Category | Classes |
|----------|---------|
| Compute | `VCPU`, `PCPU`, `MEMORY_MB` |
| Storage | `DISK_GB` |
| Network | `SRIOV_NET_VF`, `NET_BW_*`, `IPV4_ADDRESS` |
| GPU | `VGPU`, `PGPU` |

## Standard Trait Prefixes

| Prefix | Description |
|--------|-------------|
| `COMPUTE_*` | Compute capabilities |
| `HW_*` | Hardware characteristics |
| `STORAGE_*` | Storage characteristics |
| `MISC_*` | Miscellaneous |
| `CUSTOM_*` | User-defined |

## Server Group Policies

| Policy | Type | Behavior |
|--------|------|----------|
| `affinity` | Hard | Same host |
| `anti-affinity` | Hard | Different hosts |
| `soft-affinity` | Soft | Prefer same |
| `soft-anti-affinity` | Soft | Prefer spread |

## Cardinality Summary

| Relationship | Cardinality |
|--------------|-------------|
| PARENT_OF | 0..1 : 0..N |
| HAS_INVENTORY | 1 : 0..N |
| CONSUMES | 0..N : 0..N |
| HAS_TRAIT | 0..N : 0..N |
| MEMBER_OF | 0..N : 0..N |

