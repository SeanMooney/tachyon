---
title: Constraint Types Overview
description: Constraint modeling for scheduling decisions
keywords: [constraints, traits, aggregates, server-groups, topology]
related:
  - 01-schema/relationships/scheduling.md
  - 04-queries/allocation-candidates.md
implements: []
section: constraints
---

# Constraint Types Overview

This section documents how scheduling constraints are modeled in the Tachyon graph.

## Constraint Categories

| Category | Files | Description |
|----------|-------|-------------|
| Trait Constraints | [trait-constraints.md](trait-constraints.md) | Required, forbidden, preferred, avoided traits |
| Aggregate Constraints | [aggregate-constraints.md](aggregate-constraints.md) | member_of, tenant/image isolation |
| Server Group Constraints | [server-group-constraints.md](server-group-constraints.md) | Affinity/anti-affinity policies |
| Topology Constraints | [topology-constraints.md](topology-constraints.md) | NUMA, PCI-NUMA affinity |
| Resource Group Constraints | [resource-group-constraints.md](resource-group-constraints.md) | group_policy, same_subtree |

## Constraint Type Summary

| Constraint | Type | Mechanism |
|------------|------|-----------|
| Required Traits | Hard | Filter - host must have trait |
| Forbidden Traits | Hard | Filter - host must not have trait |
| Preferred Traits | Soft | Weigher - boost score for trait |
| Avoided Traits | Soft | Weigher - penalize for trait |
| member_of Aggregate | Hard | Filter - host in aggregate |
| Tenant Isolation | Hard | Filter - project allowed |
| Image Isolation | Hard | Filter - image allowed |
| Server Group Affinity | Hard | Filter - same host as group |
| Server Group Anti-Affinity | Hard | Filter - different host |
| Soft Affinity | Soft | Weigher - prefer same host |
| Soft Anti-Affinity | Soft | Weigher - prefer spread |
| NUMA Affinity | Hard | Filter - resources from same NUMA |
| PCI-NUMA Affinity | Hard/Soft | Policy-based |
| group_policy=isolate | Hard | Filter - different providers |
| same_subtree | Hard | Filter - common ancestor |

## Hard vs Soft Constraints

**Hard constraints** (filters):
- Exclude hosts that don't meet criteria
- Applied first in scheduling pipeline
- No hosts = scheduling failure

**Soft constraints** (weighers):
- Influence host ranking
- Applied after filtering
- Never exclude hosts, only re-order

