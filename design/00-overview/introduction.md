---
title: Introduction and Goals
description: Purpose, why graph, goals, and scope of Tachyon
keywords: [introduction, goals, graph-database, neo4j, placement, scheduler]
related:
  - 00-overview/design-principles.md
  - 01-schema/README.md
implements: []
section: overview
---

# Introduction and Goals

## Purpose

Tachyon provides a graph-native approach to cloud resource scheduling that replaces the traditional relational model used by OpenStack Placement and Nova's scheduler.
By leveraging Neo4j's property graph database, Tachyon models the complex relationships between resource providers, consumers, traits, and constraints as first-class citizens rather than join tables.

## Why Graph?

Traditional scheduling systems struggle with:

1. **Complex Hierarchies**: Resource provider trees (compute nodes with NUMA nodes, PCI devices, vGPUs) require recursive queries in SQL
2. **Multi-dimensional Constraints**: NUMA affinity, PCI topology, and network connectivity form interconnected constraint graphs
3. **Aggregate Relationships**: Sharing providers, availability zones, and host aggregates create many-to-many relationships
4. **Traversal-Heavy Queries**: Finding allocation candidates requires walking trees while checking traits, inventories, and constraints

Neo4j excels at these patterns, providing:

- Native tree/forest traversal with variable-length paths
- Efficient relationship-based filtering
- Pattern matching for complex constraint validation
- ACID transactions with optimistic concurrency

## Goals

1. **Full Placement API Compatibility**: Support all existing Placement API operations through a compatibility layer
2. **Enhanced Scheduling Capabilities**: Enable graph-native optimizations not possible in relational systems
3. **Real-time Telemetry Integration**: Provide hooks for Prometheus/Aetos metrics to inform scheduling decisions
4. **Extensibility**: Allow custom constraints and policies without code changes using Neo4j's query language

## Scope

This design covers:

- All entities from OpenStack Placement (ResourceProvider, Inventory, Allocation, Consumer, ResourceClass, Trait, Aggregate)
- Nova scheduling concepts (Flavor, Image, ServerGroup, Cell, NUMA topology)
- Graph-native optimizations for common scheduling patterns
- Migration path from existing Placement deployments

See [reference/use-cases.md](../reference/use-cases.md) for the complete list of use cases this model must support.

