---
title: Consumption Relationships
description: CONSUMES, OWNED_BY, CREATED_BY, OF_TYPE relationships
keywords: [consumes, allocation, owned-by, created-by, consumer-type]
related:
  - 01-schema/nodes/consumer.md
  - 01-schema/nodes/inventory.md
  - 05-operations/resource-claiming.md
implements:
  - "Resource allocation tracking"
  - "Consumer ownership"
section: schema/relationships
---

# Consumption Relationships

## CONSUMES

Records resource consumption by a consumer. This is the core allocation mechanism.

```
(:Consumer)-[:CONSUMES {used, created_at, updated_at}]->(:Inventory)
```

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `used` | Integer! | Amount of resource consumed |
| `created_at` | DateTime! | When allocation was created |
| `updated_at` | DateTime! | When allocation was last modified |

### Constraints

- `used >= inventory.min_unit`
- `used <= inventory.max_unit`
- `used % inventory.step_size == 0`
- Sum of all CONSUMES.used on an Inventory must not exceed capacity

### Example

```cypher
// Create allocation
MATCH (c:Consumer {uuid: $consumer_uuid})
MATCH (rp:ResourceProvider {uuid: $rp_uuid})
      -[:HAS_INVENTORY]->(inv)
      -[:OF_CLASS]->(:ResourceClass {name: 'VCPU'})
CREATE (c)-[:CONSUMES {
  used: 4,
  created_at: datetime(),
  updated_at: datetime()
}]->(inv)
```

### Capacity Check

```cypher
// Verify capacity before allocation
MATCH (inv:Inventory)
WITH inv, (inv.total - inv.reserved) * inv.allocation_ratio AS capacity
OPTIONAL MATCH (inv)<-[existing:CONSUMES]-()
WITH inv, capacity, COALESCE(sum(existing.used), 0) AS current_usage
WHERE capacity - current_usage >= $requested_amount
RETURN inv
```

---

## OWNED_BY

Links consumer to its owning project.

```
(:Consumer)-[:OWNED_BY]->(:Project)
```

### Properties

None.

### Semantics

- Each consumer has exactly one owning project
- Used for quota tracking and tenant isolation queries

---

## CREATED_BY

Links consumer to the user who created it.

```
(:Consumer)-[:CREATED_BY]->(:User)
```

### Properties

None.

---

## OF_TYPE

Links consumer to its type.

```
(:Consumer)-[:OF_TYPE]->(:ConsumerType)
```

### Properties

None.

### Example Consumer Types

- `INSTANCE` - VM instance
- `MIGRATION` - Migration operation
- `VOLUME` - Cinder volume

---

## Complete Consumer Pattern

```cypher
// Create consumer with full relationships
MERGE (c:Consumer {uuid: $consumer_uuid})
ON CREATE SET
  c.generation = 0,
  c.created_at = datetime(),
  c.updated_at = datetime()

// Link ownership
MERGE (proj:Project {external_id: $project_id})
MERGE (user:User {external_id: $user_id})
MERGE (c)-[:OWNED_BY]->(proj)
MERGE (c)-[:CREATED_BY]->(user)

// Optional: consumer type
OPTIONAL MATCH (ct:ConsumerType {name: $consumer_type})
FOREACH (_ IN CASE WHEN ct IS NOT NULL THEN [1] ELSE [] END |
  MERGE (c)-[:OF_TYPE]->(ct)
)

// Create allocations
WITH c
UNWIND $allocations AS alloc
MATCH (rp:ResourceProvider {uuid: alloc.rp_uuid})
      -[:HAS_INVENTORY]->(inv)
      -[:OF_CLASS]->(:ResourceClass {name: alloc.resource_class})
CREATE (c)-[:CONSUMES {
  used: alloc.used,
  created_at: datetime(),
  updated_at: datetime()
}]->(inv)

// Increment consumer generation
SET c.generation = c.generation + 1,
    c.updated_at = datetime()

RETURN c
```

---

## Cardinality Summary

| Relationship | From | To | Cardinality |
|--------------|------|-----|-------------|
| CONSUMES | Consumer | Inventory | 0..N : 0..N |
| OWNED_BY | Consumer | Project | N : 1 |
| CREATED_BY | Consumer | User | N : 1 |
| OF_TYPE | Consumer | ConsumerType | N : 0..1 |

