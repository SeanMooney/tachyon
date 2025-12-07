---
title: Placement API Mapping
description: Bidirectional mapping between Placement API and Tachyon
keywords: [placement-api, migration, compatibility, endpoint-mapping]
related:
  - 01-schema/nodes/resource-provider.md
  - 01-schema/nodes/inventory.md
  - reference/placement-model.md
implements:
  - "Placement API compatibility"
section: migration
---

# Placement API Mapping

## Resource Providers

| Placement API | HTTP | Tachyon Neo4j Operation |
|---------------|------|-------------------------|
| `GET /resource_providers` | GET | `MATCH (rp:ResourceProvider) ...` |
| `POST /resource_providers` | POST | `CREATE (rp:ResourceProvider {...})` |
| `GET /resource_providers/{uuid}` | GET | `MATCH (rp:ResourceProvider {uuid: $uuid})` |
| `PUT /resource_providers/{uuid}` | PUT | `MATCH (rp:ResourceProvider {uuid: $uuid}) SET ...` |
| `DELETE /resource_providers/{uuid}` | DELETE | `MATCH (rp:ResourceProvider {uuid: $uuid}) DETACH DELETE rp` |

### GET /resource_providers - List with filters

```cypher
MATCH (rp:ResourceProvider)

// Name filter (contains)
WHERE ($name IS NULL OR rp.name CONTAINS $name)

// in_tree filter
AND ($in_tree IS NULL OR EXISTS {
  MATCH (root:ResourceProvider {uuid: $in_tree})-[:PARENT_OF*0..]->(rp)
})

// resources filter
AND ($resources IS NULL OR ALL(req IN $resources WHERE
  EXISTS {
    MATCH (rp)-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(:ResourceClass {name: req.rc})
    OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
    WITH inv, (inv.total - inv.reserved) * inv.allocation_ratio AS capacity,
         COALESCE(sum(alloc.used), 0) AS used
    WHERE capacity - used >= req.amount
  }
))

// required traits filter
AND ($required IS NULL OR ALL(t IN $required WHERE
  (rp)-[:HAS_TRAIT]->(:Trait {name: t})
))

// member_of filter
AND ($member_of IS NULL OR EXISTS {
  MATCH (rp)-[:MEMBER_OF]->(agg:Aggregate)
  WHERE agg.uuid IN $member_of
})

RETURN rp
```

### POST /resource_providers - Create

```cypher
// Validate parent exists if specified
OPTIONAL MATCH (parent:ResourceProvider {uuid: $parent_provider_uuid})
WITH parent
WHERE $parent_provider_uuid IS NULL OR parent IS NOT NULL

CREATE (rp:ResourceProvider {
  uuid: COALESCE($uuid, randomUUID()),
  name: $name,
  generation: 0,
  created_at: datetime(),
  updated_at: datetime()
})

// Create parent relationship if specified
WITH rp, parent
FOREACH (_ IN CASE WHEN parent IS NOT NULL THEN [1] ELSE [] END |
  CREATE (parent)-[:PARENT_OF]->(rp)
)

RETURN rp
```

## Inventories

| Placement API | HTTP | Tachyon Neo4j Operation |
|---------------|------|-------------------------|
| `GET /resource_providers/{uuid}/inventories` | GET | `MATCH (rp)-[:HAS_INVENTORY]->(inv)` |
| `PUT /resource_providers/{uuid}/inventories` | PUT | Replace all inventories |
| `GET /resource_providers/{uuid}/inventories/{rc}` | GET | Single inventory by class |
| `PUT /resource_providers/{uuid}/inventories/{rc}` | PUT | Create/update single inventory |
| `DELETE /resource_providers/{uuid}/inventories/{rc}` | DELETE | Delete single inventory |

### PUT /resource_providers/{uuid}/inventories

```cypher
MATCH (rp:ResourceProvider {uuid: $uuid})
WHERE rp.generation = $resource_provider_generation

// Delete existing inventories without allocations
OPTIONAL MATCH (rp)-[:HAS_INVENTORY]->(old_inv)
WHERE NOT (old_inv)<-[:CONSUMES]-()
DETACH DELETE old_inv

// Create new inventories
WITH rp
UNWIND keys($inventories) AS rc_name
MATCH (rc:ResourceClass {name: rc_name})

MERGE (rp)-[:HAS_INVENTORY]->(inv:Inventory)-[:OF_CLASS]->(rc)
SET inv.total = $inventories[rc_name].total,
    inv.reserved = COALESCE($inventories[rc_name].reserved, 0),
    inv.min_unit = COALESCE($inventories[rc_name].min_unit, 1),
    inv.max_unit = COALESCE($inventories[rc_name].max_unit, $inventories[rc_name].total),
    inv.step_size = COALESCE($inventories[rc_name].step_size, 1),
    inv.allocation_ratio = COALESCE($inventories[rc_name].allocation_ratio, 1.0),
    inv.updated_at = datetime()

// Increment generation
WITH rp
SET rp.generation = rp.generation + 1,
    rp.updated_at = datetime()

RETURN rp
```

## Traits

| Placement API | HTTP | Tachyon Neo4j Operation |
|---------------|------|-------------------------|
| `GET /traits` | GET | `MATCH (t:Trait) RETURN t` |
| `PUT /traits/{name}` | PUT | `MERGE (t:Trait {name: $name})` |
| `GET /traits/{name}` | GET | `MATCH (t:Trait {name: $name})` |
| `DELETE /traits/{name}` | DELETE | `MATCH (t:Trait {name: $name}) DELETE t` |
| `GET /resource_providers/{uuid}/traits` | GET | `MATCH (rp)-[:HAS_TRAIT]->(t)` |
| `PUT /resource_providers/{uuid}/traits` | PUT | Replace all traits |

### PUT /resource_providers/{uuid}/traits

```cypher
MATCH (rp:ResourceProvider {uuid: $uuid})
WHERE rp.generation = $resource_provider_generation

// Remove existing trait relationships
OPTIONAL MATCH (rp)-[r:HAS_TRAIT]->()
DELETE r

// Create new trait relationships
WITH rp
UNWIND $traits AS trait_name
MERGE (t:Trait {name: trait_name})
ON CREATE SET t.standard = NOT trait_name STARTS WITH 'CUSTOM_',
              t.created_at = datetime(),
              t.updated_at = datetime()
CREATE (rp)-[:HAS_TRAIT]->(t)

// Increment generation
WITH rp
SET rp.generation = rp.generation + 1,
    rp.updated_at = datetime()

RETURN rp
```

## Allocations

| Placement API | HTTP | Tachyon Neo4j Operation |
|---------------|------|-------------------------|
| `GET /allocations/{consumer_uuid}` | GET | `MATCH (c:Consumer {uuid})-[:CONSUMES]->()` |
| `PUT /allocations/{consumer_uuid}` | PUT | Replace consumer allocations |
| `DELETE /allocations/{consumer_uuid}` | DELETE | Delete all consumer allocations |
| `POST /allocations` | POST | Bulk reshaper operation |

### GET /allocations/{consumer_uuid}

```cypher
MATCH (c:Consumer {uuid: $consumer_uuid})
OPTIONAL MATCH (c)-[alloc:CONSUMES]->(inv)-[:OF_CLASS]->(rc:ResourceClass)
OPTIONAL MATCH (inv)<-[:HAS_INVENTORY]-(rp:ResourceProvider)
OPTIONAL MATCH (c)-[:OWNED_BY]->(proj:Project)
OPTIONAL MATCH (c)-[:CREATED_BY]->(user:User)

RETURN {
  allocations: collect({
    resource_provider: {uuid: rp.uuid},
    resources: {[rc.name]: alloc.used}
  }),
  consumer_generation: c.generation,
  project_id: proj.external_id,
  user_id: user.external_id
} AS allocation_data
```

## Allocation Candidates

| Placement API | HTTP | Tachyon Neo4j Operation |
|---------------|------|-------------------------|
| `GET /allocation_candidates` | GET | Complex graph query |

**Query parameter mapping:**

| Placement Parameter | Tachyon Equivalent |
|--------------------|--------------------|
| `resources` | Filter on HAS_INVENTORY with capacity check |
| `required` | ALL traits must exist via HAS_TRAIT |
| `forbidden` | NONE of traits exist via HAS_TRAIT |
| `member_of` | MEMBER_OF aggregate relationship |
| `in_tree` | PARENT_OF path from specified root |
| `limit` | LIMIT clause |
| `group_policy` | Provider isolation in result grouping |

## Usages

| Placement API | HTTP | Tachyon Neo4j Operation |
|---------------|------|-------------------------|
| `GET /resource_providers/{uuid}/usages` | GET | Sum CONSUMES.used per resource class |
| `GET /usages?project_id=X` | GET | Sum by project across all providers |

```cypher
MATCH (rp:ResourceProvider {uuid: $uuid})
      -[:HAS_INVENTORY]->(inv)
      -[:OF_CLASS]->(rc:ResourceClass)
OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()

WITH rc.name AS resource_class, COALESCE(sum(alloc.used), 0) AS usage
RETURN {usages: collect({resource_class: resource_class, usage: usage})} AS result
```

