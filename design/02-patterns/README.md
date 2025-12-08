---
title: Pattern Catalog
description: Implementation patterns for complex graph structures
keywords: [patterns, hierarchy, numa, pci, vgpu, sharing]
related:
  - 01-schema/nodes/resource-provider.md
  - 01-schema/relationships/hierarchy.md
implements: []
section: patterns
---

# Pattern Catalog

This section documents graph patterns for modeling complex hierarchical relationships in Tachyon.

## Overview

| Pattern | Description | Key Relationships |
|---------|-------------|-------------------|
| [Provider Trees](provider-trees.md) | Nested resource provider hierarchies | `PARENT_OF` |
| [NUMA Topology](numa-topology.md) | NUMA node modeling | `PARENT_OF`, `:NUMANode` |
| [PCI Hierarchy](pci-hierarchy.md) | PCI device and SR-IOV | `PARENT_OF`, `PCI_PARENT_OF` |
| [vGPU](vgpu.md) | Virtual GPU modeling | `PARENT_OF`, `:vGPUType` |
| [Sharing Providers](sharing-providers.md) | Shared storage pattern | `SHARES_RESOURCES` |
| [Soft Constraints](soft-constraints.md) | Preferred/avoided traits | `REQUIRES_TRAIT` |

## Common Pattern Structure

All patterns follow this structure:

1. **Graph Diagram**: Visual representation of the pattern
2. **Creation Pattern**: Cypher to create the structure
3. **Query Patterns**: Common queries against the structure
4. **Constraints**: Validation rules

## Pattern Dependencies

```
provider-trees.md
    │
    ├── numa-topology.md
    │       │
    │       └── pci-hierarchy.md
    │               │
    │               └── vgpu.md
    │
    └── sharing-providers.md

soft-constraints.md (independent)
```
