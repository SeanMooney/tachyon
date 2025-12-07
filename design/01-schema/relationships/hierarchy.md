---
title: Hierarchy Relationships
description: PARENT_OF, HAS_INVENTORY, OF_CLASS relationships
keywords: [parent-of, has-inventory, of-class, tree, hierarchy]
related:
  - 01-schema/nodes/resource-provider.md
  - 01-schema/nodes/inventory.md
  - 02-patterns/provider-trees.md
implements:
  - "Resource provider trees"
  - "Inventory management"
section: schema/relationships
---

# Hierarchy Relationships

## PARENT_OF

Models resource provider tree hierarchy.

```
(:ResourceProvider)-[:PARENT_OF]->(:ResourceProvider)
```

### Properties

None.

### Semantics

- Direction: Parent → Child
- A provider with no incoming PARENT_OF is a root provider
- A provider can have at most one parent
- A provider can have multiple children
- No cycles allowed

### Example

```cypher
// Create parent-child relationship
MATCH (parent:ResourceProvider {uuid: $parent_uuid})
MATCH (child:ResourceProvider {uuid: $child_uuid})
CREATE (parent)-[:PARENT_OF]->(child)
```

### Traversal Queries

```cypher
// Find root provider for any node
MATCH (rp:ResourceProvider {uuid: $uuid})
MATCH path = (root:ResourceProvider)-[:PARENT_OF*0..]->(rp)
WHERE NOT ()-[:PARENT_OF]->(root)
RETURN root

// Find all descendants
MATCH (root:ResourceProvider {uuid: $uuid})
MATCH (root)-[:PARENT_OF*]->(descendant)
RETURN descendant

// Find depth of provider in tree
MATCH (rp:ResourceProvider {uuid: $uuid})
MATCH path = (root)-[:PARENT_OF*0..]->(rp)
WHERE NOT ()-[:PARENT_OF]->(root)
RETURN length(path) AS depth
```

---

## HAS_INVENTORY

Links resource provider to its inventory.

```
(:ResourceProvider)-[:HAS_INVENTORY]->(:Inventory)
```

### Properties

None.

### Constraints

- Each ResourceProvider can have multiple inventories (one per ResourceClass)
- Inventory must also have OF_CLASS relationship to ResourceClass

### Example

```cypher
MATCH (rp:ResourceProvider {uuid: $rp_uuid})
CREATE (rp)-[:HAS_INVENTORY]->(inv:Inventory {
  total: 64,
  reserved: 4,
  min_unit: 1,
  max_unit: 64,
  step_size: 1,
  allocation_ratio: 4.0,
  created_at: datetime(),
  updated_at: datetime()
})
```

---

## OF_CLASS

Links inventory to its resource class.

```
(:Inventory)-[:OF_CLASS]->(:ResourceClass)
```

### Properties

None.

### Constraints

- Each Inventory has exactly one OF_CLASS relationship
- Combined with HAS_INVENTORY, forms unique (Provider, Class) pairs

### Example

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

### Query Pattern

```cypher
// Find inventory for specific resource class
MATCH (rp:ResourceProvider {uuid: $rp_uuid})
      -[:HAS_INVENTORY]->(inv)
      -[:OF_CLASS]->(:ResourceClass {name: $rc_name})
RETURN inv
```

---

## Cardinality Summary

| Relationship | From | To | Cardinality |
|--------------|------|-----|-------------|
| PARENT_OF | ResourceProvider | ResourceProvider | 0..1 : 0..N |
| HAS_INVENTORY | ResourceProvider | Inventory | 1 : 0..N |
| OF_CLASS | Inventory | ResourceClass | N : 1 |

