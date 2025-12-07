---
title: Operations Overview
description: Runtime operations and infrastructure
keywords: [operations, claiming, indexes, telemetry, transactions]
related:
  - 04-queries/allocation-candidates.md
  - 01-schema/relationships/consumption.md
implements: []
section: operations
---

# Operations Overview

This section covers runtime operations for the Tachyon scheduling system.

## Contents

| File | Description |
|------|-------------|
| [resource-claiming.md](resource-claiming.md) | Allocation creation with optimistic concurrency |
| [indexes-constraints.md](indexes-constraints.md) | Neo4j schema setup for performance and integrity |
| [telemetry.md](telemetry.md) | Prometheus/Aetos hooks for real-time metrics |

## Operation Categories

### Resource Claiming
- Atomic allocation creation
- Optimistic concurrency with generations
- Multi-provider allocations
- Capacity validation

### Database Schema
- Uniqueness constraints
- Property existence constraints
- Performance indexes
- Full-text search indexes

### Telemetry Integration
- Prometheus metric endpoints
- Real-time utilization queries
- Threshold alerts
- Power-aware scheduling

