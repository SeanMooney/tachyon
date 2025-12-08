---
title: Group and Cell Weighers
description: ServerGroup soft weighers, CrossCellWeigher, BuildFailureWeigher
keywords: [group-weigher, cross-cell, build-failure, hypervisor-version]
related:
  - 03-constraints/server-group-constraints.md
  - 01-schema/nodes/nova-entities.md
implements:
  - "ServerGroupSoftAffinityWeigher"
  - "ServerGroupSoftAntiAffinityWeigher"
  - "CrossCellWeigher"
  - "BuildFailureWeigher"
  - "HypervisorVersionWeigher"
section: queries/weighers
---

# Group and Cell Weighers

## ServerGroupSoftAffinityWeigher

Prefer hosts with more group members (for soft-affinity policy).

```cypher
MATCH (sg:ServerGroup {uuid: $group_uuid})
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// Count group members on each host
OPTIONAL MATCH (sg)-[:HAS_MEMBER]->(member:Consumer)-[:SCHEDULED_ON]->(host)
WITH host, count(member) AS group_instance_count

// More instances = higher weight (prefer collocation)
RETURN host, group_instance_count,
       group_instance_count * $soft_affinity_weight_multiplier AS affinity_weight
ORDER BY affinity_weight DESC
```

## ServerGroupSoftAntiAffinityWeigher

Prefer hosts with fewer group members (for soft-anti-affinity policy).

```cypher
MATCH (sg:ServerGroup {uuid: $group_uuid})
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// Count group members on each host
OPTIONAL MATCH (sg)-[:HAS_MEMBER]->(member:Consumer)-[:SCHEDULED_ON]->(host)
WITH host, count(member) AS instance_count

// Fewer instances = higher weight (prefer spreading)
// Use negative count so lowest count gets highest weight
RETURN host, instance_count,
       -1 * instance_count * $soft_anti_affinity_weight_multiplier AS anti_affinity_weight
ORDER BY anti_affinity_weight DESC
```

## CrossCellWeigher

Prefer local cell for migrations.

```cypher
// Prefer hosts in same cell as existing instance
MATCH (existing:Consumer {uuid: $instance_uuid})
      -[:SCHEDULED_ON]->(current_host)
      -[:LOCATED_IN]->(current_cell:Cell)

MATCH (candidate:ResourceProvider)-[:LOCATED_IN]->(candidate_cell:Cell)
WHERE NOT ()-[:PARENT_OF]->(candidate)

WITH candidate, current_cell, candidate_cell,
     CASE WHEN current_cell = candidate_cell THEN 0 ELSE 1 END AS cross_cell_penalty

RETURN candidate, cross_cell_penalty,
       -1 * cross_cell_penalty * $cross_cell_weight_multiplier AS cell_weight
ORDER BY cell_weight DESC
```

## BuildFailureWeigher

Penalize hosts with recent build failures.

```cypher
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// Get recent build failures (stored as property or separate counter)
WITH host, COALESCE(host.recent_build_failures, 0) AS failures

// Higher failures = lower weight
RETURN host, failures,
       -1 * failures * $build_failure_weight_multiplier AS failure_weight
ORDER BY failure_weight DESC
```

## HypervisorVersionWeigher

Prefer hosts with newer hypervisor versions.

```cypher
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)
  AND host.hypervisor_version IS NOT NULL

WITH host, host.hypervisor_version AS version

// Normalize versions
WITH collect({host: host, version: version}) AS all_hosts
WITH all_hosts,
     reduce(max_v = 0, h IN all_hosts |
            CASE WHEN h.version > max_v THEN h.version ELSE max_v END) AS max_version

UNWIND all_hosts AS h
WITH h.host AS host, h.version AS version,
     toFloat(h.version) / max_version AS normalized_version

// Positive multiplier = prefer newer versions
RETURN host, version,
       normalized_version * $hypervisor_version_weight_multiplier AS version_weight
ORDER BY version_weight DESC
```

## Combined Weigher Including Groups

```cypher
// Combine all weigher scores
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// RAM weight
MATCH (host)-[:HAS_INVENTORY]->(mem_inv)-[:OF_CLASS]->(:ResourceClass {name: 'MEMORY_MB'})
OPTIONAL MATCH (mem_inv)<-[m_alloc:CONSUMES]-()
WITH host,
     (mem_inv.total - mem_inv.reserved) * mem_inv.allocation_ratio - COALESCE(sum(m_alloc.used), 0) AS free_ram

// CPU weight
MATCH (host)-[:HAS_INVENTORY]->(cpu_inv)-[:OF_CLASS]->(:ResourceClass {name: 'VCPU'})
OPTIONAL MATCH (cpu_inv)<-[c_alloc:CONSUMES]-()
WITH host, free_ram,
     (cpu_inv.total - cpu_inv.reserved) * cpu_inv.allocation_ratio - COALESCE(sum(c_alloc.used), 0) AS free_vcpus

// Server group soft affinity (if applicable)
OPTIONAL MATCH (sg:ServerGroup {uuid: $group_uuid})-[:HAS_MEMBER]->(member:Consumer)-[:SCHEDULED_ON]->(host)
WITH host, free_ram, free_vcpus, count(member) AS group_count

// Trait affinity
WITH host, free_ram, free_vcpus, group_count,
     reduce(pref = 0.0, p IN $preferred_traits |
       pref + CASE WHEN (host)-[:HAS_TRAIT]->(:Trait {name: p.name}) THEN p.weight ELSE 0 END
     ) AS preferred_score,
     reduce(avoid = 0.0, a IN $avoided_traits |
       avoid + CASE WHEN (host)-[:HAS_TRAIT]->(:Trait {name: a.name}) THEN a.weight ELSE 0 END
     ) AS avoided_penalty

// Calculate final weight
WITH host, free_ram, free_vcpus, group_count, preferred_score, avoided_penalty,
     (free_ram / 1024.0) * $ram_weight_multiplier +
     free_vcpus * $cpu_weight_multiplier +
     group_count * $soft_affinity_weight_multiplier +
     (preferred_score - avoided_penalty) * $trait_weight_multiplier AS total_weight

RETURN host, free_ram, free_vcpus, group_count, total_weight
ORDER BY total_weight DESC
LIMIT $host_subset_size
```

## Policy-Based Group Weigher

Apply weigher based on group policy.

```cypher
OPTIONAL MATCH (sg:ServerGroup {uuid: $group_uuid})
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// Count group members on host
OPTIONAL MATCH (sg)-[:HAS_MEMBER]->(member:Consumer)-[:SCHEDULED_ON]->(host)
WITH host, sg, count(member) AS member_count

// Apply weigher based on policy
WITH host, member_count,
     CASE sg.policy
       WHEN 'soft-affinity' THEN member_count * $soft_affinity_weight_multiplier
       WHEN 'soft-anti-affinity' THEN -1 * member_count * $soft_anti_affinity_weight_multiplier
       ELSE 0  // No weighing for hard policies or no group
     END AS group_weight

RETURN host, member_count, group_weight
ORDER BY group_weight DESC
```
