---
title: Aggregate Filters
description: Tenant isolation, image isolation, extra specs filters
keywords: [tenant-filter, image-filter, aggregate-filter, isolation]
related:
  - 03-constraints/aggregate-constraints.md
  - 01-schema/nodes/aggregate.md
implements:
  - "AggregateMultiTenancyIsolation"
  - "AggregateImagePropertiesIsolation"
  - "AggregateInstanceExtraSpecsFilter"
section: queries/filters
---

# Aggregate Filters

## AggregateMultiTenancyIsolation

Restrict hosts based on tenant/project.

```cypher
// Find providers accessible to a project
MATCH (rp:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(rp)

  // Provider is valid if:
  // 1. Not in any aggregate with tenant restrictions, OR
  // 2. In aggregate that allows this project
  AND NOT EXISTS {
    // Provider is in an isolated aggregate that doesn't allow this project
    MATCH (rp)-[:MEMBER_OF]->(agg:Aggregate)-[:TENANT_ALLOWED]->(:Project)
    WHERE NOT (agg)-[:TENANT_ALLOWED]->(:Project {external_id: $project_id})
  }

RETURN rp
```

## AggregateImagePropertiesIsolation

Restrict hosts based on image properties.

```cypher
// Find providers where image is allowed
MATCH (rp:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(rp)

  AND NOT EXISTS {
    // Provider is in an isolated aggregate that doesn't allow this image
    MATCH (rp)-[:MEMBER_OF]->(agg:Aggregate)-[:IMAGE_ALLOWED]->(:Image)
    WHERE NOT (agg)-[:IMAGE_ALLOWED]->(:Image {uuid: $image_uuid})
  }

RETURN rp
```

## AggregateInstanceExtraSpecsFilter

Match flavor extra specs against aggregate metadata.

```cypher
// Parameters:
// $aggregate_extra_specs: {'ssd': 'true', 'gpu_type': 'nvidia'}

MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// Host must be in an aggregate matching all specs,
// or not in any aggregate with those keys
WITH host
OPTIONAL MATCH (host)-[:MEMBER_OF]->(agg:Aggregate)

WITH host, collect(agg) AS host_aggs

// Valid if:
// 1. No aggregates, OR
// 2. At least one aggregate matches all specs
WHERE size(host_aggs) = 0 OR
      ANY(agg IN host_aggs WHERE
        ALL(key IN keys($aggregate_extra_specs) WHERE
          agg[key] IS NULL OR agg[key] = $aggregate_extra_specs[key]
        )
      )

RETURN host
```

## AggregateIoOpsFilter

Limit I/O operations per aggregate.

```cypher
// Filter hosts exceeding aggregate I/O limits
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

OPTIONAL MATCH (host)-[:MEMBER_OF]->(agg:Aggregate)
WHERE agg.max_io_ops_per_host IS NOT NULL

// Count I/O-heavy instances on host
OPTIONAL MATCH (c:Consumer)-[:SCHEDULED_ON]->(host)
WHERE c.task_state IN ['spawning', 'resize_migrating', 'rebuilding', 
                       'resize_prep', 'image_snapshot', 'image_backup', 
                       'rescuing', 'unshelving']
WITH host, agg, count(c) AS current_io_ops

// Check limit
WHERE agg IS NULL OR current_io_ops < agg.max_io_ops_per_host

RETURN DISTINCT host
```

## AggregateNumInstancesFilter

Limit total instances per aggregate.

```cypher
// Filter hosts exceeding aggregate instance limits
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

OPTIONAL MATCH (host)-[:MEMBER_OF]->(agg:Aggregate)
WHERE agg.max_instances_per_host IS NOT NULL

// Count instances on host
OPTIONAL MATCH (c:Consumer)-[:SCHEDULED_ON]->(host)
WITH host, agg, count(c) AS instance_count

WHERE agg IS NULL OR instance_count < agg.max_instances_per_host

RETURN DISTINCT host
```

## Combined Aggregate Filter

```cypher
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

  // Tenant isolation
  AND NOT EXISTS {
    MATCH (host)-[:MEMBER_OF]->(agg:Aggregate)-[:TENANT_ALLOWED]->(:Project)
    WHERE NOT (agg)-[:TENANT_ALLOWED]->(:Project {external_id: $project_id})
  }
  
  // Image isolation
  AND NOT EXISTS {
    MATCH (host)-[:MEMBER_OF]->(agg:Aggregate)-[:IMAGE_ALLOWED]->(:Image)
    WHERE NOT (agg)-[:IMAGE_ALLOWED]->(:Image {uuid: $image_uuid})
  }
  
  // Extra specs matching
  AND (
    size(keys($aggregate_extra_specs)) = 0 OR
    EXISTS {
      MATCH (host)-[:MEMBER_OF]->(agg:Aggregate)
      WHERE ALL(key IN keys($aggregate_extra_specs) WHERE
        agg[key] IS NULL OR agg[key] = $aggregate_extra_specs[key]
      )
    } OR
    NOT EXISTS {MATCH (host)-[:MEMBER_OF]->(:Aggregate)}
  )

RETURN host
```

## Availability Zone Filter

```cypher
// Filter to specific AZ
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

  AND (
    $az IS NULL OR
    EXISTS {
      MATCH (host)-[:MEMBER_OF]->(:Aggregate)-[:DEFINES_AZ]->(:AvailabilityZone {name: $az})
    }
  )

RETURN host
```

## Isolated Hosts Filter

Match isolated_images and isolated_hosts configuration.

```cypher
// Isolated hosts filter
// $isolated_hosts: list of host names
// $isolated_images: list of image UUIDs
// If image is in isolated_images, host must be in isolated_hosts (and vice versa)

MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

WITH host,
     host.name IN $isolated_hosts AS host_is_isolated,
     $image_uuid IN $isolated_images AS image_is_isolated

// Host and image isolation must match
WHERE host_is_isolated = image_is_isolated

RETURN host
```

