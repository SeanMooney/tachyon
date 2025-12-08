---
title: Scheduling Relationships
description: REQUIRES_TRAIT, SHARES_RESOURCES, TENANT_ALLOWED, and more
keywords: [requires-trait, shares-resources, tenant-allowed, image-allowed, scheduled-on]
related:
  - 01-schema/nodes/nova-entities.md
  - 02-patterns/sharing-providers.md
  - 03-constraints/aggregate-constraints.md
implements:
  - "Flavor trait requirements"
  - "Resource sharing"
  - "Tenant and image isolation"
section: schema/relationships
---

# Scheduling Relationships

## REQUIRES_TRAIT

Links flavor to trait requirements with hard or soft constraints.

```
(:Flavor)-[:REQUIRES_TRAIT {constraint, weight}]->(:Trait)
```

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `constraint` | String! | Constraint type (required, forbidden, preferred, avoided) |
| `weight` | Float | Weight for soft constraints (default: 1.0) |

### Constraint Types

| Constraint | Type | Behavior |
|------------|------|----------|
| `required` | Hard | Provider MUST have trait (filter) |
| `forbidden` | Hard | Provider MUST NOT have trait (filter) |
| `preferred` | Soft | Prefer providers WITH trait (weigher, positive score) |
| `avoided` | Soft | Prefer providers WITHOUT trait (weigher, negative score) |

### Example

```cypher
// Required trait (hard constraint)
CREATE (f)-[:REQUIRES_TRAIT {constraint: 'required'}]->(t:Trait {name: 'HW_CPU_X86_AVX2'})

// Forbidden trait (hard constraint)
CREATE (f)-[:REQUIRES_TRAIT {constraint: 'forbidden'}]->(t:Trait {name: 'COMPUTE_STATUS_DISABLED'})

// Preferred trait (soft constraint - favor hosts with SSD)
CREATE (f)-[:REQUIRES_TRAIT {constraint: 'preferred', weight: 2.0}]->(t:Trait {name: 'STORAGE_DISK_SSD'})

// Avoided trait (soft constraint - avoid hosts in maintenance window)
CREATE (f)-[:REQUIRES_TRAIT {constraint: 'avoided', weight: 1.5}]->(t:Trait {name: 'CUSTOM_MAINTENANCE_WINDOW'})
```

---

## REQUIRES_RESOURCE

Links flavor to resource requirements.

```
(:Flavor)-[:REQUIRES_RESOURCE {amount, group}]->(:ResourceClass)
```

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `amount` | Integer! | Required amount |
| `group` | String | Optional resource group name |

---

## HAS_MEMBER

Links server group to its member consumers.

```
(:ServerGroup)-[:HAS_MEMBER]->(:Consumer)
```

### Properties

None.

### Semantics

- Enforces affinity/anti-affinity policies
- Consumer can be member of one server group

---

## SCHEDULED_ON

Links consumer to its hosting resource provider.

```
(:Consumer)-[:SCHEDULED_ON {host, node, scheduled_at}]->(:ResourceProvider)
```

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `host` | String | Compute host name |
| `node` | String | Hypervisor node name |
| `scheduled_at` | DateTime | When scheduled |

### Semantics

- Represents where instance is running
- Used for affinity/anti-affinity evaluation

---

## SHARES_RESOURCES

Direct relationship for sharing providers (replaces MISC_SHARES_VIA_AGGREGATE pattern).

```
(:ResourceProvider)-[:SHARES_RESOURCES {resource_classes}]->(:ResourceProvider)
```

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `resource_classes` | List<String> | Which resource classes are shared |

### Semantics

- Source provider shares its resources with target providers
- More efficient than aggregate-based sharing queries
- Created when provider has MISC_SHARES_VIA_AGGREGATE trait

### Example

```cypher
// Storage provider shares DISK_GB with compute nodes
MATCH (storage:ResourceProvider {name: 'shared-storage-pool'})
MATCH (compute:ResourceProvider)
WHERE compute.name STARTS WITH 'compute-'
  AND (storage)-[:MEMBER_OF]->(:Aggregate)<-[:MEMBER_OF]-(compute)
CREATE (storage)-[:SHARES_RESOURCES {resource_classes: ['DISK_GB']}]->(compute)
```

---

## TENANT_ALLOWED

Links aggregate to allowed tenant(s).

```
(:Aggregate)-[:TENANT_ALLOWED]->(:Project)
```

### Properties

None.

### Semantics

- Replaces `filter_tenant_id` aggregate metadata
- Hosts in aggregate only schedulable by allowed tenants
- Graph-native alternative enables efficient tenant isolation queries

---

## IMAGE_ALLOWED

Links aggregate to allowed images.

```
(:Aggregate)-[:IMAGE_ALLOWED]->(:Image)
```

### Properties

None.

### Semantics

- Replaces image property matching in aggregate metadata
- Hosts in aggregate only schedulable for allowed images

---

## NUMA_AFFINITY

Links PCI device to NUMA node for affinity.

```
(:PCIDevice)-[:NUMA_AFFINITY]->(:NUMANode)
```

### Properties

None.

### Semantics

- PCI device is physically attached to specific NUMA node
- Used for PCI-NUMA affinity policy enforcement

---

## PCI_PARENT_OF

Links PCI physical function to virtual functions.

```
(:PCIDevice)-[:PCI_PARENT_OF]->(:PCIDevice)
```

### Properties

None.

### Semantics

- Source is Physical Function (PF)
- Target is Virtual Function (VF)
- Used for SR-IOV modeling

---

## Cardinality Summary

| Relationship | From | To | Cardinality |
|--------------|------|-----|-------------|
| REQUIRES_TRAIT | Flavor | Trait | 0..N : 0..N |
| REQUIRES_RESOURCE | Flavor | ResourceClass | 0..N : 0..N |
| HAS_MEMBER | ServerGroup | Consumer | 1 : 0..N |
| SCHEDULED_ON | Consumer | ResourceProvider | 0..1 : 0..N |
| SHARES_RESOURCES | ResourceProvider | ResourceProvider | 0..N : 0..N |
| TENANT_ALLOWED | Aggregate | Project | 0..N : 0..N |
| IMAGE_ALLOWED | Aggregate | Image | 0..N : 0..N |
| NUMA_AFFINITY | PCIDevice | NUMANode | N : 1 |
| PCI_PARENT_OF | PCIDevice | PCIDevice | 1 : 0..N |
