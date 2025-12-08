---
title: Design Principles
description: Core architectural decisions and patterns
keywords: [design, principles, optimistic-concurrency, generation, relationships]
related:
  - 00-overview/introduction.md
  - 01-schema/nodes/resource-provider.md
implements: []
section: overview
---

# Design Principles

## 1. Entities as Nodes, Relationships as First-Class Citizens

Unlike the relational model where many-to-many relationships require join tables, Neo4j represents relationships directly:

```
Relational:                          Graph:
┌─────────────────┐                  ┌───────────────────┐
│ resource_provider│                 │  :ResourceProvider │
├─────────────────┤                  │   uuid, name      │
│ id              │                  └─────────┬─────────┘
│ uuid            │     ──────►               │
│ parent_id (FK)  │                    [:PARENT_OF]
│ root_id (FK)    │                           │
└─────────────────┘                           ▼
                                     ┌───────────────────┐
                                     │  :ResourceProvider │
                                     │   (child)         │
                                     └───────────────────┘
```

## 2. Optimistic Concurrency via Generation

Both ResourceProvider and Consumer nodes maintain `generation` properties for optimistic locking. Any write operation must:

1. Read current generation
2. Include generation in update predicate
3. Increment generation on success
4. Fail if generation changed (concurrent modification)

## 3. Computed Properties at Query Time

Rather than storing derived values, Tachyon computes them during queries:

```cypher
// Capacity is computed, not stored
WITH inv, (inv.total - inv.reserved) * inv.allocation_ratio AS capacity
```

## 4. Relationship Properties for Allocations

Allocations are modeled as relationship properties rather than separate nodes, reducing graph traversal depth:

```
(:Consumer)-[:CONSUMES {used: 4, created_at: datetime()}]->(:Inventory)
```

## 5. Trait and Aggregate Optimization

Traits and aggregates use direct relationships rather than the `MISC_SHARES_VIA_AGGREGATE` pattern, enabling efficient graph queries:

```
// Instead of checking for trait + aggregate membership
(:ResourceProvider)-[:SHARES_RESOURCES]->(:ResourceProvider)
```
