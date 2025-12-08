---
title: Schema Overview
description: Neo4j node and relationship definitions for Tachyon
keywords: [schema, nodes, relationships, graph, neo4j]
related:
  - 01-schema/nodes/resource-provider.md
  - 01-schema/relationships/hierarchy.md
implements: []
section: schema
---

# Schema Overview

This section defines all Neo4j node labels and relationship types in the Tachyon graph model.

## Graph Structure Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         TACHYON GRAPH SCHEMA                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  (:Project)<-[:OWNED_BY]-(:Consumer)-[:CREATED_BY]->(:User)                │
│                              │                                              │
│                              │[:CONSUMES {used}]                            │
│                              ▼                                              │
│  (:ResourceClass)<-[:OF_CLASS]-(:Inventory)<-[:HAS_INVENTORY]-┐            │
│                                                                │            │
│  (:Trait)<-[:HAS_TRAIT]-(:ResourceProvider)-[:MEMBER_OF]->(:Aggregate)     │
│                              │        │                        │            │
│                     [:PARENT_OF]  [:LOCATED_IN]      [:DEFINES_AZ]         │
│                              │        │                        │            │
│                              ▼        ▼                        ▼            │
│                    (:ResourceProvider) (:Cell)        (:AvailabilityZone)  │
│                                                                             │
│  (:ServerGroup)-[:HAS_MEMBER]->(:Consumer)                                 │
│                                                                             │
│  (:Flavor)-[:REQUIRES_TRAIT]->(:Trait)                                     │
│          -[:REQUIRES_RESOURCE]->(:ResourceClass)                           │
│                                                                             │
│  (:Aggregate)-[:TENANT_ALLOWED]->(:Project)                                │
│              -[:IMAGE_ALLOWED]->(:Image)                                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Node Types

| Label | Description | Key Properties |
|-------|-------------|----------------|
| `:ResourceProvider` | Source of resources | uuid, name, generation |
| `:Inventory` | Quantitative resources | total, reserved, allocation_ratio |
| `:Consumer` | Resource consumer | uuid, generation |
| `:ResourceClass` | Resource type | name, standard |
| `:Trait` | Qualitative capability | name, standard |
| `:Aggregate` | Provider grouping | uuid, name |
| `:Flavor` | Instance type | uuid, vcpus, memory_mb |
| `:ServerGroup` | Affinity policy | uuid, policy |

See [nodes/](nodes/) for detailed definitions.

## Relationship Types

| Relationship | From | To | Properties |
|--------------|------|-----|------------|
| `PARENT_OF` | ResourceProvider | ResourceProvider | - |
| `HAS_INVENTORY` | ResourceProvider | Inventory | - |
| `CONSUMES` | Consumer | Inventory | used, created_at |
| `HAS_TRAIT` | ResourceProvider | Trait | - |
| `MEMBER_OF` | ResourceProvider | Aggregate | - |
| `REQUIRES_TRAIT` | Flavor | Trait | constraint, weight |

See [relationships/](relationships/) for detailed definitions.
