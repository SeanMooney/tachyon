---
title: Membership Relationships
description: HAS_TRAIT, MEMBER_OF, DEFINES_AZ, LOCATED_IN relationships
keywords: [has-trait, member-of, defines-az, located-in, aggregate]
related:
  - 01-schema/nodes/trait.md
  - 01-schema/nodes/aggregate.md
  - 03-constraints/trait-constraints.md
  - 03-constraints/aggregate-constraints.md
implements:
  - "Trait associations"
  - "Aggregate membership"
  - "Availability zone mapping"
section: schema/relationships
---

# Membership Relationships

## HAS_TRAIT

Associates traits with resource providers.

```
(:ResourceProvider)-[:HAS_TRAIT]->(:Trait)
```

### Properties

None.

### Semantics

- A provider can have multiple traits
- Traits on root provider apply to scheduling decisions
- Traits on nested providers indicate specific capabilities

### Example

```cypher
// Add trait to provider
MATCH (rp:ResourceProvider {uuid: $rp_uuid})
MERGE (t:Trait {name: 'HW_CPU_X86_AVX2'})
ON CREATE SET t.standard = true, t.created_at = datetime(), t.updated_at = datetime()
CREATE (rp)-[:HAS_TRAIT]->(t)
```

### Query Patterns

```cypher
// Required traits (provider must have all)
MATCH (rp:ResourceProvider)
WHERE ALL(trait IN $required_traits WHERE
  (rp)-[:HAS_TRAIT]->(:Trait {name: trait})
)
RETURN rp

// Forbidden traits (provider must have none)
MATCH (rp:ResourceProvider)
WHERE NONE(trait IN $forbidden_traits WHERE
  (rp)-[:HAS_TRAIT]->(:Trait {name: trait})
)
RETURN rp
```

---

## MEMBER_OF

Associates resource providers with aggregates.

```
(:ResourceProvider)-[:MEMBER_OF]->(:Aggregate)
```

### Properties

None.

### Semantics

- A provider can be member of multiple aggregates
- Used for AZ mapping, host aggregates, tenant isolation

### Example

```cypher
// Add provider to aggregate
MATCH (rp:ResourceProvider {uuid: $rp_uuid})
MATCH (agg:Aggregate {uuid: $agg_uuid})
CREATE (rp)-[:MEMBER_OF]->(agg)
```

### Query Patterns

```cypher
// Providers in specific aggregate
MATCH (rp:ResourceProvider)-[:MEMBER_OF]->(:Aggregate {uuid: $agg_uuid})
RETURN rp

// Providers in any of multiple aggregates (OR)
MATCH (rp:ResourceProvider)-[:MEMBER_OF]->(agg:Aggregate)
WHERE agg.uuid IN $aggregate_uuids
RETURN DISTINCT rp

// Providers in all of multiple aggregates (AND)
MATCH (rp:ResourceProvider)
WHERE ALL(agg_uuid IN $aggregate_uuids
      WHERE (rp)-[:MEMBER_OF]->(:Aggregate {uuid: agg_uuid}))
RETURN rp
```

---

## DEFINES_AZ

Links aggregate to an availability zone.

```
(:Aggregate)-[:DEFINES_AZ]->(:AvailabilityZone)
```

### Properties

None.

### Semantics

- An aggregate can define at most one AZ
- Multiple aggregates can define the same AZ
- Used for map_az_to_placement_aggregate functionality

### Example

```cypher
// Link aggregate to AZ
MATCH (agg:Aggregate {uuid: $agg_uuid})
MERGE (az:AvailabilityZone {name: $az_name})
ON CREATE SET az.created_at = datetime(), az.updated_at = datetime()
CREATE (agg)-[:DEFINES_AZ]->(az)
```

### Query Pattern

```cypher
// Find providers in AZ
MATCH (rp:ResourceProvider)
      -[:MEMBER_OF]->(agg:Aggregate)
      -[:DEFINES_AZ]->(:AvailabilityZone {name: $az_name})
RETURN DISTINCT rp
```

---

## LOCATED_IN

Links resource provider to its cell.

```
(:ResourceProvider)-[:LOCATED_IN]->(:Cell)
```

### Properties

None.

### Example

```cypher
// Assign provider to cell
MATCH (rp:ResourceProvider {uuid: $rp_uuid})
MATCH (cell:Cell {uuid: $cell_uuid})
CREATE (rp)-[:LOCATED_IN]->(cell)
```

### Query Pattern

```cypher
// Prefer local cell for migrations
MATCH (existing:Consumer {uuid: $instance_uuid})
      -[:SCHEDULED_ON]->(current_host)
      -[:LOCATED_IN]->(current_cell:Cell)
MATCH (candidate:ResourceProvider)-[:LOCATED_IN]->(candidate_cell:Cell)
WITH candidate, current_cell, candidate_cell,
     CASE WHEN current_cell = candidate_cell THEN 0 ELSE 1 END AS cross_cell_penalty
RETURN candidate, cross_cell_penalty
ORDER BY cross_cell_penalty
```

---

## Cardinality Summary

| Relationship | From | To | Cardinality |
|--------------|------|-----|-------------|
| HAS_TRAIT | ResourceProvider | Trait | 0..N : 0..N |
| MEMBER_OF | ResourceProvider | Aggregate | 0..N : 0..N |
| DEFINES_AZ | Aggregate | AvailabilityZone | N : 0..1 |
| LOCATED_IN | ResourceProvider | Cell | N : 1 |
