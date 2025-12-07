---
title: Aggregate-Based Constraints
description: member_of filtering, tenant isolation, image isolation
keywords: [member-of, tenant-isolation, image-isolation, availability-zone]
related:
  - 01-schema/nodes/aggregate.md
  - 01-schema/relationships/scheduling.md
implements:
  - "Host aggregates"
  - "Tenant isolation"
  - "Image isolation"
  - "Availability zones"
section: constraints
---

# Aggregate-Based Constraints

## Member Of (Required Aggregate)

Provider must be in specific aggregate(s).

```cypher
// Single aggregate
MATCH (rp:ResourceProvider)-[:MEMBER_OF]->(:Aggregate {uuid: $aggregate_uuid})

// Any of multiple aggregates (OR)
MATCH (rp:ResourceProvider)-[:MEMBER_OF]->(agg:Aggregate)
WHERE agg.uuid IN $aggregate_uuids

// All of multiple aggregates (AND)
MATCH (rp:ResourceProvider)
WHERE ALL(agg_uuid IN $aggregate_uuids 
      WHERE (rp)-[:MEMBER_OF]->(:Aggregate {uuid: agg_uuid}))
```

## Forbidden Aggregate Membership

Provider must NOT be in specific aggregate(s).

```cypher
// Not in any of these aggregates
MATCH (rp:ResourceProvider)
WHERE NONE(agg_uuid IN $forbidden_aggregates 
      WHERE (rp)-[:MEMBER_OF]->(:Aggregate {uuid: agg_uuid}))
```

## Availability Zone Constraint

```cypher
// Find providers in specific AZ
MATCH (rp:ResourceProvider)
      -[:MEMBER_OF]->(agg:Aggregate)
      -[:DEFINES_AZ]->(:AvailabilityZone {name: $az_name})
RETURN DISTINCT rp

// Providers not in any AZ (default zone)
MATCH (rp:ResourceProvider)
WHERE NOT EXISTS {
  MATCH (rp)-[:MEMBER_OF]->(:Aggregate)-[:DEFINES_AZ]->(:AvailabilityZone)
}
RETURN rp
```

## Tenant Isolation

Aggregates with TENANT_ALLOWED restrict which projects can schedule.

```cypher
// Check if project can use provider
MATCH (rp:ResourceProvider)
OPTIONAL MATCH (rp)-[:MEMBER_OF]->(agg:Aggregate)-[:TENANT_ALLOWED]->(allowed:Project)

// Provider is usable if:
// 1. Not in any aggregate with tenant restrictions, OR
// 2. In aggregate that allows this project
WITH rp, collect(DISTINCT agg) AS isolated_aggs, collect(DISTINCT allowed) AS allowed_projects
WHERE size(isolated_aggs) = 0 
   OR ANY(p IN allowed_projects WHERE p.external_id = $project_id)
RETURN rp
```

### Alternative Tenant Isolation Query

```cypher
// Find all providers accessible to a project
MATCH (rp:ResourceProvider)
WHERE NOT EXISTS {
  // Provider is in an isolated aggregate that doesn't allow this project
  MATCH (rp)-[:MEMBER_OF]->(agg:Aggregate)-[:TENANT_ALLOWED]->(:Project)
  WHERE NOT (agg)-[:TENANT_ALLOWED]->(:Project {external_id: $project_id})
}
RETURN rp
```

## Image Isolation

```cypher
// Check if image can use provider based on aggregate isolation
MATCH (rp:ResourceProvider)
OPTIONAL MATCH (rp)-[:MEMBER_OF]->(agg:Aggregate)-[:IMAGE_ALLOWED]->(img:Image)

WITH rp, collect(DISTINCT agg) AS isolated_aggs, collect(DISTINCT img) AS allowed_images
WHERE size(isolated_aggs) = 0 
   OR ANY(i IN allowed_images WHERE i.uuid = $image_uuid)
RETURN rp
```

## Aggregate Instance Extra Specs

Match flavor extra specs against aggregate metadata.

```cypher
// Match aggregate metadata to flavor extra specs
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// Get aggregates with metadata
OPTIONAL MATCH (host)-[:MEMBER_OF]->(agg:Aggregate)

WITH host, collect(agg) AS host_aggs
WHERE size(host_aggs) = 0 OR
      ANY(agg IN host_aggs WHERE
        ALL(key IN keys($aggregate_extra_specs) WHERE
          agg[key] IS NULL OR agg[key] = $aggregate_extra_specs[key]
        )
      )

RETURN host
```

## Combined Aggregate Filtering

```cypher
// Full aggregate filtering with AZ, member_of, and tenant isolation
MATCH (rp:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(rp)

// AZ filter
AND (
  $az_name IS NULL OR
  EXISTS {
    MATCH (rp)-[:MEMBER_OF]->(:Aggregate)-[:DEFINES_AZ]->(:AvailabilityZone {name: $az_name})
  }
)

// member_of filter (any of)
AND (
  size($member_of) = 0 OR 
  EXISTS {
    MATCH (rp)-[:MEMBER_OF]->(agg:Aggregate)
    WHERE agg.uuid IN $member_of
  }
)

// Tenant isolation
AND NOT EXISTS {
  MATCH (rp)-[:MEMBER_OF]->(agg:Aggregate)-[:TENANT_ALLOWED]->(:Project)
  WHERE NOT (agg)-[:TENANT_ALLOWED]->(:Project {external_id: $project_id})
}

RETURN rp
```

