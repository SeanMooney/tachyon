---
title: Query Patterns Overview
description: Cypher query implementations for scheduling
keywords: [queries, cypher, filters, weighers, allocation-candidates]
related:
  - 03-constraints/README.md
  - 05-operations/resource-claiming.md
implements: []
section: queries
---

# Query Patterns Overview

This section provides production-ready Cypher queries for key scheduling operations, equivalent to Placement API and Nova scheduler functionality.

## Query Categories

| Category | Description |
|----------|-------------|
| [Allocation Candidates](allocation-candidates.md) | Core scheduling query (`GET /allocation_candidates`) |
| [Filters](filters/) | Hard constraint implementations |
| [Weighers](weighers/) | Soft constraint scoring |

## Scheduling Pipeline

```
┌─────────────────┐
│ Allocation      │  Core query: find providers with capacity
│ Candidates      │  Applies: traits, aggregates, resources
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Filters         │  Hard constraints: exclude non-matching hosts
│ (Hard)          │  ComputeFilter, ImageProperties, ServerGroup, etc.
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Weighers        │  Soft constraints: score and rank hosts
│ (Soft)          │  RAM, CPU, TraitAffinity, ServerGroupSoft, etc.
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Selection       │  Pick top host(s), create alternates
└─────────────────┘
```

## Filter Query Files

| File | Nova Equivalent |
|------|-----------------|
| [compute-filters.md](filters/compute-filters.md) | ComputeFilter, ImagePropertiesFilter |
| [topology-filters.md](filters/topology-filters.md) | NUMATopologyFilter, PciPassthroughFilter |
| [server-group-filters.md](filters/server-group-filters.md) | ServerGroupAffinityFilter, AntiAffinityFilter |
| [aggregate-filters.md](filters/aggregate-filters.md) | AggregateTenancy, AggregateImage, ExtraSpecs |

## Weigher Query Files

| File | Nova Equivalent |
|------|-----------------|
| [resource-weighers.md](weighers/resource-weighers.md) | RAMWeigher, CPUWeigher, DiskWeigher, IoOpsWeigher |
| [trait-affinity-weigher.md](weighers/trait-affinity-weigher.md) | (Tachyon-specific) TraitAffinityWeigher |
| [group-weighers.md](weighers/group-weighers.md) | ServerGroupSoftWeighers, CrossCellWeigher |

## Query Parameters

Common parameters used across queries:

| Parameter | Type | Description |
|-----------|------|-------------|
| `$resources` | List | `[{resource_class, amount}]` |
| `$required_traits` | List | Trait names to require |
| `$forbidden_traits` | List | Trait names to forbid |
| `$preferred_traits` | List | `[{name, weight}]` for weighing |
| `$avoided_traits` | List | `[{name, weight}]` for weighing |
| `$member_of` | List | Aggregate UUIDs (any match) |
| `$limit` | Integer | Max results to return |
