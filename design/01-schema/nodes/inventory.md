---
title: Inventory Node
description: Quantitative resources available on a resource provider
keywords: [inventory, total, reserved, allocation-ratio, capacity, min-unit, max-unit]
related:
  - 01-schema/nodes/resource-provider.md
  - 01-schema/nodes/resource-class.md
  - 01-schema/relationships/hierarchy.md
implements:
  - "Resource allocation and quantitative scheduling"
section: schema/nodes
---

# Inventory Node

Quantitative resources available on a resource provider.

## Schema

```
:Inventory
  total:            Integer!   # Total amount of resource
  reserved:         Integer!   # Amount reserved for other uses (default: 0)
  min_unit:         Integer!   # Minimum allocation unit (default: 1)
  max_unit:         Integer!   # Maximum allocation unit (default: total)
  step_size:        Integer!   # Allocation granularity (default: 1)
  allocation_ratio: Float!     # Overcommit ratio (default: 1.0)
  created_at:       DateTime!
  updated_at:       DateTime!
```

## Computed Properties (at query time)

```cypher
// Capacity = (total - reserved) * allocation_ratio
WITH inv, (inv.total - inv.reserved) * inv.allocation_ratio AS capacity

// Usage = sum of all CONSUMES relationships
MATCH (inv)<-[c:CONSUMES]-()
WITH inv, sum(c.used) AS usage
```

## Constraints

- One Inventory node per (ResourceProvider, ResourceClass) pair
- `min_unit <= max_unit`
- `step_size > 0`
- `allocation_ratio > 0`
- Cannot delete Inventory with active allocations (CONSUMES relationships)

## Example

```cypher
MATCH (rp:ResourceProvider {uuid: $rp_uuid})
MATCH (rc:ResourceClass {name: 'VCPU'})
CREATE (rp)-[:HAS_INVENTORY]->(inv:Inventory {
  total: 64,
  reserved: 4,
  min_unit: 1,
  max_unit: 64,
  step_size: 1,
  allocation_ratio: 4.0,
  created_at: datetime(),
  updated_at: datetime()
})-[:OF_CLASS]->(rc)
```

## Relationships

| Relationship | Direction | Target | Description |
|--------------|-----------|--------|-------------|
| `HAS_INVENTORY` | incoming | ResourceProvider | Owner of this inventory |
| `OF_CLASS` | outgoing | ResourceClass | Type of resource |
| `CONSUMES` | incoming | Consumer | Allocations against this inventory |

## Allocation Validation

When creating allocations, validate:

```cypher
// Check allocation constraints
WHERE alloc.used >= inv.min_unit
  AND alloc.used <= inv.max_unit
  AND alloc.used % inv.step_size = 0

// Check capacity
WITH inv, (inv.total - inv.reserved) * inv.allocation_ratio AS capacity
OPTIONAL MATCH (inv)<-[c:CONSUMES]-()
WITH inv, capacity, COALESCE(sum(c.used), 0) AS usage
WHERE capacity - usage >= $requested_amount
```
