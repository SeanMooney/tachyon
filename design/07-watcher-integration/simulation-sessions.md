---
title: Simulation Sessions
description: Server-side sandbox for speculative what-if analysis
keywords: [simulation, session, delta, speculation, sandbox, what-if, optimization]
related:
  - 07-watcher-integration/README.md
  - 05-operations/simulation.md
  - 01-schema/relationships/consumption.md
implements:
  - "Speculative planning"
  - "What-if analysis"
  - "Delta-based simulation"
section: watcher-integration
---

# Simulation Sessions

Simulation sessions provide a lightweight, server-side mechanism for "what-if" analysis that enables Watcher strategies to evaluate workload placement permutations without:

1. Storing the full model in client memory
2. Committing changes to the global graph
3. Creating full copies of the graph data

## Core Concepts

### Session Model

A simulation session is a transient entity that tracks speculative changes (deltas) against the global graph at a specific point in time.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Simulation Session                            │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  Session Properties                                          │    │
│  │  - id: UUID                                                  │    │
│  │  - base_generation: Global graph generation at creation      │    │
│  │  - created_at: Timestamp                                     │    │
│  │  - expires_at: TTL for automatic cleanup                     │    │
│  │  - audit_uuid: Optional link to Watcher audit                │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                              │                                       │
│                              ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  Delta Chain (ordered sequence of speculative changes)       │    │
│  │  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐             │    │
│  │  │Delta 1 │→ │Delta 2 │→ │Delta 3 │→ │Delta N │             │    │
│  │  │ MOVE   │  │ MOVE   │  │ MOVE   │  │  ...   │             │    │
│  │  └────────┘  └────────┘  └────────┘  └────────┘             │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

### Delta Types

Each delta records a single speculative operation:

| Delta Type | Description | Properties |
|------------|-------------|------------|
| `MOVE` | Migrate consumer between providers | `consumer_uuid`, `from_provider`, `to_provider`, `resource_changes` |
| `ALLOCATE` | Create new allocation | `consumer_uuid`, `provider_uuid`, `allocations` |
| `DEALLOCATE` | Remove allocation | `consumer_uuid`, `provider_uuid` |
| `RESIZE` | Modify allocation amounts | `consumer_uuid`, `provider_uuid`, `old_amounts`, `new_amounts` |

### Virtual State

Virtual state is computed by overlaying the delta chain on the global graph. This allows queries to see the "effective" state as if the speculative changes had been applied.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Virtual State View                            │
│                                                                      │
│  Global Graph State           Session Deltas                         │
│  ─────────────────           ──────────────                          │
│  Instance A → Node 1     +   [MOVE A: 1→2]     =   Instance A → Node 2
│  Instance B → Node 1     +   [MOVE B: 1→3]     =   Instance B → Node 3
│  Instance C → Node 2     +   (no change)       =   Instance C → Node 2
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## Graph Schema

### SimulationSession Node

```cypher
(:SimulationSession {
  id: 'session-uuid',           // Unique session identifier
  base_generation: 42,          // Global graph generation at creation
  created_at: datetime(),       // Session creation timestamp
  expires_at: datetime(),       // TTL for automatic cleanup
  audit_uuid: 'audit-uuid',     // Optional: Associated Watcher audit
  status: 'active'              // active, committed, rolled_back, expired
})
```

### SpeculativeDelta Node

```cypher
(:SpeculativeDelta {
  sequence: 1,                  // Order within session
  type: 'MOVE',                 // MOVE, ALLOCATE, DEALLOCATE, RESIZE
  consumer_uuid: 'instance-uuid',
  from_provider: 'node-1-uuid', // For MOVE/DEALLOCATE
  to_provider: 'node-2-uuid',   // For MOVE/ALLOCATE
  resource_changes: {           // Resource class → amount delta
    'VCPU': 4,
    'MEMORY_MB': 8192
  },
  created_at: datetime()
})
```

### Relationships

```cypher
// Session owns its deltas
(:SimulationSession)-[:HAS_DELTA]->(:SpeculativeDelta)

// Optional: Link session to audit
(:SimulationSession)-[:FOR_AUDIT]->(:Audit {uuid: 'audit-uuid'})
```

## Session Lifecycle

### 1. Create Session

Create a new simulation session anchored to the current global state:

```cypher
// Create session with current global generation
MATCH (global:GlobalState)
CREATE (s:SimulationSession {
  id: $session_id,
  base_generation: global.generation,
  created_at: datetime(),
  expires_at: datetime() + duration($ttl),
  audit_uuid: $audit_uuid,
  status: 'active'
})
RETURN s
```

### 2. Record Deltas

Add speculative changes to the session:

```cypher
// Record a MOVE delta
MATCH (s:SimulationSession {id: $session_id})
WHERE s.status = 'active'

// Get next sequence number
OPTIONAL MATCH (s)-[:HAS_DELTA]->(existing:SpeculativeDelta)
WITH s, COALESCE(max(existing.sequence), 0) + 1 AS next_seq

// Validate consumer exists and is currently at from_provider
MATCH (consumer:Consumer {uuid: $consumer_uuid})
      -[:CONSUMES]->(inv)
      <-[:HAS_INVENTORY]-(from_rp:ResourceProvider {uuid: $from_provider})

// Validate destination provider exists and has capacity
MATCH (to_rp:ResourceProvider {uuid: $to_provider})
      -[:HAS_INVENTORY]->(to_inv)

// Create the delta
CREATE (s)-[:HAS_DELTA]->(d:SpeculativeDelta {
  sequence: next_seq,
  type: 'MOVE',
  consumer_uuid: $consumer_uuid,
  from_provider: $from_provider,
  to_provider: $to_provider,
  resource_changes: $resource_amounts,
  created_at: datetime()
})

RETURN d
```

### 3. Query Virtual State

Query effective state with deltas applied:

```cypher
// Get effective placements for all consumers in a session's virtual state
MATCH (s:SimulationSession {id: $session_id})

// Get all consumers and their current providers
MATCH (consumer:Consumer)-[:CONSUMES]->(inv)<-[:HAS_INVENTORY]-(rp:ResourceProvider)

// Get all move deltas for this session
OPTIONAL MATCH (s)-[:HAS_DELTA]->(d:SpeculativeDelta)
WHERE d.type = 'MOVE' AND d.consumer_uuid = consumer.uuid

// Find the last move for each consumer
WITH consumer, rp, d
ORDER BY d.sequence DESC
WITH consumer, rp, head(collect(d)) AS last_move

// Compute effective provider
WITH consumer,
     CASE
       WHEN last_move IS NOT NULL THEN last_move.to_provider
       ELSE rp.uuid
     END AS effective_provider

RETURN consumer.uuid, effective_provider
```

### 4. Compute Metrics on Virtual State

Calculate optimization metrics considering deltas:

```cypher
// Compute resource utilization per provider in virtual state
MATCH (s:SimulationSession {id: $session_id})
MATCH (rp:ResourceProvider)-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(:ResourceClass {name: $resource_class})

// Get base allocations
OPTIONAL MATCH (inv)<-[base_alloc:CONSUMES]-(consumer:Consumer)

// Get deltas that affect this provider
OPTIONAL MATCH (s)-[:HAS_DELTA]->(d:SpeculativeDelta)
WHERE (d.to_provider = rp.uuid OR d.from_provider = rp.uuid)
  AND d.type = 'MOVE'

// Calculate effective usage
WITH rp, inv,
     // Base usage from existing allocations
     COALESCE(sum(base_alloc.used), 0) AS base_usage,
     // Collect incoming moves
     [delta IN collect(DISTINCT d) WHERE delta.to_provider = rp.uuid | delta.resource_changes[$resource_class]] AS incoming,
     // Collect outgoing moves
     [delta IN collect(DISTINCT d) WHERE delta.from_provider = rp.uuid | delta.resource_changes[$resource_class]] AS outgoing

WITH rp, inv,
     base_usage
     + REDUCE(s = 0, x IN incoming | s + COALESCE(x, 0))
     - REDUCE(s = 0, x IN outgoing | s + COALESCE(x, 0)) AS virtual_usage

// Calculate utilization
WITH rp, inv, virtual_usage,
     (inv.total - inv.reserved) * inv.allocation_ratio AS capacity

RETURN rp.uuid AS provider,
       virtual_usage,
       capacity,
       toFloat(virtual_usage) / capacity AS utilization
ORDER BY utilization DESC
```

### 5. Commit or Rollback

Either apply the deltas to the global graph or discard them:

```cypher
// Commit: Apply deltas to global graph (simplified)
MATCH (s:SimulationSession {id: $session_id})
WHERE s.status = 'active'

// Verify base generation hasn't changed (optimistic concurrency)
MATCH (global:GlobalState)
WHERE global.generation = s.base_generation

// Apply each delta in order
MATCH (s)-[:HAS_DELTA]->(d:SpeculativeDelta)
ORDER BY d.sequence

// For MOVE deltas: update allocations
FOREACH (delta IN collect(d) |
  // Apply move logic...
)

// Mark session as committed
SET s.status = 'committed',
    global.generation = global.generation + 1

RETURN s
```

```cypher
// Rollback: Discard session
MATCH (s:SimulationSession {id: $session_id})
WHERE s.status = 'active'

// Delete all deltas
MATCH (s)-[:HAS_DELTA]->(d:SpeculativeDelta)
DELETE d

// Mark session as rolled back
SET s.status = 'rolled_back'

RETURN s
```

## Optimization Queries

### Resource Balance Score

Calculate the standard deviation of resource utilization across providers:

```cypher
// Compute utilization standard deviation in virtual state
MATCH (s:SimulationSession {id: $session_id})
CALL {
  // ... (virtual usage calculation from above)
  RETURN provider, utilization
}
WITH collect(utilization) AS utils

// Calculate standard deviation
WITH utils,
     REDUCE(s = 0.0, u IN utils | s + u) / size(utils) AS mean
WITH utils, mean,
     REDUCE(s = 0.0, u IN utils | s + (u - mean) * (u - mean)) AS sum_sq

RETURN sqrt(sum_sq / size(utils)) AS std_deviation,
       mean AS avg_utilization
```

### Find Best Migration Target

Find providers with capacity for an instance in virtual state:

```cypher
// Find valid migration destinations considering session deltas
MATCH (s:SimulationSession {id: $session_id})
MATCH (instance:Consumer {uuid: $instance_uuid})

// Get instance resource requirements
MATCH (instance)-[alloc:CONSUMES]->(inv)-[:OF_CLASS]->(rc:ResourceClass)
WITH s, instance, collect({resource_class: rc.name, amount: alloc.used}) AS requirements

// Find providers with inventory
UNWIND requirements AS req
MATCH (rp:ResourceProvider)-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(:ResourceClass {name: req.resource_class})

// Exclude current provider
WHERE NOT (instance)-[:CONSUMES]->()<-[:HAS_INVENTORY]-(rp)

// Calculate virtual capacity (accounting for deltas)
OPTIONAL MATCH (s)-[:HAS_DELTA]->(d:SpeculativeDelta)
WHERE d.to_provider = rp.uuid OR d.from_provider = rp.uuid

// ... (virtual usage calculation)

WITH rp, req, virtual_usage, capacity
WHERE capacity - virtual_usage >= req.amount

// Return viable destinations
RETURN DISTINCT rp.uuid AS destination,
       capacity - virtual_usage AS available_capacity
ORDER BY available_capacity DESC
```

## Session Isolation

Multiple simulation sessions can exist concurrently without interference:

```
Session A (Audit 1)              Session B (Audit 2)
─────────────────               ─────────────────
MOVE inst-1: node-1 → node-2    MOVE inst-1: node-1 → node-3
MOVE inst-2: node-3 → node-4    MOVE inst-5: node-2 → node-1

Virtual State A:                 Virtual State B:
  inst-1 → node-2                  inst-1 → node-3
  inst-2 → node-4                  inst-5 → node-1

Global State (unchanged):
  inst-1 → node-1
  inst-2 → node-3
  inst-5 → node-2
```

## Conflict Detection

When committing a session, detect if the global state has changed:

```cypher
// Check for conflicts before commit
MATCH (s:SimulationSession {id: $session_id})
MATCH (global:GlobalState)

// Session is stale if global generation has advanced
WITH s, global,
     s.base_generation < global.generation AS is_stale

// Check specific conflicts: consumers that were touched in session
// but have since been modified in global graph
MATCH (s)-[:HAS_DELTA]->(d:SpeculativeDelta)
MATCH (consumer:Consumer {uuid: d.consumer_uuid})
WHERE consumer.generation > s.base_generation

WITH is_stale, collect(consumer.uuid) AS conflicting_consumers

RETURN is_stale,
       conflicting_consumers,
       size(conflicting_consumers) > 0 AS has_conflicts
```

## Automatic Cleanup

Sessions expire after their TTL to prevent resource leaks:

```cypher
// Clean up expired sessions (run periodically)
MATCH (s:SimulationSession)
WHERE s.expires_at < datetime()
  AND s.status = 'active'

// Delete associated deltas
MATCH (s)-[:HAS_DELTA]->(d:SpeculativeDelta)
DELETE d

// Mark as expired
SET s.status = 'expired'

RETURN count(s) AS expired_sessions
```

## Performance Considerations

### Delta Chain Length

Long delta chains can slow down virtual state queries. Recommendations:

- Limit sessions to ~1000 deltas maximum
- For complex optimization, use multiple sessions (e.g., per strategy phase)
- Consider "checkpointing" by committing intermediate states

### Index Strategy

Create indexes to support efficient delta lookups:

```cypher
// Index for session lookups
CREATE INDEX session_id IF NOT EXISTS FOR (s:SimulationSession) ON (s.id);

// Index for delta ordering
CREATE INDEX delta_sequence IF NOT EXISTS FOR (d:SpeculativeDelta) ON (d.sequence);

// Index for consumer-based delta lookups
CREATE INDEX delta_consumer IF NOT EXISTS FOR (d:SpeculativeDelta) ON (d.consumer_uuid);
```

### Memory vs. Disk

Session data can be configured for:

- **Memory-only**: Fastest, but lost on restart (suitable for short-lived audits)
- **Disk-backed**: Persisted, slower, but survives restarts (for long-running optimizations)
