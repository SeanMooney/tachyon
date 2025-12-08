---
title: Indexes and Constraints
description: Neo4j schema setup for performance and integrity
keywords: [index, constraint, uniqueness, performance, schema]
related:
  - 01-schema/nodes/resource-provider.md
implements:
  - "Data integrity"
  - "Query performance"
section: operations
---

# Indexes and Constraints

## Uniqueness Constraints

Uniqueness constraints ensure data integrity and automatically create indexes.

```cypher
// Resource Provider - UUID must be unique
CREATE CONSTRAINT rp_uuid_unique IF NOT EXISTS
FOR (rp:ResourceProvider)
REQUIRE rp.uuid IS UNIQUE;

// Resource Provider - Name must be unique
CREATE CONSTRAINT rp_name_unique IF NOT EXISTS
FOR (rp:ResourceProvider)
REQUIRE rp.name IS UNIQUE;

// Consumer - UUID must be unique
CREATE CONSTRAINT consumer_uuid_unique IF NOT EXISTS
FOR (c:Consumer)
REQUIRE c.uuid IS UNIQUE;

// Resource Class - Name must be unique
CREATE CONSTRAINT rc_name_unique IF NOT EXISTS
FOR (rc:ResourceClass)
REQUIRE rc.name IS UNIQUE;

// Trait - Name must be unique
CREATE CONSTRAINT trait_name_unique IF NOT EXISTS
FOR (t:Trait)
REQUIRE t.name IS UNIQUE;

// Aggregate - UUID must be unique
CREATE CONSTRAINT agg_uuid_unique IF NOT EXISTS
FOR (agg:Aggregate)
REQUIRE agg.uuid IS UNIQUE;

// Project - External ID must be unique
CREATE CONSTRAINT project_external_id_unique IF NOT EXISTS
FOR (p:Project)
REQUIRE p.external_id IS UNIQUE;

// User - External ID must be unique
CREATE CONSTRAINT user_external_id_unique IF NOT EXISTS
FOR (u:User)
REQUIRE u.external_id IS UNIQUE;

// Flavor - UUID must be unique
CREATE CONSTRAINT flavor_uuid_unique IF NOT EXISTS
FOR (f:Flavor)
REQUIRE f.uuid IS UNIQUE;

// Server Group - UUID must be unique
CREATE CONSTRAINT sg_uuid_unique IF NOT EXISTS
FOR (sg:ServerGroup)
REQUIRE sg.uuid IS UNIQUE;

// Availability Zone - Name must be unique
CREATE CONSTRAINT az_name_unique IF NOT EXISTS
FOR (az:AvailabilityZone)
REQUIRE az.name IS UNIQUE;

// Cell - UUID must be unique
CREATE CONSTRAINT cell_uuid_unique IF NOT EXISTS
FOR (cell:Cell)
REQUIRE cell.uuid IS UNIQUE;

// Consumer Type - Name must be unique
CREATE CONSTRAINT ct_name_unique IF NOT EXISTS
FOR (ct:ConsumerType)
REQUIRE ct.name IS UNIQUE;
```

## Property Existence Constraints

```cypher
// Resource Provider must have generation
CREATE CONSTRAINT rp_generation_exists IF NOT EXISTS
FOR (rp:ResourceProvider)
REQUIRE rp.generation IS NOT NULL;

// Consumer must have generation
CREATE CONSTRAINT consumer_generation_exists IF NOT EXISTS
FOR (c:Consumer)
REQUIRE c.generation IS NOT NULL;

// Inventory must have core properties
CREATE CONSTRAINT inv_total_exists IF NOT EXISTS
FOR (inv:Inventory)
REQUIRE inv.total IS NOT NULL;

CREATE CONSTRAINT inv_reserved_exists IF NOT EXISTS
FOR (inv:Inventory)
REQUIRE inv.reserved IS NOT NULL;

CREATE CONSTRAINT inv_allocation_ratio_exists IF NOT EXISTS
FOR (inv:Inventory)
REQUIRE inv.allocation_ratio IS NOT NULL;
```

## Performance Indexes

```cypher
// Resource Provider indexes
CREATE INDEX rp_disabled IF NOT EXISTS
FOR (rp:ResourceProvider)
ON (rp.disabled);

CREATE INDEX rp_hypervisor_type IF NOT EXISTS
FOR (rp:ResourceProvider)
ON (rp.hypervisor_type);

// Trait name index
CREATE INDEX trait_name IF NOT EXISTS
FOR (t:Trait)
ON (t.name);

// Resource Class name index
CREATE INDEX rc_name IF NOT EXISTS
FOR (rc:ResourceClass)
ON (rc.name);

// Consumer UUID index
CREATE INDEX consumer_uuid IF NOT EXISTS
FOR (c:Consumer)
ON (c.uuid);

// Aggregate UUID index
CREATE INDEX agg_uuid IF NOT EXISTS
FOR (agg:Aggregate)
ON (agg.uuid);

// Server Group policy index
CREATE INDEX sg_policy IF NOT EXISTS
FOR (sg:ServerGroup)
ON (sg.policy);

// Cell disabled index
CREATE INDEX cell_disabled IF NOT EXISTS
FOR (cell:Cell)
ON (cell.disabled);

// NUMA node cell_id index
CREATE INDEX numa_cell_id IF NOT EXISTS
FOR (numa:NUMANode)
ON (numa.cell_id);

// PCI device indexes
CREATE INDEX pci_address IF NOT EXISTS
FOR (pci:PCIDevice)
ON (pci.address);

CREATE INDEX pci_status IF NOT EXISTS
FOR (pci:PCIDevice)
ON (pci.status);

// Composite index for PCI vendor/product
CREATE INDEX pci_vendor_product IF NOT EXISTS
FOR (pci:PCIDevice)
ON (pci.vendor_id, pci.product_id);
```

## Full-Text Indexes

```cypher
// Full-text search on resource provider names
CREATE FULLTEXT INDEX rp_name_fulltext IF NOT EXISTS
FOR (rp:ResourceProvider)
ON EACH [rp.name];

// Full-text search on trait names
CREATE FULLTEXT INDEX trait_name_fulltext IF NOT EXISTS
FOR (t:Trait)
ON EACH [t.name];

// Full-text search on aggregate names
CREATE FULLTEXT INDEX agg_name_fulltext IF NOT EXISTS
FOR (agg:Aggregate)
ON EACH [agg.name];
```

## Relationship Property Indexes

```cypher
// Index on CONSUMES.used for allocation queries
CREATE INDEX consumes_used IF NOT EXISTS
FOR ()-[c:CONSUMES]-()
ON (c.used);

// Index on SHARES_RESOURCES.resource_classes
CREATE INDEX shares_rc IF NOT EXISTS
FOR ()-[s:SHARES_RESOURCES]-()
ON (s.resource_classes);
```

## Index Usage Guidelines

| Query Pattern | Recommended Index |
|--------------|-------------------|
| Find provider by UUID | `rp_uuid_unique` |
| Find provider by name | `rp_name_unique` |
| Filter disabled providers | `rp_disabled` |
| Find traits by name | `trait_name` |
| Find providers by hypervisor | `rp_hypervisor_type` |
| Find consumers by instance | `consumer_uuid` |
| Find aggregates by UUID | `agg_uuid` |
| Find PCI by address | `pci_address` |
| Find PCI by vendor/product | `pci_vendor_product` |

## Index Maintenance

```cypher
// Show all indexes
SHOW INDEXES;

// Show index usage statistics
CALL db.stats.retrieve('INDEX USAGE');

// Drop unused index
DROP INDEX index_name IF EXISTS;
```
