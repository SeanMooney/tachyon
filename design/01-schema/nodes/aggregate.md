---
title: Aggregate and AvailabilityZone Nodes
description: Grouping mechanisms for resource providers
keywords: [aggregate, availability-zone, host-aggregate, grouping]
related:
  - 01-schema/nodes/resource-provider.md
  - 01-schema/relationships/membership.md
  - 03-constraints/aggregate-constraints.md
implements:
  - "Host aggregates with metadata"
  - "Availability zones"
  - "Tenant isolation"
section: schema/nodes
---

# Aggregate and AvailabilityZone Nodes

## Aggregate

Grouping mechanism for resource providers.

```
:Aggregate
  uuid:       String!    # External identifier
  name:       String     # Optional human-readable name
  created_at: DateTime!
  updated_at: DateTime!
```

### Purpose

- Logical grouping (availability zones, host aggregates)
- Enables shared resources via SHARES_RESOURCES relationship
- Filters via member_of queries
- Tenant isolation via TENANT_ALLOWED relationship

### Example

```cypher
CREATE (agg:Aggregate {
  uuid: 'agg-uuid-001',
  name: 'gpu-hosts',
  created_at: datetime(),
  updated_at: datetime()
})
```

### Relationships

| Relationship | Direction | Target | Description |
|--------------|-----------|--------|-------------|
| `MEMBER_OF` | incoming | ResourceProvider | Provider membership |
| `DEFINES_AZ` | outgoing | AvailabilityZone | AZ definition |
| `TENANT_ALLOWED` | outgoing | Project | Tenant isolation |
| `IMAGE_ALLOWED` | outgoing | Image | Image isolation |

---

## AvailabilityZone

Availability zone grouping.

```
:AvailabilityZone
  name:       String!       # AZ name (e.g., "nova", "az1")
  created_at: DateTime!
  updated_at: DateTime!
```

### Relationship to Aggregates

An aggregate can define at most one AZ via `DEFINES_AZ`:

```cypher
// Create AZ and link to aggregate
CREATE (az:AvailabilityZone {name: 'az1', created_at: datetime(), updated_at: datetime()})
MATCH (agg:Aggregate {uuid: $agg_uuid})
CREATE (agg)-[:DEFINES_AZ]->(az)
```

### AZ Query Patterns

```cypher
// Find providers in specific AZ
MATCH (rp:ResourceProvider)-[:MEMBER_OF]->(agg:Aggregate)-[:DEFINES_AZ]->(:AvailabilityZone {name: $az_name})
RETURN DISTINCT rp

// Providers not in any AZ (default zone)
MATCH (rp:ResourceProvider)
WHERE NOT EXISTS {
  MATCH (rp)-[:MEMBER_OF]->(:Aggregate)-[:DEFINES_AZ]->(:AvailabilityZone)
}
RETURN rp
```

---

## Aggregate Metadata Pattern

For aggregate-level configuration, use properties:

```cypher
CREATE (agg:Aggregate {
  uuid: randomUUID(),
  name: 'ssd-hosts',
  // Metadata as properties
  ssd: 'true',
  gpu_type: 'nvidia',
  trait_weight_multiplier: 2.0,
  created_at: datetime(),
  updated_at: datetime()
})
```

This enables AggregateInstanceExtraSpecsFilter equivalent queries:

```cypher
MATCH (rp:ResourceProvider)-[:MEMBER_OF]->(agg:Aggregate)
WHERE agg.ssd = 'true'
RETURN rp
```

