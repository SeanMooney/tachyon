---
title: Simulation Operations
description: API operations for speculative what-if analysis
keywords: [simulation, session, speculative, what-if, optimization, delta, sandbox]
related:
  - 07-watcher-integration/simulation-sessions.md
  - 07-watcher-integration/watcher-model-mapping.md
  - 05-operations/resource-claiming.md
implements:
  - "Speculative planning"
  - "What-if analysis"
section: operations
---

# Simulation Operations

This document defines the API operations for Tachyon's simulation capability, enabling server-side speculative analysis for optimization planning.

## Overview

Simulation operations allow clients to:

1. Create isolated sandbox sessions
2. Record speculative changes (deltas) without affecting global state
3. Query virtual state with deltas applied
4. Compute optimization metrics on speculative states
5. Commit successful plans or discard failed attempts

## Session Lifecycle Operations

### Create Session

Initialize a new simulation session anchored to the current global state.

```cypher
// Parameters:
// $session_id: 'uuid' - Unique session identifier
// $ttl: 'PT1H' - Time-to-live duration
// $audit_uuid: 'uuid' - Optional associated Watcher audit

// Get current global generation for consistency baseline
MATCH (global:GlobalState)
WITH global.generation AS base_gen

CREATE (s:SimulationSession {
  id: $session_id,
  base_generation: base_gen,
  created_at: datetime(),
  expires_at: datetime() + duration($ttl),
  audit_uuid: $audit_uuid,
  status: 'active',
  delta_count: 0
})

RETURN s.id AS session_id,
       s.base_generation AS base_generation,
       s.expires_at AS expires_at
```

### Get Session

Retrieve session metadata and delta summary.

```cypher
MATCH (s:SimulationSession {id: $session_id})

// Count deltas by type
OPTIONAL MATCH (s)-[:HAS_DELTA]->(d:SpeculativeDelta)
WITH s, d.type AS delta_type, count(d) AS count
WITH s, collect({type: delta_type, count: count}) AS delta_summary

RETURN s.id AS session_id,
       s.status AS status,
       s.base_generation AS base_generation,
       s.created_at AS created_at,
       s.expires_at AS expires_at,
       delta_summary
```

### List Sessions

List active sessions, optionally filtered by audit.

```cypher
// Parameters:
// $audit_uuid: Optional filter by audit
// $status: Optional filter by status (default: 'active')

MATCH (s:SimulationSession)
WHERE ($audit_uuid IS NULL OR s.audit_uuid = $audit_uuid)
  AND ($status IS NULL OR s.status = $status)
  AND s.expires_at > datetime()

OPTIONAL MATCH (s)-[:HAS_DELTA]->(d:SpeculativeDelta)
WITH s, count(d) AS delta_count

RETURN s.id AS session_id,
       s.status AS status,
       s.audit_uuid AS audit_uuid,
       s.created_at AS created_at,
       s.expires_at AS expires_at,
       delta_count
ORDER BY s.created_at DESC
```

### Extend Session TTL

Extend the expiration time for long-running optimizations.

```cypher
MATCH (s:SimulationSession {id: $session_id})
WHERE s.status = 'active'

SET s.expires_at = datetime() + duration($additional_ttl)

RETURN s.id AS session_id,
       s.expires_at AS new_expires_at
```

### Delete Session

Explicitly delete a session and its deltas.

```cypher
MATCH (s:SimulationSession {id: $session_id})

// Delete all deltas
OPTIONAL MATCH (s)-[:HAS_DELTA]->(d:SpeculativeDelta)
DELETE d

// Delete session
DELETE s

RETURN true AS deleted
```

## Delta Operations

### Record Move

Simulate migrating a consumer from one provider to another.

```cypher
// Parameters:
// $session_id: Session identifier
// $consumer_uuid: Consumer (instance) to move
// $from_provider: Source provider UUID
// $to_provider: Destination provider UUID

MATCH (s:SimulationSession {id: $session_id})
WHERE s.status = 'active'

// Validate consumer exists and get current allocations
MATCH (consumer:Consumer {uuid: $consumer_uuid})
      -[alloc:CONSUMES]->(inv:Inventory)
      -[:OF_CLASS]->(rc:ResourceClass)

// Verify consumer is currently on source provider (in global or virtual state)
MATCH (inv)<-[:HAS_INVENTORY]-(source:ResourceProvider {uuid: $from_provider})

// Get resource amounts for the move
WITH s, consumer,
     apoc.map.fromPairs(collect([rc.name, alloc.used])) AS resource_amounts

// Check for existing moves of this consumer in session
OPTIONAL MATCH (s)-[:HAS_DELTA]->(existing:SpeculativeDelta)
WHERE existing.consumer_uuid = consumer.uuid AND existing.type = 'MOVE'
WITH s, consumer, resource_amounts, max(existing.sequence) AS last_move_seq

// If there was a previous move, verify we're moving from the right place
// (the previous move's destination)
OPTIONAL MATCH (s)-[:HAS_DELTA]->(last_move:SpeculativeDelta {sequence: last_move_seq})
WHERE last_move.consumer_uuid = consumer.uuid
WITH s, consumer, resource_amounts,
     CASE
       WHEN last_move IS NOT NULL AND last_move.to_provider <> $from_provider
       THEN false
       ELSE true
     END AS valid_source

WHERE valid_source = true

// Get next sequence number
OPTIONAL MATCH (s)-[:HAS_DELTA]->(any_delta:SpeculativeDelta)
WITH s, consumer, resource_amounts,
     COALESCE(max(any_delta.sequence), 0) + 1 AS next_seq

// Validate destination has inventory
MATCH (dest:ResourceProvider {uuid: $to_provider})
      -[:HAS_INVENTORY]->(dest_inv:Inventory)
      -[:OF_CLASS]->(dest_rc:ResourceClass)
WHERE dest_rc.name IN keys(resource_amounts)

// Create the delta
CREATE (s)-[:HAS_DELTA]->(d:SpeculativeDelta {
  sequence: next_seq,
  type: 'MOVE',
  consumer_uuid: consumer.uuid,
  from_provider: $from_provider,
  to_provider: $to_provider,
  resource_changes: resource_amounts,
  created_at: datetime()
})

SET s.delta_count = s.delta_count + 1

RETURN d.sequence AS sequence,
       d.type AS type,
       d.consumer_uuid AS consumer,
       d.from_provider AS from_provider,
       d.to_provider AS to_provider,
       d.resource_changes AS resources
```

### Record Allocation

Simulate creating a new allocation.

```cypher
// Parameters:
// $session_id: Session identifier
// $consumer_uuid: New or existing consumer UUID
// $allocations: [{provider_uuid, resource_class, amount}, ...]

MATCH (s:SimulationSession {id: $session_id})
WHERE s.status = 'active'

// Get next sequence
OPTIONAL MATCH (s)-[:HAS_DELTA]->(existing:SpeculativeDelta)
WITH s, COALESCE(max(existing.sequence), 0) + 1 AS next_seq

// Build resource changes map
UNWIND $allocations AS alloc
WITH s, next_seq, alloc.provider_uuid AS provider,
     collect({resource_class: alloc.resource_class, amount: alloc.amount}) AS resources

// Create delta
CREATE (s)-[:HAS_DELTA]->(d:SpeculativeDelta {
  sequence: next_seq,
  type: 'ALLOCATE',
  consumer_uuid: $consumer_uuid,
  to_provider: provider,
  resource_changes: apoc.map.fromPairs(
    [r IN resources | [r.resource_class, r.amount]]
  ),
  created_at: datetime()
})

SET s.delta_count = s.delta_count + 1

RETURN d.sequence AS sequence
```

### Record Deallocation

Simulate removing an allocation.

```cypher
// Parameters:
// $session_id: Session identifier
// $consumer_uuid: Consumer to deallocate

MATCH (s:SimulationSession {id: $session_id})
WHERE s.status = 'active'

// Get consumer's current allocations
MATCH (consumer:Consumer {uuid: $consumer_uuid})
      -[alloc:CONSUMES]->(inv:Inventory)
      -[:OF_CLASS]->(rc:ResourceClass)
      <-[:HAS_INVENTORY]-(rp:ResourceProvider)

WITH s, consumer, rp.uuid AS provider,
     apoc.map.fromPairs(collect([rc.name, alloc.used])) AS resource_amounts

// Get next sequence
OPTIONAL MATCH (s)-[:HAS_DELTA]->(existing:SpeculativeDelta)
WITH s, consumer, provider, resource_amounts,
     COALESCE(max(existing.sequence), 0) + 1 AS next_seq

// Create delta
CREATE (s)-[:HAS_DELTA]->(d:SpeculativeDelta {
  sequence: next_seq,
  type: 'DEALLOCATE',
  consumer_uuid: consumer.uuid,
  from_provider: provider,
  resource_changes: resource_amounts,
  created_at: datetime()
})

SET s.delta_count = s.delta_count + 1

RETURN d.sequence AS sequence
```

### Undo Last Delta

Remove the most recent delta from a session.

```cypher
MATCH (s:SimulationSession {id: $session_id})
WHERE s.status = 'active'

// Find the last delta
MATCH (s)-[:HAS_DELTA]->(d:SpeculativeDelta)
WITH s, d ORDER BY d.sequence DESC LIMIT 1

// Delete it
DELETE d
SET s.delta_count = s.delta_count - 1

RETURN true AS undone
```

### Get Delta History

List all deltas in a session.

```cypher
MATCH (s:SimulationSession {id: $session_id})
      -[:HAS_DELTA]->(d:SpeculativeDelta)

RETURN d.sequence AS sequence,
       d.type AS type,
       d.consumer_uuid AS consumer,
       d.from_provider AS from_provider,
       d.to_provider AS to_provider,
       d.resource_changes AS resources,
       d.created_at AS created_at
ORDER BY d.sequence
```

## Virtual State Queries

### Get Effective Placement

Query where consumers are located in virtual state (with deltas applied).

```cypher
// Parameters:
// $session_id: Session identifier
// $consumer_uuids: Optional list of specific consumers to query

MATCH (s:SimulationSession {id: $session_id})

// Get all consumers (or specific ones)
MATCH (consumer:Consumer)
WHERE $consumer_uuids IS NULL OR consumer.uuid IN $consumer_uuids

// Get their current global placement
MATCH (consumer)-[:CONSUMES]->(:Inventory)<-[:HAS_INVENTORY]-(global_rp:ResourceProvider)

// Get the last MOVE delta for each consumer
OPTIONAL MATCH (s)-[:HAS_DELTA]->(d:SpeculativeDelta)
WHERE d.consumer_uuid = consumer.uuid AND d.type = 'MOVE'
WITH consumer, global_rp, d
ORDER BY d.sequence DESC
WITH consumer, global_rp, head(collect(d)) AS last_move

// Check for DEALLOCATE deltas
OPTIONAL MATCH (s)-[:HAS_DELTA]->(dealloc:SpeculativeDelta)
WHERE dealloc.consumer_uuid = consumer.uuid AND dealloc.type = 'DEALLOCATE'

// Compute effective placement
WITH consumer,
     CASE
       WHEN dealloc IS NOT NULL THEN null  // Deallocated
       WHEN last_move IS NOT NULL THEN last_move.to_provider
       ELSE global_rp.uuid
     END AS effective_provider

RETURN consumer.uuid AS consumer_uuid,
       consumer.name AS consumer_name,
       effective_provider
```

### Get Virtual Resource Usage

Query resource usage per provider with deltas applied.

```cypher
// Parameters:
// $session_id: Session identifier
// $resource_class: Resource class to query (e.g., 'VCPU')

MATCH (s:SimulationSession {id: $session_id})

// Get all providers with this resource
MATCH (rp:ResourceProvider)
      -[:HAS_INVENTORY]->(inv:Inventory)
      -[:OF_CLASS]->(:ResourceClass {name: $resource_class})

// Get base allocations
OPTIONAL MATCH (inv)<-[base_alloc:CONSUMES]-(consumer:Consumer)
WITH s, rp, inv,
     COALESCE(sum(base_alloc.used), 0) AS base_usage,
     collect(DISTINCT consumer.uuid) AS base_consumers

// Get incoming moves (consumers moving TO this provider)
OPTIONAL MATCH (s)-[:HAS_DELTA]->(incoming:SpeculativeDelta)
WHERE incoming.to_provider = rp.uuid
  AND incoming.type IN ['MOVE', 'ALLOCATE']
  AND incoming.consumer_uuid NOT IN base_consumers

// Get outgoing moves (consumers moving FROM this provider)
OPTIONAL MATCH (s)-[:HAS_DELTA]->(outgoing:SpeculativeDelta)
WHERE outgoing.from_provider = rp.uuid
  AND outgoing.type IN ['MOVE', 'DEALLOCATE']
  AND outgoing.consumer_uuid IN base_consumers

WITH rp, inv, base_usage,
     collect(DISTINCT incoming) AS incoming_deltas,
     collect(DISTINCT outgoing) AS outgoing_deltas

// Calculate virtual usage
WITH rp, inv, base_usage,
     REDUCE(s = 0, d IN incoming_deltas |
       s + COALESCE(d.resource_changes[$resource_class], 0)) AS incoming_amount,
     REDUCE(s = 0, d IN outgoing_deltas |
       s + COALESCE(d.resource_changes[$resource_class], 0)) AS outgoing_amount

WITH rp, inv,
     base_usage + incoming_amount - outgoing_amount AS virtual_usage,
     (inv.total - inv.reserved) * inv.allocation_ratio AS capacity

RETURN rp.uuid AS provider_uuid,
       rp.name AS provider_name,
       virtual_usage AS used,
       capacity,
       capacity - virtual_usage AS available,
       toFloat(virtual_usage) / capacity AS utilization
ORDER BY utilization DESC
```

### Find Valid Migration Destinations

Find providers with capacity for a consumer in virtual state.

```cypher
// Parameters:
// $session_id: Session identifier
// $consumer_uuid: Consumer to find destinations for
// $exclude_current: Whether to exclude current provider (default true)

MATCH (s:SimulationSession {id: $session_id})

// Get consumer's resource requirements
MATCH (consumer:Consumer {uuid: $consumer_uuid})
      -[alloc:CONSUMES]->(inv:Inventory)
      -[:OF_CLASS]->(rc:ResourceClass)
WITH s, consumer, collect({resource: rc.name, amount: alloc.used}) AS requirements

// Get consumer's effective current provider
MATCH (consumer)-[:CONSUMES]->(:Inventory)<-[:HAS_INVENTORY]-(current_rp:ResourceProvider)
OPTIONAL MATCH (s)-[:HAS_DELTA]->(last_move:SpeculativeDelta)
WHERE last_move.consumer_uuid = consumer.uuid AND last_move.type = 'MOVE'
WITH s, consumer, requirements, current_rp,
     CASE WHEN last_move IS NOT NULL THEN last_move.to_provider ELSE current_rp.uuid END AS current_provider
ORDER BY last_move.sequence DESC
LIMIT 1

// Find all providers with required inventories
UNWIND requirements AS req
MATCH (rp:ResourceProvider)
      -[:HAS_INVENTORY]->(inv:Inventory)
      -[:OF_CLASS]->(:ResourceClass {name: req.resource})
WHERE NOT ($exclude_current = true AND rp.uuid = current_provider)

// Calculate virtual available capacity (simplified - full version in simulation-sessions.md)
OPTIONAL MATCH (inv)<-[existing:CONSUMES]-()
WITH rp, req, inv,
     (inv.total - inv.reserved) * inv.allocation_ratio AS capacity,
     COALESCE(sum(existing.used), 0) AS base_usage

// Check if this provider can accommodate the requirement
WITH rp, collect({
  resource: req.resource,
  required: req.amount,
  available: capacity - base_usage
}) AS resource_checks

WHERE ALL(r IN resource_checks WHERE r.available >= r.required)

RETURN DISTINCT rp.uuid AS provider_uuid,
       rp.name AS provider_name,
       resource_checks
ORDER BY rp.name
```

## Optimization Metrics

### Resource Balance Score

Calculate the standard deviation of resource utilization across providers.

```cypher
// Parameters:
// $session_id: Session identifier
// $resource_class: Resource class to analyze

MATCH (s:SimulationSession {id: $session_id})

// Get virtual utilization for each provider
CALL {
  WITH s
  MATCH (rp:ResourceProvider)
        -[:HAS_INVENTORY]->(inv:Inventory)
        -[:OF_CLASS]->(:ResourceClass {name: $resource_class})

  // ... (virtual usage calculation as above)

  RETURN rp.uuid AS provider, toFloat(virtual_usage) / capacity AS utilization
}

WITH collect(utilization) AS utilizations

// Calculate mean
WITH utilizations,
     REDUCE(sum = 0.0, u IN utilizations | sum + u) / size(utilizations) AS mean

// Calculate variance and standard deviation
WITH utilizations, mean,
     REDUCE(sum = 0.0, u IN utilizations | sum + (u - mean) * (u - mean)) / size(utilizations) AS variance

RETURN mean AS average_utilization,
       sqrt(variance) AS std_deviation,
       min(utilizations) AS min_utilization,
       max(utilizations) AS max_utilization,
       size(utilizations) AS provider_count
```

### Compare Sessions

Compare metrics between two simulation sessions or between a session and global state.

```cypher
// Parameters:
// $session_a: First session ID (or null for global state)
// $session_b: Second session ID
// $resource_class: Resource class to compare

// Get metrics for session A
CALL {
  // ... balance score calculation for session A
  RETURN std_deviation AS sd_a, average_utilization AS avg_a
}

// Get metrics for session B
CALL {
  // ... balance score calculation for session B
  RETURN std_deviation AS sd_b, average_utilization AS avg_b
}

RETURN sd_a AS session_a_std_dev,
       sd_b AS session_b_std_dev,
       avg_a AS session_a_avg_util,
       avg_b AS session_b_avg_util,
       sd_a - sd_b AS std_dev_improvement,
       (sd_a - sd_b) / sd_a * 100 AS std_dev_improvement_pct
```

## Commit Operations

### Validate Before Commit

Check for conflicts before committing a session.

```cypher
MATCH (s:SimulationSession {id: $session_id})
WHERE s.status = 'active'

// Check if global state has advanced
MATCH (global:GlobalState)
WITH s, global,
     s.base_generation < global.generation AS is_stale

// If stale, check for specific conflicts
OPTIONAL MATCH (s)-[:HAS_DELTA]->(d:SpeculativeDelta)
OPTIONAL MATCH (consumer:Consumer {uuid: d.consumer_uuid})
WHERE consumer.generation > s.base_generation

WITH s, is_stale, collect(DISTINCT consumer.uuid) AS conflicting_consumers

// Check provider generation conflicts
OPTIONAL MATCH (s)-[:HAS_DELTA]->(d:SpeculativeDelta)
MATCH (rp:ResourceProvider)
WHERE rp.uuid IN [d.from_provider, d.to_provider]
  AND rp.generation > s.base_generation
WITH is_stale, conflicting_consumers,
     collect(DISTINCT rp.uuid) AS conflicting_providers

RETURN is_stale,
       conflicting_consumers,
       conflicting_providers,
       size(conflicting_consumers) > 0 OR size(conflicting_providers) > 0 AS has_conflicts
```

### Commit Session

Apply session deltas to the global graph.

```cypher
// This is a multi-statement transaction
// Statement 1: Validate and lock

MATCH (s:SimulationSession {id: $session_id})
WHERE s.status = 'active'

MATCH (global:GlobalState)
WHERE global.generation = s.base_generation

// Statement 2: Apply MOVE deltas
MATCH (s)-[:HAS_DELTA]->(d:SpeculativeDelta {type: 'MOVE'})
ORDER BY d.sequence

UNWIND collect(d) AS delta
MATCH (consumer:Consumer {uuid: delta.consumer_uuid})

// Remove old allocations
MATCH (consumer)-[old_alloc:CONSUMES]->(old_inv:Inventory)
      <-[:HAS_INVENTORY]-(old_rp:ResourceProvider {uuid: delta.from_provider})
DELETE old_alloc

// Create new allocations
WITH consumer, delta
UNWIND keys(delta.resource_changes) AS rc_name
MATCH (new_rp:ResourceProvider {uuid: delta.to_provider})
      -[:HAS_INVENTORY]->(new_inv:Inventory)
      -[:OF_CLASS]->(:ResourceClass {name: rc_name})

CREATE (consumer)-[:CONSUMES {
  used: delta.resource_changes[rc_name],
  created_at: datetime()
}]->(new_inv)

SET consumer.generation = consumer.generation + 1;

// Statement 3: Apply ALLOCATE deltas
// ... similar pattern ...

// Statement 4: Apply DEALLOCATE deltas
// ... similar pattern ...

// Statement 5: Finalize
MATCH (s:SimulationSession {id: $session_id})
MATCH (global:GlobalState)

SET s.status = 'committed',
    s.committed_at = datetime(),
    global.generation = global.generation + 1

RETURN s.id AS session_id,
       'committed' AS status,
       global.generation AS new_global_generation
```

### Rollback Session

Discard a session without applying changes.

```cypher
MATCH (s:SimulationSession {id: $session_id})
WHERE s.status = 'active'

// Delete all deltas
OPTIONAL MATCH (s)-[:HAS_DELTA]->(d:SpeculativeDelta)
DELETE d

// Mark as rolled back
SET s.status = 'rolled_back',
    s.rolled_back_at = datetime(),
    s.delta_count = 0

RETURN s.id AS session_id,
       'rolled_back' AS status
```

## Maintenance Operations

### Cleanup Expired Sessions

Periodic job to clean up expired sessions.

```cypher
// Run as a scheduled job
MATCH (s:SimulationSession)
WHERE s.expires_at < datetime()
  AND s.status = 'active'

// Delete deltas
OPTIONAL MATCH (s)-[:HAS_DELTA]->(d:SpeculativeDelta)
DELETE d

// Mark as expired
SET s.status = 'expired',
    s.expired_at = datetime(),
    s.delta_count = 0

RETURN count(s) AS expired_session_count
```

### Session Statistics

Get statistics about simulation sessions.

```cypher
MATCH (s:SimulationSession)

WITH s.status AS status, count(s) AS count,
     avg(s.delta_count) AS avg_deltas

RETURN status,
       count AS session_count,
       avg_deltas AS average_delta_count
ORDER BY count DESC
```

## Error Handling

### Session Not Found

```cypher
OPTIONAL MATCH (s:SimulationSession {id: $session_id})
WITH s
WHERE s IS NULL
CALL apoc.util.validate(true, 'Session not found: %s', [$session_id])
RETURN null
```

### Session Not Active

```cypher
MATCH (s:SimulationSession {id: $session_id})
WHERE s.status <> 'active'
CALL apoc.util.validate(true, 'Session %s is not active (status: %s)', [s.id, s.status])
RETURN null
```

### Capacity Exceeded

```cypher
// During move validation
WITH ... AS available, ... AS required
WHERE available < required
CALL apoc.util.validate(true,
  'Insufficient capacity on provider %s: available=%d, required=%d',
  [provider_uuid, available, required])
RETURN null
```
