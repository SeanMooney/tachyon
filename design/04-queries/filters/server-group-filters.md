---
title: Server Group Filters
description: Affinity and anti-affinity filter implementations
keywords: [affinity-filter, anti-affinity-filter, server-group-filter]
related:
  - 03-constraints/server-group-constraints.md
  - 01-schema/nodes/nova-entities.md
implements:
  - "ServerGroupAffinityFilter"
  - "ServerGroupAntiAffinityFilter"
section: queries/filters
---

# Server Group Filters

## ServerGroupAffinityFilter

All group instances must be on the same host.

```cypher
// Find valid hosts for affinity group
MATCH (sg:ServerGroup {uuid: $group_uuid})
WHERE sg.policy = 'affinity'

OPTIONAL MATCH (sg)-[:HAS_MEMBER]->(existing:Consumer)-[:SCHEDULED_ON]->(host:ResourceProvider)

// If group is empty, any host is valid
// If group has members, only the host(s) they're on are valid
WITH sg, collect(DISTINCT host) AS group_hosts

MATCH (candidate:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(candidate)  // Root providers only
  AND (size(group_hosts) = 0 OR candidate IN group_hosts)

RETURN candidate
```

## ServerGroupAntiAffinityFilter

Group instances must be on different hosts.

```cypher
// Find valid hosts for anti-affinity group
MATCH (sg:ServerGroup {uuid: $group_uuid})
WHERE sg.policy = 'anti-affinity'

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
MATCH (sg:ServerGroup {uuid: $group_uuid})
WHERE sg.policy = 'anti-affinity'

MATCH (candidate:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(candidate)

// Count existing group instances on each candidate
OPTIONAL MATCH (sg)-[:HAS_MEMBER]->(member:Consumer)-[:SCHEDULED_ON]->(candidate)
WITH candidate, sg, count(member) AS instance_count

// Check against limit (default is 1 if not specified)
WHERE instance_count < COALESCE(sg.rules.max_server_per_host, 1)

RETURN candidate, instance_count
```

## Combined Server Group Filter

Apply appropriate filter based on policy:

```cypher
MATCH (sg:ServerGroup {uuid: $group_uuid})
MATCH (candidate:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(candidate)

// Get current group state
OPTIONAL MATCH (sg)-[:HAS_MEMBER]->(member:Consumer)-[:SCHEDULED_ON]->(host:ResourceProvider)
WITH sg, candidate,
     collect(DISTINCT host) AS member_hosts,
     count(CASE WHEN host = candidate THEN 1 END) AS count_on_candidate

// Apply policy-specific filter
WITH sg, candidate, member_hosts, count_on_candidate,
     CASE sg.policy
       WHEN 'affinity' THEN
         size(member_hosts) = 0 OR candidate IN member_hosts
       WHEN 'anti-affinity' THEN
         count_on_candidate < COALESCE(sg.rules.max_server_per_host, 1)
       ELSE true  // soft policies don't filter
     END AS passes_filter

WHERE passes_filter

RETURN candidate
```

## DifferentHostFilter

Exclude specific hosts (e.g., scheduler hints).

```cypher
// Scheduler hint: different_host = [uuid1, uuid2, ...]
MATCH (candidate:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(candidate)
  AND NOT candidate.uuid IN $different_host_uuids

RETURN candidate
```

## SameHostFilter

Include only specific hosts.

```cypher
// Scheduler hint: same_host = [uuid1, uuid2, ...]
MATCH (candidate:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(candidate)
  AND candidate.uuid IN $same_host_uuids

RETURN candidate
```

## Full Server Group Check

Complete filter including group lookup:

```cypher
// Find valid hosts considering server group (if any)
MATCH (candidate:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(candidate)

// Check if consumer is in a server group
OPTIONAL MATCH (sg:ServerGroup)-[:HAS_MEMBER]->(:Consumer {uuid: $consumer_uuid})

// Get group distribution
OPTIONAL MATCH (sg)-[:HAS_MEMBER]->(member:Consumer)-[:SCHEDULED_ON]->(host:ResourceProvider)
WITH candidate, sg, collect(DISTINCT host) AS member_hosts

// Apply filter based on policy
WITH candidate, sg, member_hosts,
     CASE
       WHEN sg IS NULL THEN true  // No group, no constraint
       WHEN sg.policy = 'affinity' THEN
         size(member_hosts) = 0 OR candidate IN member_hosts
       WHEN sg.policy = 'anti-affinity' THEN
         NOT candidate IN member_hosts
       ELSE true
     END AS valid

WHERE valid

RETURN candidate
```
