---
title: Trait Node
description: Qualitative characteristic of a resource provider
keywords: [trait, capability, hw-cpu, compute-status, custom-trait]
related:
  - 01-schema/relationships/membership.md
  - 03-constraints/trait-constraints.md
implements:
  - "Qualitative scheduling via traits"
section: schema/nodes
---

# Trait Node

Qualitative characteristic of a resource provider.

## Schema

```
:Trait
  name:       String!    # e.g., "HW_CPU_X86_AVX2", "CUSTOM_RAID"
  standard:   Boolean!   # True for os-traits, false for CUSTOM_*
  created_at: DateTime!
  updated_at: DateTime!
```

## Naming Rules

- Standard traits: synced from os-traits library
- Custom traits: must start with "CUSTOM_" prefix
- Standard traits cannot be deleted

## Trait Categories

### COMPUTE_*

Compute capabilities, architecture, features, status.

| Trait | Description |
|-------|-------------|
| `COMPUTE_STATUS_DISABLED` | Compute node is disabled |
| `COMPUTE_VOLUME_MULTI_ATTACH` | Supports multi-attach volumes |
| `COMPUTE_IMAGE_TYPE_QCOW2` | Supports qcow2 images |
| `COMPUTE_IMAGE_TYPE_RAW` | Supports raw images |

### HW_*

Hardware characteristics (CPU features, GPU APIs, NIC offloads).

| Trait | Description |
|-------|-------------|
| `HW_CPU_X86_AVX` | CPU supports AVX |
| `HW_CPU_X86_AVX2` | CPU supports AVX2 |
| `HW_CPU_X86_AVX512F` | CPU supports AVX-512 |
| `HW_NIC_SRIOV` | NIC supports SR-IOV |

### STORAGE_*

Storage characteristics.

| Trait | Description |
|-------|-------------|
| `STORAGE_DISK_SSD` | SSD storage |
| `STORAGE_DISK_HDD` | HDD storage |

### MISC_*

Miscellaneous capabilities.

| Trait | Description |
|-------|-------------|
| `MISC_SHARES_VIA_AGGREGATE` | Provider shares resources via aggregate |

### CUSTOM_*

User-defined traits for custom capabilities.

## Example

```cypher
CREATE (t:Trait {
  name: 'COMPUTE_STATUS_DISABLED',
  standard: true,
  created_at: datetime(),
  updated_at: datetime()
})
```

## Relationships

| Relationship | Direction | Target | Description |
|--------------|-----------|--------|-------------|
| `HAS_TRAIT` | incoming | ResourceProvider | Providers with this trait |
| `REQUIRES_TRAIT` | incoming | Flavor | Flavors requiring this trait |

## Trait Constraint Types

Traits can be used in four constraint modes:

| Constraint | Type | Behavior |
|------------|------|----------|
| `required` | Hard | Provider MUST have trait (filter) |
| `forbidden` | Hard | Provider MUST NOT have trait (filter) |
| `preferred` | Soft | Prefer providers WITH trait (weigher, positive score) |
| `avoided` | Soft | Prefer providers WITHOUT trait (weigher, negative score) |

See [03-constraints/trait-constraints.md](../../03-constraints/trait-constraints.md) for query patterns.

