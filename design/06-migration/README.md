---
title: Migration Strategy
description: Placement API compatibility and migration
keywords: [migration, placement-api, compatibility, import]
related:
  - reference/placement-model.md
implements: []
section: migration
---

# Migration Strategy

This section documents the bidirectional mapping between OpenStack Placement API operations and Tachyon Neo4j operations to enable gradual migration.

## Contents

| File | Description |
|------|-------------|
| [api-mapping.md](api-mapping.md) | Placement API endpoint mapping to Tachyon |
| [data-migration.md](data-migration.md) | Scripts for migrating from Placement |

## Migration Approach

1. **Compatibility Layer**: Tachyon exposes Placement-compatible REST API
2. **Shadow Mode**: Run Tachyon alongside Placement, compare results
3. **Gradual Cutover**: Switch traffic incrementally
4. **Full Migration**: Decommission Placement

## Key Considerations

- All Placement API operations must be supported
- Generation-based concurrency must be preserved
- Trait and aggregate semantics must match exactly
- Custom resource classes must be migrated
