---
title: Server Group Constraints
description: Affinity, anti-affinity, soft variants, max_server_per_host
keywords: [affinity, anti-affinity, soft-affinity, server-group, max-server-per-host]
related:
  - 01-schema/nodes/nova-entities.md
  - 04-queries/filters/server-group-filters.md
  - 04-queries/weighers/group-weighers.md
implements:
  - "Server group affinity"
  - "Server group anti-affinity"
  - "Soft affinity/anti-affinity"
section: constraints
---

# Server Group Constraints

## Policies

| Policy | Type | Behavior |
|--------|------|----------|
| `affinity` | Hard | All members on same host |
| `anti-affinity` | Hard | All members on different hosts |
| `soft-affinity` | Soft | Prefer same host (weigher) |
| `soft-anti-affinity` | Soft | Prefer different hosts (weigher) |

## Affinity Policy

All group instances must be on the same host.

```cypher
// Find valid hosts for affinity group
MATCH (sg:ServerGroup {uuid: $group_uuid, policy: 'affinity'})
OPTIONAL MATCH (sg)-[:HAS_MEMBER]->(existing:Consumer)-[:SCHEDULED_ON]->(host:ResourceProvider)

// If group is empty, any host is valid
// If group has members, only the host(s) they're on are valid
WITH sg, collect(DISTINCT host) AS group_hosts
MATCH (candidate:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(candidate)  // Root providers only
  AND (size(group_hosts) = 0 OR candidate IN group_hosts)
RETURN candidate
```

## Anti-Affinity Policy

Group instances must be on different hosts.

```cypher
// Find valid hosts for anti-affinity group
MATCH (sg:ServerGroup {uuid: $group_uuid, policy: 'anti-affinity'})
OPTIONAL MATCH (sg)-[:HAS_MEMBER]->(existing:Consumer)-[:SCHEDULED_ON]->(occupied:ResourceProvider)

WITH sg, collect(DISTINCT occupied) AS occupied_hosts
MATCH (candidate:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(candidate)  // Root providers only
  AND NOT candidate IN occupied_hosts
RETURN candidate
```

## Anti-Affinity with max_server_per_host

```cypher
// Find hosts not exceeding max_server_per_host
MATCH (sg:ServerGroup {uuid: $group_uuid, policy: 'anti-affinity'})
MATCH (candidate:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(candidate)

// Count existing group instances on each candidate
OPTIONAL MATCH (sg)-[:HAS_MEMBER]->(member:Consumer)-[:SCHEDULED_ON]->(candidate)
WITH candidate, sg, count(member) AS instance_count

// Check against limit (default is 1 if not specified)
WHERE instance_count < COALESCE(sg.rules.max_server_per_host, 1)
RETURN candidate
```

## Soft Affinity

Prefer hosts with more group members (weigher).

```cypher
// Soft affinity: weight by number of group instances on host
MATCH (sg:ServerGroup {uuid: $group_uuid, policy: 'soft-affinity'})
MATCH (candidate:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(candidate)

OPTIONAL MATCH (sg)-[:HAS_MEMBER]->(member:Consumer)-[:SCHEDULED_ON]->(candidate)
WITH candidate, count(member) AS affinity_score
RETURN candidate, affinity_score
ORDER BY affinity_score DESC
```

## Soft Anti-Affinity

Prefer hosts with fewer group members (weigher).

```cypher
// Soft anti-affinity: weight inversely by group instance count
MATCH (sg:ServerGroup {uuid: $group_uuid, policy: 'soft-anti-affinity'})
MATCH (candidate:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(candidate)

OPTIONAL MATCH (sg)-[:HAS_MEMBER]->(member:Consumer)-[:SCHEDULED_ON]->(candidate)
WITH candidate, count(member) AS instance_count
RETURN candidate, -1 * instance_count AS anti_affinity_score
ORDER BY anti_affinity_score DESC
```

## Creating Server Group Membership

```cypher
// Add consumer to server group
MATCH (sg:ServerGroup {uuid: $group_uuid})
MATCH (c:Consumer {uuid: $consumer_uuid})
CREATE (sg)-[:HAS_MEMBER]->(c)

// Record where consumer is scheduled
MATCH (host:ResourceProvider {uuid: $host_uuid})
CREATE (c)-[:SCHEDULED_ON {
  host: host.name,
  scheduled_at: datetime()
}]->(host)
```

## Check Group Constraint Before Scheduling

```cypher
// Validate scheduling against group policy
MATCH (sg:ServerGroup {uuid: $group_uuid})
MATCH (target_host:ResourceProvider {uuid: $target_host_uuid})

// Get current group distribution
OPTIONAL MATCH (sg)-[:HAS_MEMBER]->(member:Consumer)-[:SCHEDULED_ON]->(host:ResourceProvider)
WITH sg, target_host, collect(DISTINCT host) AS member_hosts, count(member) AS total_members

// Check policy
WITH sg, target_host, member_hosts, total_members,
     CASE sg.policy
       WHEN 'affinity' THEN
         size(member_hosts) = 0 OR target_host IN member_hosts
       WHEN 'anti-affinity' THEN
         NOT target_host IN member_hosts
       ELSE true  // Soft policies don't filter
     END AS policy_satisfied

RETURN policy_satisfied
```
