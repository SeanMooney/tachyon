---
title: Watcher Integration Overview
description: Integration with OpenStack Watcher for stateless optimization
keywords: [watcher, decision-engine, optimization, simulation, stateless, horizontal-scaling]
related:
  - 05-operations/simulation.md
  - 01-schema/nodes/consumer.md
  - 01-schema/nodes/resource-provider.md
implements:
  - "Watcher data model delegation"
  - "Stateless decision engine"
section: watcher-integration
---

# Watcher Integration Overview

This section describes how Tachyon integrates with OpenStack Watcher to provide a stateless, horizontally-scalable data model backend for the decision engine.

## Background

OpenStack Watcher is a resource optimization service that analyzes cloud workloads and generates action plans to improve resource utilization, thermal efficiency, or other optimization goals. Currently, Watcher's decision engine maintains an in-memory data model (using NetworkX) that:

1. Is populated by collectors that query Nova, Placement, and Cinder APIs
2. Is updated via notification handlers for real-time changes
3. Is used by strategies to simulate workload migrations and calculate optimization metrics
4. Cannot be shared across multiple decision engine instances

This architecture limits horizontal scalability and introduces memory constraints for large deployments.

## Integration Goals

### Stateless Decision Engine

By delegating the data model to Tachyon, decision engine instances become stateless workers that:

- Query Tachyon for current cloud state
- Perform simulations using server-side sandbox sessions
- Generate action plans without local state
- Scale horizontally without coordination

### Server-Side Simulation

Tachyon provides first-class support for "what-if" analysis through **Simulation Sessions**:

- Create lightweight sandbox sessions that track deltas against the global graph
- Simulate workload moves without committing to global state
- Compute optimization metrics on virtual states
- Evaluate multiple permutations efficiently
- Avoid full graph copies by using delta-based speculation

## Contents

| File | Description |
|------|-------------|
| [simulation-sessions.md](simulation-sessions.md) | Simulation session model with delta tracking |
| [watcher-model-mapping.md](watcher-model-mapping.md) | Mapping Watcher entities to Tachyon graph |

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Watcher Decision Engine (Stateless)               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐               │
│  │  Strategy A  │  │  Strategy B  │  │  Strategy C  │               │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘               │
│         │                 │                 │                        │
│         └────────────────┼────────────────┘                         │
│                          │                                           │
│                          ▼                                           │
│              ┌───────────────────────┐                               │
│              │  Tachyon Client API   │                               │
│              └───────────┬───────────┘                               │
└──────────────────────────│──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         Tachyon Service                              │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    Simulation Sessions                       │    │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐             │    │
│  │  │ Session A  │  │ Session B  │  │ Session C  │             │    │
│  │  │  (deltas)  │  │  (deltas)  │  │  (deltas)  │             │    │
│  │  └────────────┘  └────────────┘  └────────────┘             │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                              │                                       │
│                              ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    Global Graph (Neo4j)                      │    │
│  │  ResourceProviders, Consumers, Inventories, Allocations      │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

## Key Concepts

### Simulation Session

A lightweight, server-side sandbox that tracks speculative changes (deltas) against the global graph without modifying it. Sessions are:

- **Isolated**: Changes in one session don't affect others or the global state
- **Ephemeral**: Sessions expire after a configurable timeout
- **Efficient**: Only deltas are stored, not full copies of the graph
- **Queryable**: Virtual state queries overlay deltas on the global graph

### Delta Operations

Operations that record speculative changes within a session:

- **Move Consumer**: Simulate migrating an instance to a different provider
- **Add Consumer**: Simulate creating a new allocation
- **Remove Consumer**: Simulate deleting an allocation
- **Update Allocation**: Simulate resizing resource consumption

### Virtual State Queries

Queries that compute the effective state by layering session deltas over the global graph:

- Get effective resource usage per provider
- Calculate optimization metrics (balance, utilization variance)
- Find valid migration destinations considering speculative moves
- Evaluate constraint satisfaction on virtual state

## Benefits

| Aspect | Current (NetworkX) | With Tachyon |
|--------|-------------------|--------------|
| Scalability | Single instance | Horizontal scaling |
| Memory | Full model in RAM | Deltas only |
| Consistency | Periodic sync | Real-time via notifications |
| Simulation | Local mutations | Server-side sandboxes |
| Multi-strategy | Sequential | Parallel sessions |
| Persistence | None (rebuild on restart) | Durable graph storage |
