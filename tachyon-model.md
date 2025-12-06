# Tachyon Neo4j Data Model Reference

This document describes the complete data model for Tachyon, a Neo4j-backed
scheduling and resource management system designed to replace OpenStack Nova's
scheduler and Placement API.

## Table of Contents

1. [Introduction and Goals](#introduction-and-goals)
2. [Design Principles](#design-principles)
3. [Node Types](#node-types)
4. [Relationship Types](#relationship-types)
5. [Hierarchical Structures](#hierarchical-structures)
6. [Constraint Modeling](#constraint-modeling)
7. [Cypher Query Examples](#cypher-query-examples)
8. [Indexes and Constraints](#indexes-and-constraints)
9. [Telemetry Integration Hooks](#telemetry-integration-hooks)
10. [Placement API Migration Mapping](#placement-api-migration-mapping)
11. [Use Case Coverage Matrix](#use-case-coverage-matrix)

---

## Introduction and Goals

### Purpose

Tachyon provides a graph-native approach to cloud resource scheduling that
replaces the traditional relational model used by OpenStack Placement and
Nova's scheduler. By leveraging Neo4j's property graph database, Tachyon
models the complex relationships between resource providers, consumers,
traits, and constraints as first-class citizens rather than join tables.

### Why Graph?

Traditional scheduling systems struggle with:

1. **Complex Hierarchies**: Resource provider trees (compute nodes with NUMA
   nodes, PCI devices, vGPUs) require recursive queries in SQL
2. **Multi-dimensional Constraints**: NUMA affinity, PCI topology, and network
   connectivity form interconnected constraint graphs
3. **Aggregate Relationships**: Sharing providers, availability zones, and
   host aggregates create many-to-many relationships
4. **Traversal-Heavy Queries**: Finding allocation candidates requires walking
   trees while checking traits, inventories, and constraints

Neo4j excels at these patterns, providing:
- Native tree/forest traversal with variable-length paths
- Efficient relationship-based filtering
- Pattern matching for complex constraint validation
- ACID transactions with optimistic concurrency

### Goals

1. **Full Placement API Compatibility**: Support all existing Placement API
   operations through a compatibility layer
2. **Enhanced Scheduling Capabilities**: Enable graph-native optimizations
   not possible in relational systems
3. **Real-time Telemetry Integration**: Provide hooks for Prometheus/Aetos
   metrics to inform scheduling decisions
4. **Extensibility**: Allow custom constraints and policies without code
   changes using Neo4j's query language

### Scope

This data model covers:
- All entities from OpenStack Placement (ResourceProvider, Inventory,
  Allocation, Consumer, ResourceClass, Trait, Aggregate)
- Nova scheduling concepts (Flavor, Image, ServerGroup, Cell, NUMA topology)
- Graph-native optimizations for common scheduling patterns
- Migration path from existing Placement deployments

See [usecases.md](usecases.md) for the complete list of use cases this model
must support.

---

## Design Principles

### 1. Entities as Nodes, Relationships as First-Class Citizens

Unlike the relational model where many-to-many relationships require join
tables, Neo4j represents relationships directly:

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

### 2. Optimistic Concurrency via Generation

Both ResourceProvider and Consumer nodes maintain `generation` properties
for optimistic locking. Any write operation must:
1. Read current generation
2. Include generation in update predicate
3. Increment generation on success
4. Fail if generation changed (concurrent modification)

### 3. Computed Properties at Query Time

Rather than storing derived values, Tachyon computes them during queries:

```cypher
// Capacity is computed, not stored
WITH inv, (inv.total - inv.reserved) * inv.allocation_ratio AS capacity
```

### 4. Relationship Properties for Allocations

Allocations are modeled as relationship properties rather than separate
nodes, reducing graph traversal depth:

```
(:Consumer)-[:CONSUMES {used: 4, created_at: datetime()}]->(:Inventory)
```

### 5. Trait and Aggregate Optimization

Traits and aggregates use direct relationships rather than the
`MISC_SHARES_VIA_AGGREGATE` pattern, enabling efficient graph queries:

```
// Instead of checking for trait + aggregate membership
(:ResourceProvider)-[:SHARES_RESOURCES]->(:ResourceProvider)
```

---

## Node Types

This section defines all Neo4j node labels, their properties, and constraints.

### Placement Entity Mapping

| Placement Entity | Neo4j Label | Notes |
|------------------|-------------|-------|
| ResourceProvider | `:ResourceProvider` | Core entity, forms trees |
| Inventory | `:Inventory` | Per-provider, per-resource-class |
| Allocation | Relationship property | On `:CONSUMES` relationship |
| Consumer | `:Consumer` | Workload consuming resources |
| ResourceClass | `:ResourceClass` | VCPU, MEMORY_MB, CUSTOM_* |
| Trait | `:Trait` | Qualitative capabilities |
| PlacementAggregate | `:Aggregate` | Grouping mechanism |
| Project | `:Project` | Keystone project reference |
| User | `:User` | Keystone user reference |
| ConsumerType | `:ConsumerType` | Consumer categorization |

### Core Node Definitions

#### ResourceProvider

The fundamental entity representing a source of resources. Forms hierarchical
trees with parent-child relationships.

```
:ResourceProvider
  uuid:         String!    # External identifier (UUID format)
  name:         String!    # Human-readable name (unique, max 200 chars)
  generation:   Integer!   # Optimistic concurrency version (auto-increment)
  disabled:     Boolean    # Whether provider is disabled for scheduling
  created_at:   DateTime!
  updated_at:   DateTime!
```

**Constraints:**
- `uuid` must be unique across all ResourceProvider nodes
- `name` must be unique across all ResourceProvider nodes
- Root providers have no incoming `:PARENT_OF` relationship
- `generation` increments on inventory, trait, or aggregate changes

**Example:**

```cypher
CREATE (rp:ResourceProvider {
  uuid: 'c0f3dbf7-0e32-4d4f-8f7c-4c2a5c6e8d9b',
  name: 'compute-node-001',
  generation: 1,
  disabled: false,
  created_at: datetime(),
  updated_at: datetime()
})
```

#### Inventory

Quantitative resources available on a resource provider.

```
:Inventory
  total:            Integer!   # Total amount of resource
  reserved:         Integer!   # Amount reserved for other uses (default: 0)
  min_unit:         Integer!   # Minimum allocation unit (default: 1)
  max_unit:         Integer!   # Maximum allocation unit (default: total)
  step_size:        Integer!   # Allocation granularity (default: 1)
  allocation_ratio: Float!     # Overcommit ratio (default: 1.0)
  created_at:       DateTime!
  updated_at:       DateTime!
```

**Computed Properties (at query time):**
```cypher
// Capacity = (total - reserved) * allocation_ratio
WITH inv, (inv.total - inv.reserved) * inv.allocation_ratio AS capacity

// Usage = sum of all CONSUMES relationships
MATCH (inv)<-[c:CONSUMES]-()
WITH inv, sum(c.used) AS usage
```

**Constraints:**
- One Inventory node per (ResourceProvider, ResourceClass) pair
- `min_unit <= max_unit`
- `step_size > 0`
- `allocation_ratio > 0`
- Cannot delete Inventory with active allocations (CONSUMES relationships)

**Example:**

```cypher
MATCH (rp:ResourceProvider {uuid: $rp_uuid})
MATCH (rc:ResourceClass {name: 'VCPU'})
CREATE (rp)-[:HAS_INVENTORY]->(inv:Inventory {
  total: 64,
  reserved: 4,
  min_unit: 1,
  max_unit: 64,
  step_size: 1,
  allocation_ratio: 4.0,
  created_at: datetime(),
  updated_at: datetime()
})-[:OF_CLASS]->(rc)
```

#### Consumer

Entity that consumes resources (e.g., VM instance, volume, migration).

```
:Consumer
  uuid:        String!    # External identifier (often matches Nova instance UUID)
  generation:  Integer!   # Optimistic concurrency version
  created_at:  DateTime!
  updated_at:  DateTime!
```

**Lifecycle Rules:**
- Created implicitly when allocations are made
- Deleted when all allocations (CONSUMES relationships) are removed
- `generation` incremented on allocation changes

**Example:**

```cypher
CREATE (c:Consumer {
  uuid: 'a1b2c3d4-e5f6-7890-abcd-ef1234567890',
  generation: 1,
  created_at: datetime(),
  updated_at: datetime()
})
```

#### ResourceClass

Type of quantitative resource.

```
:ResourceClass
  name:       String!    # e.g., "VCPU", "MEMORY_MB", "CUSTOM_FPGA"
  id:         Integer    # Placement compatibility (0-9999 standard, 10000+ custom)
  standard:   Boolean!   # True for os-resource-classes, false for CUSTOM_*
  created_at: DateTime!
  updated_at: DateTime!
```

**Naming Rules:**
- Standard classes: synced from os-resource-classes library
- Custom classes: must start with "CUSTOM_" prefix
- Standard classes cannot be modified or deleted

**Standard Resource Classes:**
- Compute: `VCPU`, `PCPU`, `MEMORY_MB`, `MEM_ENCRYPTION_CONTEXT`
- Storage: `DISK_GB`
- Network: `SRIOV_NET_VF`, `NET_BW_EGR_KILOBIT_PER_SEC`, `NET_BW_IGR_KILOBIT_PER_SEC`,
  `NET_PACKET_RATE_KILOPACKET_PER_SEC`, `IPV4_ADDRESS`
- GPU: `VGPU`, `VGPU_DISPLAY_HEAD`, `PGPU`
- NUMA: `NUMA_SOCKET`, `NUMA_CORE`, `NUMA_THREAD`, `NUMA_MEMORY_MB`
- Accelerator: `FPGA`, `PCI_DEVICE`

**Example:**

```cypher
CREATE (rc:ResourceClass {
  name: 'CUSTOM_GPU_NVIDIA_A100',
  standard: false,
  created_at: datetime(),
  updated_at: datetime()
})
```

#### Trait

Qualitative characteristic of a resource provider.

```
:Trait
  name:       String!    # e.g., "HW_CPU_X86_AVX2", "CUSTOM_RAID"
  standard:   Boolean!   # True for os-traits, false for CUSTOM_*
  created_at: DateTime!
  updated_at: DateTime!
```

**Naming Rules:**
- Standard traits: synced from os-traits library
- Custom traits: must start with "CUSTOM_" prefix
- Standard traits cannot be deleted

**Trait Categories:**
- `COMPUTE_*`: Compute capabilities (architecture, features, status)
- `HW_*`: Hardware characteristics (CPU features, GPU APIs, NIC offloads)
- `STORAGE_*`: Storage characteristics (HDD, SSD)
- `MISC_*`: Miscellaneous (SHARES_VIA_AGGREGATE)
- `CUSTOM_*`: User-defined traits

**Example:**

```cypher
CREATE (t:Trait {
  name: 'COMPUTE_STATUS_DISABLED',
  standard: true,
  created_at: datetime(),
  updated_at: datetime()
})
```

#### Aggregate

Grouping mechanism for resource providers.

```
:Aggregate
  uuid:       String!    # External identifier
  name:       String     # Optional human-readable name
  created_at: DateTime!
  updated_at: DateTime!
```

**Purpose:**
- Logical grouping (availability zones, host aggregates)
- Enables shared resources via SHARES_RESOURCES relationship
- Filters via member_of queries
- Tenant isolation via TENANT_ALLOWED relationship

**Example:**

```cypher
CREATE (agg:Aggregate {
  uuid: 'agg-uuid-001',
  name: 'gpu-hosts',
  created_at: datetime(),
  updated_at: datetime()
})
```

#### Project

Keystone project reference.

```
:Project
  external_id: String!   # Keystone project UUID
  created_at:  DateTime!
  updated_at:  DateTime!
```

#### User

Keystone user reference.

```
:User
  external_id: String!   # Keystone user UUID
  created_at:  DateTime!
  updated_at:  DateTime!
```

#### ConsumerType

Categorization for consumers.

```
:ConsumerType
  name:       String!    # e.g., "INSTANCE", "MIGRATION", "VOLUME"
  created_at: DateTime!
  updated_at: DateTime!
```

### Nova-Specific Node Definitions

#### Flavor

Instance type defining compute, memory, and storage capacity.

```
:Flavor
  uuid:          String!     # Internal UUID
  flavorid:      String!     # External ID (e.g., "m1.small")
  name:          String!     # Display name
  memory_mb:     Integer!    # RAM in MB
  vcpus:         Integer!    # vCPU count
  root_gb:       Integer!    # Root disk size in GB
  ephemeral_gb:  Integer!    # Ephemeral disk size in GB
  swap_mb:       Integer!    # Swap size in MB
  rxtx_factor:   Float       # Network I/O multiplier
  vcpu_weight:   Integer     # CPU scheduling weight
  disabled:      Boolean!    # Disabled flag
  is_public:     Boolean!    # Public vs private
  description:   String      # Flavor description
  created_at:    DateTime!
  updated_at:    DateTime!
```

**Extra Specs Modeling:**

Extra specs are modeled as relationships to dedicated nodes:

```cypher
(:Flavor)-[:HAS_EXTRA_SPEC]->(:ExtraSpec {
  namespace: 'hw',
  key: 'cpu_policy',
  value: 'dedicated'
})
```

Or as a map property for simple cases:
```cypher
(:Flavor {
  extra_specs: {
    'hw:cpu_policy': 'dedicated',
    'hw:numa_nodes': '2',
    'trait:HW_CPU_X86_AVX2': 'required'
  }
})
```

**Trait Extra Specs Syntax:**

| Extra Spec Pattern | Constraint Type | Description |
|-------------------|-----------------|-------------|
| `trait:TRAIT_NAME=required` | Hard | Provider must have trait |
| `trait:TRAIT_NAME=forbidden` | Hard | Provider must not have trait |
| `trait:TRAIT_NAME=preferred` | Soft | Prefer providers with trait |
| `trait:TRAIT_NAME=preferred:2.0` | Soft (weighted) | Prefer with weight 2.0 |
| `trait:TRAIT_NAME=avoided` | Soft | Avoid providers with trait |
| `trait:TRAIT_NAME=avoided:1.5` | Soft (weighted) | Avoid with weight 1.5 |

Example flavor with mixed trait constraints:
```cypher
(:Flavor {
  extra_specs: {
    'trait:HW_CPU_X86_AVX2': 'required',           // Must have AVX2
    'trait:COMPUTE_STATUS_DISABLED': 'forbidden',  // Must not be disabled
    'trait:STORAGE_DISK_SSD': 'preferred:2.0',     // Prefer SSD (weight 2.0)
    'trait:CUSTOM_OVERLOADED': 'avoided:3.0'       // Avoid overloaded (weight 3.0)
  }
})
```

#### Image

Glance image properties for scheduling.

```
:Image
  uuid:         String!      # Glance image UUID
  name:         String       # Image name
  disk_format:  String       # qcow2, raw, iso, etc.
  properties:   Map          # Image properties as key-value map
  created_at:   DateTime!
  updated_at:   DateTime!
```

**Key Properties for Scheduling:**
- `hw_architecture`: x86_64, aarch64, ppc64le
- `img_hv_type`: kvm, qemu, xen, vmware
- `hw_vm_mode`: hvm, xen
- `os_type`: linux, windows
- `os_distro`: ubuntu, centos, windows

#### ServerGroup

Affinity/anti-affinity policies for instances.

```
:ServerGroup
  uuid:       String!       # External identifier
  name:       String        # Group name
  policy:     String!       # affinity, anti-affinity, soft-affinity, soft-anti-affinity
  rules:      Map           # Policy rules (e.g., {max_server_per_host: 3})
  created_at: DateTime!
  updated_at: DateTime!
```

#### AvailabilityZone

Availability zone grouping.

```
:AvailabilityZone
  name:       String!       # AZ name (e.g., "nova", "az1")
  created_at: DateTime!
  updated_at: DateTime!
```

#### Cell

Nova cell structure.

```
:Cell
  uuid:       String!       # Cell UUID
  name:       String!       # Cell name
  disabled:   Boolean!      # Whether cell is disabled for scheduling
  created_at: DateTime!
  updated_at: DateTime!
```

#### NUMANode

NUMA topology node (child of ResourceProvider).

```
:NUMANode
  cell_id:      Integer!    # NUMA cell ID
  cpuset:       List<Int>!  # CPU IDs in this cell
  memory_mb:    Integer!    # Total memory in MB
  hugepages:    Map         # Hugepage configuration {size_kb: count}
  created_at:   DateTime!
  updated_at:   DateTime!
```

#### PCIDevice

PCI device available for passthrough.

```
:PCIDevice
  address:      String!     # PCI address (0000:04:00.1)
  vendor_id:    String!     # PCI vendor ID (e.g., "8086")
  product_id:   String!     # PCI product ID (e.g., "10ed")
  dev_type:     String!     # type-PCI, type-PF, type-VF
  numa_node:    Integer     # NUMA affinity
  status:       String!     # available, claimed, allocated, unavailable
  created_at:   DateTime!
  updated_at:   DateTime!
```

---

## Relationship Types

This section defines all relationship types in the Tachyon graph model.

### Core Relationships Overview

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

### Relationship Definitions

#### PARENT_OF

Models resource provider tree hierarchy.

```
(:ResourceProvider)-[:PARENT_OF]->(:ResourceProvider)
```

**Properties:** None

**Semantics:**
- Direction: Parent → Child
- A provider with no incoming PARENT_OF is a root provider
- A provider can have at most one parent
- A provider can have multiple children
- No cycles allowed

**Example:**

```cypher
// Create parent-child relationship
MATCH (parent:ResourceProvider {uuid: $parent_uuid})
MATCH (child:ResourceProvider {uuid: $child_uuid})
CREATE (parent)-[:PARENT_OF]->(child)
```

**Traversal:**

```cypher
// Find root provider for any node
MATCH (rp:ResourceProvider {uuid: $uuid})
MATCH path = (root:ResourceProvider)-[:PARENT_OF*0..]->(rp)
WHERE NOT ()-[:PARENT_OF]->(root)
RETURN root

// Find all descendants
MATCH (root:ResourceProvider {uuid: $uuid})
MATCH (root)-[:PARENT_OF*]->(descendant)
RETURN descendant
```

#### HAS_INVENTORY

Links resource provider to its inventory.

```
(:ResourceProvider)-[:HAS_INVENTORY]->(:Inventory)
```

**Properties:** None

**Constraints:**
- Each ResourceProvider can have multiple inventories (one per ResourceClass)
- Inventory must also have OF_CLASS relationship to ResourceClass

#### OF_CLASS

Links inventory to its resource class.

```
(:Inventory)-[:OF_CLASS]->(:ResourceClass)
```

**Properties:** None

**Constraints:**
- Each Inventory has exactly one OF_CLASS relationship
- Combined with HAS_INVENTORY, forms unique (Provider, Class) pairs

#### HAS_TRAIT

Associates traits with resource providers.

```
(:ResourceProvider)-[:HAS_TRAIT]->(:Trait)
```

**Properties:** None

**Semantics:**
- A provider can have multiple traits
- Traits on root provider apply to scheduling decisions
- Traits on nested providers indicate specific capabilities

#### MEMBER_OF

Associates resource providers with aggregates.

```
(:ResourceProvider)-[:MEMBER_OF]->(:Aggregate)
```

**Properties:** None

**Semantics:**
- A provider can be member of multiple aggregates
- Used for AZ mapping, host aggregates, tenant isolation

#### CONSUMES

Records resource consumption by a consumer.

```
(:Consumer)-[:CONSUMES {used, created_at, updated_at}]->(:Inventory)
```

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| used | Integer! | Amount of resource consumed |
| created_at | DateTime! | When allocation was created |
| updated_at | DateTime! | When allocation was last modified |

**Constraints:**
- `used >= inventory.min_unit`
- `used <= inventory.max_unit`
- `used % inventory.step_size == 0`
- Sum of all CONSUMES.used on an Inventory must not exceed capacity

**Example:**

```cypher
// Create allocation
MATCH (c:Consumer {uuid: $consumer_uuid})
MATCH (rp:ResourceProvider {uuid: $rp_uuid})-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(:ResourceClass {name: 'VCPU'})
CREATE (c)-[:CONSUMES {
  used: 4,
  created_at: datetime(),
  updated_at: datetime()
}]->(inv)
```

#### OWNED_BY

Links consumer to its owning project.

```
(:Consumer)-[:OWNED_BY]->(:Project)
```

**Properties:** None

#### CREATED_BY

Links consumer to the user who created it.

```
(:Consumer)-[:CREATED_BY]->(:User)
```

**Properties:** None

#### OF_TYPE

Links consumer to its type.

```
(:Consumer)-[:OF_TYPE]->(:ConsumerType)
```

**Properties:** None

#### DEFINES_AZ

Links aggregate to an availability zone.

```
(:Aggregate)-[:DEFINES_AZ]->(:AvailabilityZone)
```

**Properties:** None

**Semantics:**
- An aggregate can define at most one AZ
- Multiple aggregates can define the same AZ
- Used for map_az_to_placement_aggregate functionality

#### LOCATED_IN

Links resource provider to its cell.

```
(:ResourceProvider)-[:LOCATED_IN]->(:Cell)
```

**Properties:** None

### Nova-Specific Relationships

#### HAS_MEMBER

Links server group to its member consumers.

```
(:ServerGroup)-[:HAS_MEMBER]->(:Consumer)
```

**Properties:** None

**Semantics:**
- Enforces affinity/anti-affinity policies
- Consumer can be member of one server group

#### SCHEDULED_ON

Links consumer to its hosting resource provider.

```
(:Consumer)-[:SCHEDULED_ON]->(:ResourceProvider)
```

**Properties:**
| Property | Type | Description |
|----------|------|-------------|
| host | String | Compute host name |
| node | String | Hypervisor node name |
| scheduled_at | DateTime | When scheduled |

**Semantics:**
- Represents where instance is running
- Used for affinity/anti-affinity evaluation

#### REQUIRES_TRAIT

Links flavor to trait requirements with hard or soft constraints.

```
(:Flavor)-[:REQUIRES_TRAIT {constraint, weight}]->(:Trait)
```

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| constraint | String! | Constraint type (see below) |
| weight | Float | Weight for soft constraints (default: 1.0) |

**Constraint Types:**

| Constraint | Type | Behavior |
|------------|------|----------|
| `required` | Hard | Provider MUST have trait (filter) |
| `forbidden` | Hard | Provider MUST NOT have trait (filter) |
| `preferred` | Soft | Prefer providers WITH trait (weigher, positive score) |
| `avoided` | Soft | Prefer providers WITHOUT trait (weigher, negative score) |

**Soft Constraint Semantics:**
- `preferred`: Hosts with the trait receive a positive weight boost
- `avoided`: Hosts with the trait receive a negative weight penalty
- Soft constraints never exclude hosts, only influence ranking
- Multiple soft traits combine additively
- Weight property allows fine-tuning relative importance

**Example:**

```cypher
// Required trait (hard constraint)
CREATE (f)-[:REQUIRES_TRAIT {constraint: 'required'}]->(t:Trait {name: 'HW_CPU_X86_AVX2'})

// Forbidden trait (hard constraint)
CREATE (f)-[:REQUIRES_TRAIT {constraint: 'forbidden'}]->(t:Trait {name: 'COMPUTE_STATUS_DISABLED'})

// Preferred trait (soft constraint - favor hosts with SSD)
CREATE (f)-[:REQUIRES_TRAIT {constraint: 'preferred', weight: 2.0}]->(t:Trait {name: 'STORAGE_DISK_SSD'})

// Avoided trait (soft constraint - avoid hosts in maintenance window)
CREATE (f)-[:REQUIRES_TRAIT {constraint: 'avoided', weight: 1.5}]->(t:Trait {name: 'CUSTOM_MAINTENANCE_WINDOW'})
```

#### REQUIRES_RESOURCE

Links flavor to resource requirements.

```
(:Flavor)-[:REQUIRES_RESOURCE {amount, group}]->(:ResourceClass)
```

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| amount | Integer! | Required amount |
| group | String | Optional resource group name |

### Graph-Native Optimization Relationships

#### SHARES_RESOURCES

Direct relationship for sharing providers (replaces MISC_SHARES_VIA_AGGREGATE pattern).

```
(:ResourceProvider)-[:SHARES_RESOURCES]->(:ResourceProvider)
```

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| resource_classes | List<String> | Which resource classes are shared |

**Semantics:**
- Source provider shares its resources with target providers
- More efficient than aggregate-based sharing queries
- Created when provider has MISC_SHARES_VIA_AGGREGATE trait

**Example:**

```cypher
// Storage provider shares DISK_GB with compute nodes
MATCH (storage:ResourceProvider {name: 'shared-storage-pool'})
MATCH (compute:ResourceProvider)
WHERE compute.name STARTS WITH 'compute-'
  AND (storage)-[:MEMBER_OF]->(:Aggregate)<-[:MEMBER_OF]-(compute)
CREATE (storage)-[:SHARES_RESOURCES {resource_classes: ['DISK_GB']}]->(compute)
```

#### NUMA_AFFINITY

Links PCI device to NUMA node for affinity.

```
(:PCIDevice)-[:NUMA_AFFINITY]->(:NUMANode)
```

**Properties:** None

**Semantics:**
- PCI device is physically attached to specific NUMA node
- Used for PCI-NUMA affinity policy enforcement

#### TENANT_ALLOWED

Links aggregate to allowed tenant(s).

```
(:Aggregate)-[:TENANT_ALLOWED]->(:Project)
```

**Properties:** None

**Semantics:**
- Replaces `filter_tenant_id` aggregate metadata
- Hosts in aggregate only schedulable by allowed tenants
- Graph-native alternative enables efficient tenant isolation queries

#### IMAGE_ALLOWED

Links aggregate to allowed images.

```
(:Aggregate)-[:IMAGE_ALLOWED]->(:Image)
```

**Properties:** None

**Semantics:**
- Replaces image property matching in aggregate metadata
- Hosts in aggregate only schedulable for allowed images

#### HAS_PCI_DEVICE

Links resource provider to PCI devices.

```
(:ResourceProvider)-[:HAS_PCI_DEVICE]->(:PCIDevice)
```

**Properties:** None

#### PCI_PARENT_OF

Links PCI physical function to virtual functions.

```
(:PCIDevice)-[:PCI_PARENT_OF]->(:PCIDevice)
```

**Properties:** None

**Semantics:**
- Source is Physical Function (PF)
- Target is Virtual Function (VF)
- Used for SR-IOV modeling

#### HAS_NUMA_NODE

Links resource provider to NUMA nodes.

```
(:ResourceProvider)-[:HAS_NUMA_NODE]->(:NUMANode)
```

**Properties:** None

### Relationship Cardinality Summary

| Relationship | From | To | Cardinality |
|--------------|------|-----|-------------|
| PARENT_OF | ResourceProvider | ResourceProvider | 0..1 : 0..N |
| HAS_INVENTORY | ResourceProvider | Inventory | 1 : 0..N |
| OF_CLASS | Inventory | ResourceClass | N : 1 |
| HAS_TRAIT | ResourceProvider | Trait | 0..N : 0..N |
| MEMBER_OF | ResourceProvider | Aggregate | 0..N : 0..N |
| CONSUMES | Consumer | Inventory | 0..N : 0..N |
| OWNED_BY | Consumer | Project | N : 1 |
| CREATED_BY | Consumer | User | N : 1 |
| OF_TYPE | Consumer | ConsumerType | N : 0..1 |
| DEFINES_AZ | Aggregate | AvailabilityZone | N : 0..1 |
| LOCATED_IN | ResourceProvider | Cell | N : 1 |
| HAS_MEMBER | ServerGroup | Consumer | 1 : 0..N |
| SCHEDULED_ON | Consumer | ResourceProvider | 0..1 : 0..N |
| SHARES_RESOURCES | ResourceProvider | ResourceProvider | 0..N : 0..N |
| TENANT_ALLOWED | Aggregate | Project | 0..N : 0..N |
| IMAGE_ALLOWED | Aggregate | Image | 0..N : 0..N |

---

## Hierarchical Structures

This section documents the graph patterns for modeling complex hierarchical
relationships in Tachyon.

### Resource Provider Trees

Resource providers form forest structures (multiple trees) where each tree
represents a compute host with its nested resources.

#### Basic Tree Structure

```
┌─────────────────────────────────────────────────────────────────┐
│                    COMPUTE HOST TREE                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  (:ResourceProvider {name: "compute-001"})  ◄─── Root Provider  │
│       │                                                         │
│       ├──[:PARENT_OF]──► (:ResourceProvider {name: "numa-0"})   │
│       │                       │                                 │
│       │                       ├──[:PARENT_OF]──► (:RP "pf-0")   │
│       │                       │                    │            │
│       │                       │        ┌───────────┴───────┐    │
│       │                       │        ▼                   ▼    │
│       │                       │   (:RP "vf-0-0")    (:RP "vf-0-1")
│       │                       │                                 │
│       │                       └──[:PARENT_OF]──► (:RP "pf-1")   │
│       │                                                         │
│       └──[:PARENT_OF]──► (:ResourceProvider {name: "numa-1"})   │
│                               │                                 │
│                               └──[:PARENT_OF]──► (:RP "gpu-0")  │
│                                                    │            │
│                                        ┌───────────┴───────┐    │
│                                        ▼                   ▼    │
│                                  (:RP "vgpu-0")    (:RP "vgpu-1")│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### Tree Creation Pattern

```cypher
// Create compute host (root provider)
CREATE (root:ResourceProvider {
  uuid: randomUUID(),
  name: 'compute-001',
  generation: 1,
  disabled: false,
  created_at: datetime(),
  updated_at: datetime()
})

// Create NUMA node 0 as child
CREATE (numa0:ResourceProvider {
  uuid: randomUUID(),
  name: 'compute-001_numa_0',
  generation: 1,
  created_at: datetime(),
  updated_at: datetime()
})
CREATE (root)-[:PARENT_OF]->(numa0)

// Create NUMA node 1 as child
CREATE (numa1:ResourceProvider {
  uuid: randomUUID(),
  name: 'compute-001_numa_1',
  generation: 1,
  created_at: datetime(),
  updated_at: datetime()
})
CREATE (root)-[:PARENT_OF]->(numa1)
```

#### Root Provider Queries

```cypher
// Find root provider for any provider in tree
MATCH (rp:ResourceProvider {uuid: $uuid})
MATCH path = (root:ResourceProvider)-[:PARENT_OF*0..]->(rp)
WHERE NOT ()-[:PARENT_OF]->(root)
RETURN root

// Alternative: Follow PARENT_OF backwards
MATCH (rp:ResourceProvider {uuid: $uuid})
OPTIONAL MATCH (rp)<-[:PARENT_OF*]-(root)
WHERE NOT ()-[:PARENT_OF]->(root)
RETURN COALESCE(root, rp) AS root
```

#### Tree Traversal Queries

```cypher
// Get entire tree from root
MATCH (root:ResourceProvider {uuid: $root_uuid})
OPTIONAL MATCH (root)-[:PARENT_OF*]->(descendant)
RETURN root, collect(descendant) AS descendants

// Get subtree from any node
MATCH (node:ResourceProvider {uuid: $uuid})
MATCH path = (node)-[:PARENT_OF*0..]->(descendant)
RETURN node, collect(DISTINCT descendant) AS subtree

// Find depth of provider in tree
MATCH (rp:ResourceProvider {uuid: $uuid})
MATCH path = (root)-[:PARENT_OF*0..]->(rp)
WHERE NOT ()-[:PARENT_OF]->(root)
RETURN length(path) AS depth
```

### NUMA Topology

NUMA topology is modeled as nested resource providers with specialized
NUMANode labels and properties.

#### NUMA Tree Structure

```
(:ResourceProvider:ComputeHost)
    │
    ├──[:PARENT_OF]──► (:ResourceProvider:NUMANode {cell_id: 0})
    │                       │
    │                       ├── Inventories: VCPU, MEMORY_MB, PCPU
    │                       │
    │                       └── Properties:
    │                             cpuset: [0,1,2,3,4,5,6,7]
    │                             pcpuset: [0,1,2,3]
    │                             memory_mb: 65536
    │                             siblings: [[0,8],[1,9],[2,10],[3,11],...]
    │                             hugepages: {2048: 1024, 1048576: 4}
    │
    └──[:PARENT_OF]──► (:ResourceProvider:NUMANode {cell_id: 1})
                            │
                            └── Properties:
                                  cpuset: [8,9,10,11,12,13,14,15]
                                  ...
```

#### NUMA Creation Pattern

```cypher
// Create compute host with NUMA topology
CREATE (host:ResourceProvider:ComputeHost {
  uuid: randomUUID(),
  name: 'compute-001',
  generation: 1,
  created_at: datetime(),
  updated_at: datetime()
})

// Create NUMA node 0
CREATE (numa0:ResourceProvider:NUMANode {
  uuid: randomUUID(),
  name: 'compute-001_numa_0',
  cell_id: 0,
  cpuset: [0,1,2,3,4,5,6,7],
  pcpuset: [0,1,2,3],
  memory_mb: 65536,
  siblings: [[0,8],[1,9],[2,10],[3,11],[4,12],[5,13],[6,14],[7,15]],
  hugepages: {2048: 1024, 1048576: 4},
  generation: 1,
  created_at: datetime(),
  updated_at: datetime()
})
CREATE (host)-[:PARENT_OF]->(numa0)

// Add NUMA node inventories
MATCH (rc_vcpu:ResourceClass {name: 'VCPU'})
MATCH (rc_mem:ResourceClass {name: 'MEMORY_MB'})
MATCH (rc_pcpu:ResourceClass {name: 'PCPU'})

CREATE (numa0)-[:HAS_INVENTORY]->(inv_vcpu:Inventory {
  total: 8,
  reserved: 0,
  min_unit: 1,
  max_unit: 8,
  step_size: 1,
  allocation_ratio: 1.0,
  created_at: datetime(),
  updated_at: datetime()
})-[:OF_CLASS]->(rc_vcpu)

CREATE (numa0)-[:HAS_INVENTORY]->(inv_mem:Inventory {
  total: 65536,
  reserved: 512,
  min_unit: 1,
  max_unit: 65536,
  step_size: 1,
  allocation_ratio: 1.0,
  created_at: datetime(),
  updated_at: datetime()
})-[:OF_CLASS]->(rc_mem)
```

#### NUMA Scheduling Query

```cypher
// Find NUMA nodes that can satisfy CPU and memory requirements
MATCH (host:ResourceProvider)-[:PARENT_OF]->(numa:NUMANode)
MATCH (numa)-[:HAS_INVENTORY]->(vcpu_inv)-[:OF_CLASS]->(:ResourceClass {name: 'VCPU'})
MATCH (numa)-[:HAS_INVENTORY]->(mem_inv)-[:OF_CLASS]->(:ResourceClass {name: 'MEMORY_MB'})

// Calculate available resources
OPTIONAL MATCH (vcpu_inv)<-[vc:CONSUMES]-()
OPTIONAL MATCH (mem_inv)<-[mc:CONSUMES]-()

WITH host, numa, vcpu_inv, mem_inv,
     (vcpu_inv.total - vcpu_inv.reserved) * vcpu_inv.allocation_ratio AS vcpu_capacity,
     COALESCE(sum(vc.used), 0) AS vcpu_used,
     (mem_inv.total - mem_inv.reserved) * mem_inv.allocation_ratio AS mem_capacity,
     COALESCE(sum(mc.used), 0) AS mem_used

WHERE vcpu_capacity - vcpu_used >= $required_vcpus
  AND mem_capacity - mem_used >= $required_memory_mb

RETURN host, numa, 
       vcpu_capacity - vcpu_used AS available_vcpus,
       mem_capacity - mem_used AS available_memory_mb
```

### PCI Device Hierarchy

PCI devices form their own hierarchy with Physical Functions (PFs) as parents
of Virtual Functions (VFs).

#### PCI Tree Structure

```
(:ResourceProvider:ComputeHost)
    │
    ├──[:PARENT_OF]──► (:ResourceProvider:NUMANode {cell_id: 0})
    │                       │
    │                       └──[:PARENT_OF]──► (:ResourceProvider:PCIPF)
    │                                              │
    │                                              ├── address: "0000:04:00.0"
    │                                              ├── vendor_id: "15b3"
    │                                              ├── product_id: "1017"
    │                                              │
    │                                              ├──[:PARENT_OF]──► (:RP:PCIVF)
    │                                              │                    address: "0000:04:00.1"
    │                                              │
    │                                              ├──[:PARENT_OF]──► (:RP:PCIVF)
    │                                              │                    address: "0000:04:00.2"
    │                                              │
    │                                              └──[:PARENT_OF]──► (:RP:PCIVF)
    │                                                                   address: "0000:04:00.3"
    │
    └──[:HAS_PCI_DEVICE]──► (:PCIDevice)  // Flat reference for quick lookup
```

#### PCI Device Creation Pattern

```cypher
// Create PF resource provider under NUMA node
MATCH (numa:ResourceProvider:NUMANode {name: 'compute-001_numa_0'})

CREATE (pf:ResourceProvider:PCIPF {
  uuid: randomUUID(),
  name: 'compute-001_0000:04:00.0',
  address: '0000:04:00.0',
  vendor_id: '15b3',
  product_id: '1017',
  generation: 1,
  created_at: datetime(),
  updated_at: datetime()
})
CREATE (numa)-[:PARENT_OF]->(pf)

// Add trait for physnet
MERGE (physnet:Trait {name: 'CUSTOM_PHYSNET_PROVIDER1'})
CREATE (pf)-[:HAS_TRAIT]->(physnet)

// Create VF resource providers
UNWIND range(1, 8) AS vf_num
CREATE (vf:ResourceProvider:PCIVF {
  uuid: randomUUID(),
  name: 'compute-001_0000:04:00.' + toString(vf_num),
  address: '0000:04:00.' + toString(vf_num),
  generation: 1,
  created_at: datetime(),
  updated_at: datetime()
})
CREATE (pf)-[:PARENT_OF]->(vf)

// Add SRIOV_NET_VF inventory to each VF
WITH vf
MATCH (rc:ResourceClass {name: 'SRIOV_NET_VF'})
CREATE (vf)-[:HAS_INVENTORY]->(inv:Inventory {
  total: 1,
  reserved: 0,
  min_unit: 1,
  max_unit: 1,
  step_size: 1,
  allocation_ratio: 1.0,
  created_at: datetime(),
  updated_at: datetime()
})-[:OF_CLASS]->(rc)
```

#### PCI Device Query Patterns

```cypher
// Find available VFs with specific physnet
MATCH (host:ResourceProvider)-[:PARENT_OF*]->(pf:PCIPF)-[:HAS_TRAIT]->(:Trait {name: $physnet_trait})
MATCH (pf)-[:PARENT_OF]->(vf:PCIVF)-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(:ResourceClass {name: 'SRIOV_NET_VF'})
WHERE NOT (inv)<-[:CONSUMES]-()
RETURN host, pf, vf

// Find PCI devices on same NUMA node as instance
MATCH (consumer:Consumer {uuid: $instance_uuid})-[:CONSUMES]->()<-[:HAS_INVENTORY]-(numa:NUMANode)
MATCH (numa)-[:PARENT_OF*]->(vf:PCIVF)-[:HAS_INVENTORY]->(inv)
WHERE NOT (inv)<-[:CONSUMES]-()
RETURN vf, inv
```

### vGPU Modeling

Virtual GPUs are modeled as child resource providers of physical GPU providers.

#### vGPU Tree Structure

```
(:ResourceProvider:ComputeHost)
    │
    └──[:PARENT_OF]──► (:ResourceProvider:NUMANode)
                            │
                            └──[:PARENT_OF]──► (:ResourceProvider:PhysicalGPU)
                                                   │
                                                   ├── name: "compute-001_pci_0000:82:00.0"
                                                   ├── address: "0000:82:00.0"
                                                   │
                                                   ├──[:HAS_TRAIT]──► (:Trait {name: 'CUSTOM_NVIDIA_A100'})
                                                   │
                                                   └──[:PARENT_OF]──► (:ResourceProvider:vGPUType)
                                                                          │
                                                                          ├── name: "nvidia-35"
                                                                          ├── Inventory: VGPU (total: 8)
                                                                          │
                                                                          └──[:HAS_TRAIT]──► (:Trait {name: 'CUSTOM_VGPU_NVIDIA_35'})
```

#### vGPU Creation Pattern

```cypher
// Create physical GPU resource provider
MATCH (numa:ResourceProvider:NUMANode {name: 'compute-001_numa_1'})

CREATE (pgpu:ResourceProvider:PhysicalGPU {
  uuid: randomUUID(),
  name: 'compute-001_pci_0000:82:00.0',
  address: '0000:82:00.0',
  generation: 1,
  created_at: datetime(),
  updated_at: datetime()
})
CREATE (numa)-[:PARENT_OF]->(pgpu)

// Add GPU trait
MERGE (gpu_trait:Trait {name: 'CUSTOM_NVIDIA_A100', standard: false, created_at: datetime(), updated_at: datetime()})
CREATE (pgpu)-[:HAS_TRAIT]->(gpu_trait)

// Create vGPU type resource provider
CREATE (vgpu_type:ResourceProvider:vGPUType {
  uuid: randomUUID(),
  name: 'compute-001_pci_0000:82:00.0_nvidia-35',
  vgpu_type: 'nvidia-35',
  generation: 1,
  created_at: datetime(),
  updated_at: datetime()
})
CREATE (pgpu)-[:PARENT_OF]->(vgpu_type)

// Add VGPU inventory
MATCH (rc:ResourceClass {name: 'VGPU'})
CREATE (vgpu_type)-[:HAS_INVENTORY]->(inv:Inventory {
  total: 8,
  reserved: 0,
  min_unit: 1,
  max_unit: 8,
  step_size: 1,
  allocation_ratio: 1.0,
  created_at: datetime(),
  updated_at: datetime()
})-[:OF_CLASS]->(rc)

// Add vGPU type trait
MERGE (vgpu_trait:Trait {name: 'CUSTOM_VGPU_NVIDIA_35', standard: false, created_at: datetime(), updated_at: datetime()})
CREATE (vgpu_type)-[:HAS_TRAIT]->(vgpu_trait)
```

### Sharing Providers

Sharing providers (e.g., shared storage) share resources with multiple trees.

#### Sharing Provider Pattern

```
(:ResourceProvider {name: "shared-storage-001"})
    │
    ├── Inventory: DISK_GB (total: 100000)
    │
    ├──[:HAS_TRAIT]──► (:Trait {name: 'MISC_SHARES_VIA_AGGREGATE'})
    │
    ├──[:MEMBER_OF]──► (:Aggregate {name: "shared-storage-agg"})
    │                       │
    │                       ├──[:MEMBER_OF]── (:ResourceProvider {name: "compute-001"})
    │                       ├──[:MEMBER_OF]── (:ResourceProvider {name: "compute-002"})
    │                       └──[:MEMBER_OF]── (:ResourceProvider {name: "compute-003"})
    │
    └──[:SHARES_RESOURCES {resource_classes: ['DISK_GB']}]──► (:ResourceProvider compute-001)
       [:SHARES_RESOURCES {resource_classes: ['DISK_GB']}]──► (:ResourceProvider compute-002)
       [:SHARES_RESOURCES {resource_classes: ['DISK_GB']}]──► (:ResourceProvider compute-003)
```

#### Sharing Provider Creation

```cypher
// Create shared storage provider
CREATE (storage:ResourceProvider {
  uuid: randomUUID(),
  name: 'shared-storage-001',
  generation: 1,
  created_at: datetime(),
  updated_at: datetime()
})

// Add DISK_GB inventory
MATCH (rc:ResourceClass {name: 'DISK_GB'})
CREATE (storage)-[:HAS_INVENTORY]->(inv:Inventory {
  total: 100000,
  reserved: 1000,
  min_unit: 1,
  max_unit: 10000,
  step_size: 1,
  allocation_ratio: 1.0,
  created_at: datetime(),
  updated_at: datetime()
})-[:OF_CLASS]->(rc)

// Add sharing trait
MERGE (sharing_trait:Trait {name: 'MISC_SHARES_VIA_AGGREGATE'})
CREATE (storage)-[:HAS_TRAIT]->(sharing_trait)

// Create aggregate and memberships
CREATE (agg:Aggregate {uuid: randomUUID(), name: 'shared-storage-agg', created_at: datetime(), updated_at: datetime()})
CREATE (storage)-[:MEMBER_OF]->(agg)

// Add compute nodes to aggregate and create SHARES_RESOURCES relationships
MATCH (compute:ResourceProvider)
WHERE compute.name STARTS WITH 'compute-'
CREATE (compute)-[:MEMBER_OF]->(agg)
CREATE (storage)-[:SHARES_RESOURCES {resource_classes: ['DISK_GB']}]->(compute)
```

#### Sharing Provider Query

```cypher
// Find allocation candidates including shared DISK_GB
MATCH (compute:ResourceProvider)-[:HAS_INVENTORY]->(vcpu_inv)-[:OF_CLASS]->(:ResourceClass {name: 'VCPU'})
MATCH (compute)-[:HAS_INVENTORY]->(mem_inv)-[:OF_CLASS]->(:ResourceClass {name: 'MEMORY_MB'})

// Include shared storage
OPTIONAL MATCH (storage:ResourceProvider)-[:SHARES_RESOURCES]->(compute)
MATCH (storage)-[:HAS_INVENTORY]->(disk_inv)-[:OF_CLASS]->(:ResourceClass {name: 'DISK_GB'})

// Check capacities...
RETURN compute, storage, vcpu_inv, mem_inv, disk_inv
```

---

## Constraint Modeling

This section maps Nova/Placement scheduling constraints to graph patterns.

### Constraint Types Overview

| Constraint Type | Placement/Nova Mechanism | Tachyon Graph Pattern |
|-----------------|--------------------------|----------------------|
| Required Traits | `trait:X=required` | `(rp)-[:HAS_TRAIT]->(t:Trait {name: X})` |
| Forbidden Traits | `trait:X=forbidden` | `NOT (rp)-[:HAS_TRAIT]->(:Trait {name: X})` |
| Aggregate Membership | `member_of` query | `(rp)-[:MEMBER_OF]->(agg:Aggregate)` |
| Tenant Isolation | `filter_tenant_id` metadata | `(agg)-[:TENANT_ALLOWED]->(proj)` |
| Image Isolation | `AggregateImagePropertiesIsolation` | `(agg)-[:IMAGE_ALLOWED]->(img)` |
| Availability Zone | AZ request | `(agg)-[:DEFINES_AZ]->(az:AvailabilityZone)` |
| Server Group Affinity | `affinity` policy | Same host via SCHEDULED_ON |
| Server Group Anti-Affinity | `anti-affinity` policy | Different hosts via SCHEDULED_ON |
| NUMA Affinity | `hw:numa_nodes` | Subtree allocation pattern |
| PCI-NUMA Affinity | `hw:pci_numa_affinity_policy` | NUMA_AFFINITY relationship |
| Resource Group Isolation | `group_policy=isolate` | Different provider subgraphs |

### Trait-Based Constraints

#### Required Traits

Ensure resource provider has specific trait(s).

```cypher
// Single required trait
MATCH (rp:ResourceProvider)-[:HAS_TRAIT]->(:Trait {name: 'HW_CPU_X86_AVX2'})

// Multiple required traits (AND)
MATCH (rp:ResourceProvider)
WHERE ALL(trait_name IN ['HW_CPU_X86_AVX2', 'COMPUTE_VOLUME_MULTI_ATTACH'] 
      WHERE (rp)-[:HAS_TRAIT]->(:Trait {name: trait_name}))

// Required traits from list
MATCH (rp:ResourceProvider)
WITH rp, $required_traits AS required
WHERE ALL(t IN required WHERE (rp)-[:HAS_TRAIT]->(:Trait {name: t}))
RETURN rp
```

#### Forbidden Traits

Exclude resource providers with specific trait(s).

```cypher
// Single forbidden trait
MATCH (rp:ResourceProvider)
WHERE NOT (rp)-[:HAS_TRAIT]->(:Trait {name: 'COMPUTE_STATUS_DISABLED'})

// Multiple forbidden traits (none of them)
MATCH (rp:ResourceProvider)
WHERE NONE(trait_name IN ['COMPUTE_STATUS_DISABLED', 'CUSTOM_MAINTENANCE'] 
      WHERE (rp)-[:HAS_TRAIT]->(:Trait {name: trait_name}))

// Forbidden traits from list
MATCH (rp:ResourceProvider)
WITH rp, $forbidden_traits AS forbidden
WHERE NONE(t IN forbidden WHERE (rp)-[:HAS_TRAIT]->(:Trait {name: t}))
RETURN rp
```

#### Any-Of Traits (OR)

At least one trait from a set must be present.

```cypher
// Any of these traits (OR)
MATCH (rp:ResourceProvider)
WHERE ANY(trait_name IN ['HW_CPU_X86_AVX', 'HW_CPU_X86_AVX2', 'HW_CPU_X86_AVX512F'] 
      WHERE (rp)-[:HAS_TRAIT]->(:Trait {name: trait_name}))

// Using EXISTS
MATCH (rp:ResourceProvider)
WHERE EXISTS {
  MATCH (rp)-[:HAS_TRAIT]->(t:Trait)
  WHERE t.name IN ['HW_CPU_X86_AVX', 'HW_CPU_X86_AVX2', 'HW_CPU_X86_AVX512F']
}
RETURN rp
```

#### Preferred Traits (Soft Affinity)

Prefer providers with specific traits without requiring them. Hosts with
preferred traits receive higher scores in weighing.

```cypher
// Calculate preferred trait score for each host
// $preferred_traits: [{name: 'STORAGE_DISK_SSD', weight: 2.0}, {name: 'HW_NIC_SRIOV', weight: 1.0}]

MATCH (rp:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(rp)

// Count matching preferred traits with weights
WITH rp, $preferred_traits AS preferred
OPTIONAL MATCH (rp)-[:HAS_TRAIT]->(t:Trait)
WHERE t.name IN [p IN preferred | p.name]

// Calculate weighted score
WITH rp, 
     [p IN $preferred_traits WHERE (rp)-[:HAS_TRAIT]->(:Trait {name: p.name}) | p.weight] AS matched_weights,
     size($preferred_traits) AS total_preferred

WITH rp,
     reduce(score = 0.0, w IN matched_weights | score + w) AS preferred_score,
     total_preferred

// Normalize: score / max_possible_score for fair comparison
WITH rp, preferred_score,
     reduce(max_score = 0.0, p IN $preferred_traits | max_score + p.weight) AS max_possible_score

RETURN rp, 
       preferred_score,
       CASE WHEN max_possible_score > 0 
            THEN preferred_score / max_possible_score 
            ELSE 0.0 
       END AS normalized_preferred_score
ORDER BY normalized_preferred_score DESC
```

```cypher
// Simple version: count of matching preferred traits
MATCH (rp:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(rp)

WITH rp, $preferred_traits AS preferred
WITH rp, size([t IN preferred WHERE (rp)-[:HAS_TRAIT]->(:Trait {name: t})]) AS preferred_match_count

RETURN rp, preferred_match_count
ORDER BY preferred_match_count DESC
```

#### Avoided Traits (Soft Anti-Affinity)

Avoid providers with specific traits without excluding them. Hosts with
avoided traits receive lower scores (penalties) in weighing.

```cypher
// Calculate avoided trait penalty for each host
// $avoided_traits: [{name: 'CUSTOM_MAINTENANCE_WINDOW', weight: 5.0}, {name: 'CUSTOM_HIGH_LATENCY', weight: 1.0}]

MATCH (rp:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(rp)

// Calculate penalty for having avoided traits
WITH rp, $avoided_traits AS avoided
WITH rp,
     [a IN $avoided_traits WHERE (rp)-[:HAS_TRAIT]->(:Trait {name: a.name}) | a.weight] AS matched_penalties

WITH rp,
     reduce(penalty = 0.0, w IN matched_penalties | penalty + w) AS avoided_penalty

// Negative score means penalty
RETURN rp, 
       avoided_penalty,
       -1 * avoided_penalty AS avoided_score
ORDER BY avoided_score DESC
```

```cypher
// Simple version: count of matching avoided traits (as negative)
MATCH (rp:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(rp)

WITH rp, $avoided_traits AS avoided
WITH rp, size([t IN avoided WHERE (rp)-[:HAS_TRAIT]->(:Trait {name: t})]) AS avoided_match_count

RETURN rp, -1 * avoided_match_count AS avoided_score
ORDER BY avoided_score DESC
```

#### Combined Preferred and Avoided Traits

Combine both soft constraints in a single query.

```cypher
// Combined soft trait scoring
// $preferred_traits: [{name: 'STORAGE_DISK_SSD', weight: 2.0}]
// $avoided_traits: [{name: 'CUSTOM_MAINTENANCE', weight: 5.0}]
// $trait_weight_multiplier: 1.0

MATCH (rp:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(rp)

// Calculate preferred score
WITH rp,
     reduce(score = 0.0, p IN $preferred_traits | 
       score + CASE WHEN (rp)-[:HAS_TRAIT]->(:Trait {name: p.name}) THEN p.weight ELSE 0.0 END
     ) AS preferred_score

// Calculate avoided penalty
WITH rp, preferred_score,
     reduce(penalty = 0.0, a IN $avoided_traits |
       penalty + CASE WHEN (rp)-[:HAS_TRAIT]->(:Trait {name: a.name}) THEN a.weight ELSE 0.0 END
     ) AS avoided_penalty

// Combined score: preferred bonus minus avoided penalty
WITH rp, 
     preferred_score,
     avoided_penalty,
     (preferred_score - avoided_penalty) * $trait_weight_multiplier AS trait_affinity_score

RETURN rp, preferred_score, avoided_penalty, trait_affinity_score
ORDER BY trait_affinity_score DESC
```

#### Flavor-Driven Soft Trait Resolution

Extract preferred/avoided traits from flavor and apply scoring.

```cypher
// Resolve traits from flavor
MATCH (flavor:Flavor {uuid: $flavor_uuid})
OPTIONAL MATCH (flavor)-[req:REQUIRES_TRAIT]->(trait:Trait)

WITH flavor,
     collect(CASE WHEN req.constraint = 'required' THEN trait.name END) AS required,
     collect(CASE WHEN req.constraint = 'forbidden' THEN trait.name END) AS forbidden,
     collect(CASE WHEN req.constraint = 'preferred' 
                  THEN {name: trait.name, weight: COALESCE(req.weight, 1.0)} END) AS preferred,
     collect(CASE WHEN req.constraint = 'avoided' 
                  THEN {name: trait.name, weight: COALESCE(req.weight, 1.0)} END) AS avoided

// Filter out nulls
WITH required, forbidden,
     [p IN preferred WHERE p IS NOT NULL] AS preferred_traits,
     [a IN avoided WHERE a IS NOT NULL] AS avoided_traits

// Apply hard constraints first (filter)
MATCH (rp:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(rp)
  AND ALL(t IN required WHERE (rp)-[:HAS_TRAIT]->(:Trait {name: t}))
  AND NONE(t IN forbidden WHERE (rp)-[:HAS_TRAIT]->(:Trait {name: t}))

// Apply soft constraints (weigh)
WITH rp, preferred_traits, avoided_traits,
     reduce(score = 0.0, p IN preferred_traits |
       score + CASE WHEN (rp)-[:HAS_TRAIT]->(:Trait {name: p.name}) THEN p.weight ELSE 0.0 END
     ) AS preferred_score,
     reduce(penalty = 0.0, a IN avoided_traits |
       penalty + CASE WHEN (rp)-[:HAS_TRAIT]->(:Trait {name: a.name}) THEN a.weight ELSE 0.0 END
     ) AS avoided_penalty

RETURN rp, 
       preferred_score - avoided_penalty AS soft_trait_score
ORDER BY soft_trait_score DESC
```

### Aggregate-Based Constraints

#### Member Of (Required Aggregate)

Provider must be in specific aggregate(s).

```cypher
// Single aggregate
MATCH (rp:ResourceProvider)-[:MEMBER_OF]->(:Aggregate {uuid: $aggregate_uuid})

// Any of multiple aggregates (OR)
MATCH (rp:ResourceProvider)-[:MEMBER_OF]->(agg:Aggregate)
WHERE agg.uuid IN $aggregate_uuids

// All of multiple aggregates (AND)
MATCH (rp:ResourceProvider)
WHERE ALL(agg_uuid IN $aggregate_uuids 
      WHERE (rp)-[:MEMBER_OF]->(:Aggregate {uuid: agg_uuid}))
```

#### Forbidden Aggregate Membership

Provider must NOT be in specific aggregate(s).

```cypher
// Not in any of these aggregates
MATCH (rp:ResourceProvider)
WHERE NONE(agg_uuid IN $forbidden_aggregates 
      WHERE (rp)-[:MEMBER_OF]->(:Aggregate {uuid: agg_uuid}))
```

#### Availability Zone Constraint

```cypher
// Find providers in specific AZ
MATCH (rp:ResourceProvider)-[:MEMBER_OF]->(agg:Aggregate)-[:DEFINES_AZ]->(:AvailabilityZone {name: $az_name})
RETURN DISTINCT rp

// Providers not in any AZ (default zone)
MATCH (rp:ResourceProvider)
WHERE NOT EXISTS {
  MATCH (rp)-[:MEMBER_OF]->(:Aggregate)-[:DEFINES_AZ]->(:AvailabilityZone)
}
RETURN rp
```

### Tenant Isolation Constraints

#### Basic Tenant Isolation

Aggregates with TENANT_ALLOWED restrict which projects can schedule.

```cypher
// Check if project can use provider
MATCH (rp:ResourceProvider)
OPTIONAL MATCH (rp)-[:MEMBER_OF]->(agg:Aggregate)-[:TENANT_ALLOWED]->(allowed:Project)

// Provider is usable if:
// 1. Not in any aggregate with tenant restrictions, OR
// 2. In aggregate that allows this project
WITH rp, collect(DISTINCT agg) AS isolated_aggs, collect(DISTINCT allowed) AS allowed_projects
WHERE size(isolated_aggs) = 0 
   OR ANY(p IN allowed_projects WHERE p.external_id = $project_id)
RETURN rp
```

#### Tenant Isolation Query Pattern

```cypher
// Find all providers accessible to a project
MATCH (rp:ResourceProvider)
WHERE NOT EXISTS {
  // Provider is in an isolated aggregate that doesn't allow this project
  MATCH (rp)-[:MEMBER_OF]->(agg:Aggregate)-[:TENANT_ALLOWED]->(:Project)
  WHERE NOT (agg)-[:TENANT_ALLOWED]->(:Project {external_id: $project_id})
}
RETURN rp
```

### Image Isolation Constraints

#### Aggregate Image Properties Isolation

```cypher
// Check if image can use provider based on aggregate isolation
MATCH (rp:ResourceProvider)
OPTIONAL MATCH (rp)-[:MEMBER_OF]->(agg:Aggregate)-[:IMAGE_ALLOWED]->(img:Image)

WITH rp, collect(DISTINCT agg) AS isolated_aggs, collect(DISTINCT img) AS allowed_images
WHERE size(isolated_aggs) = 0 
   OR ANY(i IN allowed_images WHERE i.uuid = $image_uuid)
RETURN rp
```

### Server Group Constraints

#### Affinity Policy

All group instances must be on the same host.

```cypher
// Find valid hosts for affinity group
MATCH (sg:ServerGroup {uuid: $group_uuid, policy: 'affinity'})
OPTIONAL MATCH (sg)-[:HAS_MEMBER]->(existing:Consumer)-[:SCHEDULED_ON]->(host:ResourceProvider)

// If group is empty, any host is valid
// If group has members, only the host(s) they're on are valid
WITH sg, collect(DISTINCT host) AS group_hosts
MATCH (candidate:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(candidate)  // Root providers only
  AND (size(group_hosts) = 0 OR candidate IN group_hosts)
RETURN candidate
```

#### Anti-Affinity Policy

Group instances must be on different hosts.

```cypher
// Find valid hosts for anti-affinity group
MATCH (sg:ServerGroup {uuid: $group_uuid, policy: 'anti-affinity'})
OPTIONAL MATCH (sg)-[:HAS_MEMBER]->(existing:Consumer)-[:SCHEDULED_ON]->(occupied:ResourceProvider)

WITH sg, collect(DISTINCT occupied) AS occupied_hosts
MATCH (candidate:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(candidate)  // Root providers only
  AND NOT candidate IN occupied_hosts
RETURN candidate
```

#### Anti-Affinity with max_server_per_host

```cypher
// Find hosts not exceeding max_server_per_host
MATCH (sg:ServerGroup {uuid: $group_uuid, policy: 'anti-affinity'})
MATCH (candidate:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(candidate)

// Count existing group instances on each candidate
OPTIONAL MATCH (sg)-[:HAS_MEMBER]->(member:Consumer)-[:SCHEDULED_ON]->(candidate)
WITH candidate, sg, count(member) AS instance_count

// Check against limit (default is 1 if not specified)
WHERE instance_count < COALESCE(sg.rules.max_server_per_host, 1)
RETURN candidate
```

#### Soft Affinity/Anti-Affinity

For weighing rather than hard filtering.

```cypher
// Soft affinity: weight by number of group instances on host
MATCH (sg:ServerGroup {uuid: $group_uuid, policy: 'soft-affinity'})
MATCH (candidate:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(candidate)

OPTIONAL MATCH (sg)-[:HAS_MEMBER]->(member:Consumer)-[:SCHEDULED_ON]->(candidate)
WITH candidate, count(member) AS affinity_score
RETURN candidate, affinity_score
ORDER BY affinity_score DESC

// Soft anti-affinity: weight inversely by group instance count
MATCH (sg:ServerGroup {uuid: $group_uuid, policy: 'soft-anti-affinity'})
MATCH (candidate:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(candidate)

OPTIONAL MATCH (sg)-[:HAS_MEMBER]->(member:Consumer)-[:SCHEDULED_ON]->(candidate)
WITH candidate, count(member) AS instance_count
RETURN candidate, -1 * instance_count AS anti_affinity_score
ORDER BY anti_affinity_score DESC
```

### NUMA Topology Constraints

#### Same NUMA Node for Resources

Ensure all resources come from same NUMA node.

```cypher
// Find NUMA nodes that can satisfy all resource requirements
MATCH (host:ResourceProvider)-[:PARENT_OF]->(numa:NUMANode)

// Check each resource class
UNWIND $resource_requirements AS req
MATCH (numa)-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(:ResourceClass {name: req.resource_class})

// Calculate available capacity
OPTIONAL MATCH (inv)<-[c:CONSUMES]-()
WITH host, numa, inv, req,
     (inv.total - inv.reserved) * inv.allocation_ratio AS capacity,
     COALESCE(sum(c.used), 0) AS used

WHERE capacity - used >= req.amount
WITH host, numa, collect(inv) AS inventories
WHERE size(inventories) = size($resource_requirements)
RETURN host, numa, inventories
```

#### PCI-NUMA Affinity

```cypher
// Policy: required - PCI must be on same NUMA as instance
MATCH (host:ResourceProvider)-[:PARENT_OF]->(numa:NUMANode)
MATCH (numa)-[:PARENT_OF*]->(pci_provider)-[:HAS_INVENTORY]->(pci_inv)-[:OF_CLASS]->(:ResourceClass {name: 'SRIOV_NET_VF'})
WHERE NOT (pci_inv)<-[:CONSUMES]-()

// Instance resources must come from same NUMA
MATCH (numa)-[:HAS_INVENTORY]->(vcpu_inv)-[:OF_CLASS]->(:ResourceClass {name: 'VCPU'})
MATCH (numa)-[:HAS_INVENTORY]->(mem_inv)-[:OF_CLASS]->(:ResourceClass {name: 'MEMORY_MB'})

RETURN host, numa, pci_provider, vcpu_inv, mem_inv
```

### Resource Group Isolation

#### Group Policy: Isolate

Each numbered resource group must use different providers.

```cypher
// Find candidates where each group uses distinct providers
// This is a complex allocation problem - simplified example:

MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// For group 1: find providers for group 1 resources
MATCH (host)-[:PARENT_OF*0..]->(g1_provider)
MATCH (g1_provider)-[:HAS_INVENTORY]->(g1_inv)-[:OF_CLASS]->(:ResourceClass {name: $group1_rc})

// For group 2: find DIFFERENT providers for group 2 resources
MATCH (host)-[:PARENT_OF*0..]->(g2_provider)
MATCH (g2_provider)-[:HAS_INVENTORY]->(g2_inv)-[:OF_CLASS]->(:ResourceClass {name: $group2_rc})
WHERE g2_provider <> g1_provider  // Isolation constraint

RETURN host, g1_provider, g2_provider
```

### Same Subtree Constraint

Resources must share a common ancestor.

```cypher
// Ensure resources from groups A and B share common subtree
MATCH (host:ResourceProvider)-[:PARENT_OF*0..]->(ancestor)-[:PARENT_OF*0..]->(provider_a)
MATCH (ancestor)-[:PARENT_OF*0..]->(provider_b)

// provider_a has resources for group A
MATCH (provider_a)-[:HAS_INVENTORY]->(inv_a)-[:OF_CLASS]->(:ResourceClass {name: $group_a_rc})

// provider_b has resources for group B
MATCH (provider_b)-[:HAS_INVENTORY]->(inv_b)-[:OF_CLASS]->(:ResourceClass {name: $group_b_rc})

// Both under common ancestor (e.g., same NUMA node)
WHERE ancestor:NUMANode  // or other appropriate label

RETURN host, ancestor, provider_a, provider_b
```

### In-Tree Constraint

Limit search to specific provider tree.

```cypher
// Only consider providers in specific tree
MATCH (root:ResourceProvider {uuid: $in_tree_uuid})
MATCH (root)-[:PARENT_OF*0..]->(rp)
RETURN rp
```

### Compute Capabilities Constraints

Match flavor extra specs against compute node capabilities.

```cypher
// Example: hypervisor_type == QEMU
MATCH (rp:ResourceProvider)
WHERE rp.hypervisor_type = 'QEMU'

// Example: free_ram_mb >= 4096
MATCH (rp:ResourceProvider)-[:HAS_INVENTORY]->(mem_inv)-[:OF_CLASS]->(:ResourceClass {name: 'MEMORY_MB'})
OPTIONAL MATCH (mem_inv)<-[c:CONSUMES]-()
WITH rp, mem_inv, (mem_inv.total - mem_inv.reserved) - COALESCE(sum(c.used), 0) AS free_ram_mb
WHERE free_ram_mb >= 4096
RETURN rp
```

### Cell Scheduling Constraints

```cypher
// Only schedule to enabled cells
MATCH (rp:ResourceProvider)-[:LOCATED_IN]->(cell:Cell)
WHERE cell.disabled = false
RETURN rp

// Prefer local cell for migrations (CrossCellWeigher)
MATCH (existing:Consumer {uuid: $instance_uuid})-[:SCHEDULED_ON]->(current_host)-[:LOCATED_IN]->(current_cell:Cell)
MATCH (candidate:ResourceProvider)-[:LOCATED_IN]->(candidate_cell:Cell)
WITH candidate, current_cell, candidate_cell,
     CASE WHEN current_cell = candidate_cell THEN 0 ELSE 1 END AS cross_cell_penalty
RETURN candidate, cross_cell_penalty
ORDER BY cross_cell_penalty
```

---

## Cypher Query Examples

This section provides production-ready Cypher queries for key scheduling
operations, equivalent to Placement API and Nova scheduler functionality.

### Allocation Candidates Query

The core scheduling query, equivalent to `GET /allocation_candidates`.

#### Basic Allocation Candidates

Find providers that can satisfy resource requirements.

```cypher
// Parameters:
// $resources: [{resource_class: 'VCPU', amount: 4}, {resource_class: 'MEMORY_MB', amount: 8192}]
// $required_traits: ['HW_CPU_X86_AVX2']
// $forbidden_traits: ['COMPUTE_STATUS_DISABLED']
// $limit: 100

// Find root providers (compute hosts)
MATCH (root:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(root)
  AND NOT root.disabled = true

// Check required traits on root
WITH root
WHERE ALL(trait IN $required_traits WHERE
  (root)-[:HAS_TRAIT]->(:Trait {name: trait})
)

// Check forbidden traits
AND NONE(trait IN $forbidden_traits WHERE
  (root)-[:HAS_TRAIT]->(:Trait {name: trait})
)

// For each required resource, find inventory with capacity
UNWIND $resources AS req
MATCH (root)-[:PARENT_OF*0..]->(provider)-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(rc:ResourceClass {name: req.resource_class})

// Calculate capacity and usage
OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
WITH root, provider, inv, rc, req,
     (inv.total - inv.reserved) * inv.allocation_ratio AS capacity,
     COALESCE(sum(alloc.used), 0) AS used

// Filter by available capacity
WHERE capacity - used >= req.amount
  AND req.amount >= inv.min_unit
  AND req.amount <= inv.max_unit
  AND req.amount % inv.step_size = 0

// Group results by root provider
WITH root, collect({
  provider: provider,
  inventory: inv,
  resource_class: rc.name,
  amount: req.amount,
  capacity: capacity,
  used: used
}) AS allocations

// Ensure all resources are satisfied
WHERE size(allocations) = size($resources)

RETURN root, allocations
LIMIT $limit
```

#### Allocation Candidates with Traits per Resource Group

Support for granular resource requests with per-group traits.

```cypher
// Parameters:
// $groups: [
//   {suffix: '', resources: [{rc: 'VCPU', amount: 4}], required_traits: [], forbidden_traits: []},
//   {suffix: '1', resources: [{rc: 'SRIOV_NET_VF', amount: 1}], required_traits: ['CUSTOM_PHYSNET_DATA'], forbidden_traits: []}
// ]
// $group_policy: 'none' or 'isolate'

MATCH (root:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(root)
  AND root.disabled <> true

// Process each group
UNWIND $groups AS grp
WITH root, grp

// Find providers that can satisfy this group
MATCH (root)-[:PARENT_OF*0..]->(provider)

// Check group-specific required traits
WHERE ALL(trait IN grp.required_traits WHERE
  (provider)-[:HAS_TRAIT]->(:Trait {name: trait})
)
AND NONE(trait IN grp.forbidden_traits WHERE
  (provider)-[:HAS_TRAIT]->(:Trait {name: trait})
)

// Check resources for this group
UNWIND grp.resources AS req
MATCH (provider)-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(rc:ResourceClass {name: req.rc})
OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
WITH root, grp, provider, inv, rc, req,
     (inv.total - inv.reserved) * inv.allocation_ratio AS capacity,
     COALESCE(sum(alloc.used), 0) AS used
WHERE capacity - used >= req.amount

WITH root, grp, provider, collect({
  inventory: inv,
  resource_class: rc.name,
  amount: req.amount
}) AS group_allocations
WHERE size(group_allocations) = size(grp.resources)

WITH root, collect({
  suffix: grp.suffix,
  provider: provider,
  allocations: group_allocations
}) AS groups

// For group_policy=isolate, ensure different providers per group
// (This is a simplified check; full implementation would be more complex)
RETURN root, groups
```

#### Allocation Candidates with Aggregates

Include aggregate membership filtering.

```cypher
// Parameters:
// $member_of: ['agg-uuid-1', 'agg-uuid-2']  // Any of these aggregates
// $forbidden_aggs: ['agg-uuid-3']  // Not in these aggregates

MATCH (root:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(root)

// member_of filter (any of)
AND (size($member_of) = 0 OR EXISTS {
  MATCH (root)-[:MEMBER_OF]->(agg:Aggregate)
  WHERE agg.uuid IN $member_of
})

// forbidden aggregates
AND NOT EXISTS {
  MATCH (root)-[:MEMBER_OF]->(agg:Aggregate)
  WHERE agg.uuid IN $forbidden_aggs
}

// ... continue with resource checks
RETURN root
```

#### Allocation Candidates with Sharing Providers

Include resources from sharing providers.

```cypher
MATCH (root:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(root)

// Collect all providers that can contribute resources (including sharing)
OPTIONAL MATCH (sharing:ResourceProvider)-[:SHARES_RESOURCES]->(root)
WITH root, collect(DISTINCT sharing) + [root] AS all_providers

// Check each resource requirement against all available providers
UNWIND $resources AS req
UNWIND all_providers AS provider

// For root/nested resources
OPTIONAL MATCH (root)-[:PARENT_OF*0..]->(provider)
MATCH (provider)-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(rc:ResourceClass {name: req.resource_class})

OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
WITH root, provider, inv, rc, req,
     (inv.total - inv.reserved) * inv.allocation_ratio AS capacity,
     COALESCE(sum(alloc.used), 0) AS used
WHERE capacity - used >= req.amount

WITH root, collect({
  provider: provider,
  inventory: inv,
  resource_class: rc.name,
  is_sharing: NOT (root)-[:PARENT_OF*0..]->(provider)
}) AS allocations

RETURN root, allocations
```

### Resource Claiming (Allocation Creation)

Atomic allocation with generation checks.

#### Simple Allocation

```cypher
// Parameters:
// $consumer_uuid: 'instance-uuid'
// $allocations: [{rp_uuid: 'rp-1', resource_class: 'VCPU', used: 4}, ...]
// $project_id: 'project-uuid'
// $user_id: 'user-uuid'
// $consumer_generation: null (new) or current generation (update)
// $provider_generations: {'rp-1': 5, 'rp-2': 3}  // Expected generations

// Start transaction
// Check provider generations haven't changed
UNWIND keys($provider_generations) AS rp_uuid
MATCH (rp:ResourceProvider {uuid: rp_uuid})
WHERE rp.generation = $provider_generations[rp_uuid]
WITH collect(rp) AS verified_providers
WHERE size(verified_providers) = size(keys($provider_generations))

// Get or create consumer
MERGE (consumer:Consumer {uuid: $consumer_uuid})
ON CREATE SET
  consumer.generation = 0,
  consumer.created_at = datetime(),
  consumer.updated_at = datetime()
ON MATCH SET
  consumer.updated_at = datetime()

// Verify consumer generation if updating
WITH consumer
WHERE $consumer_generation IS NULL OR consumer.generation = $consumer_generation

// Link to project and user
MERGE (project:Project {external_id: $project_id})
MERGE (user:User {external_id: $user_id})
MERGE (consumer)-[:OWNED_BY]->(project)
MERGE (consumer)-[:CREATED_BY]->(user)

// Remove existing allocations (for replacement)
OPTIONAL MATCH (consumer)-[old_alloc:CONSUMES]->()
DELETE old_alloc

// Create new allocations
WITH consumer
UNWIND $allocations AS alloc
MATCH (rp:ResourceProvider {uuid: alloc.rp_uuid})-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(:ResourceClass {name: alloc.resource_class})

// Verify capacity
OPTIONAL MATCH (inv)<-[existing:CONSUMES]-()
WITH consumer, rp, inv, alloc,
     (inv.total - inv.reserved) * inv.allocation_ratio AS capacity,
     COALESCE(sum(existing.used), 0) AS current_usage
WHERE capacity - current_usage >= alloc.used

// Create allocation
CREATE (consumer)-[:CONSUMES {
  used: alloc.used,
  created_at: datetime(),
  updated_at: datetime()
}]->(inv)

// Increment consumer generation
WITH consumer
SET consumer.generation = consumer.generation + 1

RETURN consumer
```

#### Multi-Provider Allocation with Nested Providers

```cypher
// Allocate across root, NUMA, and PCI providers in same tree
// Parameters:
// $allocations: [
//   {provider_uuid: 'root-uuid', resource_class: 'VCPU', used: 4},
//   {provider_uuid: 'numa-0-uuid', resource_class: 'MEMORY_MB', used: 8192},
//   {provider_uuid: 'vf-uuid', resource_class: 'SRIOV_NET_VF', used: 1}
// ]

MATCH (consumer:Consumer {uuid: $consumer_uuid})

UNWIND $allocations AS alloc
MATCH (provider:ResourceProvider {uuid: alloc.provider_uuid})
MATCH (provider)-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(:ResourceClass {name: alloc.resource_class})

// Verify all providers are in same tree
MATCH (root:ResourceProvider)-[:PARENT_OF*0..]->(provider)
WHERE NOT ()-[:PARENT_OF]->(root)
WITH consumer, provider, inv, alloc, root
// All allocations should have same root
WITH consumer, collect({provider: provider, inv: inv, alloc: alloc}) AS all_allocs, collect(DISTINCT root) AS roots
WHERE size(roots) = 1  // All in same tree

// Create allocations
UNWIND all_allocs AS a
CREATE (consumer)-[:CONSUMES {
  used: a.alloc.used,
  created_at: datetime(),
  updated_at: datetime()
}]->(a.inv)

RETURN consumer
```

### Filter Implementations

#### ComputeFilter

Filter out disabled or down compute nodes.

```cypher
// Equivalent to ComputeFilter
MATCH (rp:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(rp)  // Root providers only
  AND COALESCE(rp.disabled, false) = false
  AND NOT (rp)-[:HAS_TRAIT]->(:Trait {name: 'COMPUTE_STATUS_DISABLED'})
RETURN rp
```

#### ImagePropertiesFilter

Match image requirements against host capabilities.

```cypher
// Parameters from image:
// $hw_architecture: 'x86_64'
// $img_hv_type: 'kvm'
// $hw_vm_mode: 'hvm'

MATCH (rp:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(rp)

// Check architecture (if specified)
AND ($hw_architecture IS NULL OR
     (rp)-[:HAS_TRAIT]->(:Trait {name: 'HW_ARCH_' + toUpper($hw_architecture)}) OR
     (rp)-[:HAS_TRAIT]->(:Trait {name: 'COMPUTE_ARCH_' + toUpper($hw_architecture)}))

// Check hypervisor type
AND ($img_hv_type IS NULL OR
     toLower(rp.hypervisor_type) = toLower($img_hv_type))

// Check VM mode
AND ($hw_vm_mode IS NULL OR
     (rp)-[:HAS_TRAIT]->(:Trait {name: 'COMPUTE_VM_MODE_' + toUpper($hw_vm_mode)}))

RETURN rp
```

#### NUMATopologyFilter

Validate NUMA topology requirements.

```cypher
// Parameters:
// $numa_nodes: 2  // Required number of NUMA nodes
// $vcpus_per_node: [4, 4]  // vCPUs per NUMA node
// $memory_per_node: [4096, 4096]  // Memory per NUMA node (MB)

MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// Find NUMA nodes with sufficient resources
MATCH (host)-[:PARENT_OF]->(numa:NUMANode)
MATCH (numa)-[:HAS_INVENTORY]->(vcpu_inv)-[:OF_CLASS]->(:ResourceClass {name: 'VCPU'})
MATCH (numa)-[:HAS_INVENTORY]->(mem_inv)-[:OF_CLASS]->(:ResourceClass {name: 'MEMORY_MB'})

OPTIONAL MATCH (vcpu_inv)<-[vc:CONSUMES]-()
OPTIONAL MATCH (mem_inv)<-[mc:CONSUMES]-()

WITH host, numa,
     (vcpu_inv.total - vcpu_inv.reserved) * vcpu_inv.allocation_ratio - COALESCE(sum(vc.used), 0) AS avail_vcpus,
     (mem_inv.total - mem_inv.reserved) * mem_inv.allocation_ratio - COALESCE(sum(mc.used), 0) AS avail_mem

// Collect NUMA nodes that meet minimum requirements
WITH host, collect({
  numa: numa,
  avail_vcpus: avail_vcpus,
  avail_mem: avail_mem
}) AS numa_nodes

// Check if we have enough suitable NUMA nodes
WHERE size([n IN numa_nodes WHERE n.avail_vcpus >= $min_vcpus_per_node AND n.avail_mem >= $min_mem_per_node]) >= $numa_nodes

RETURN host, numa_nodes
```

#### PciPassthroughFilter

Match PCI device requirements.

```cypher
// Parameters:
// $pci_requests: [
//   {alias: 'gpu', count: 1, traits: ['CUSTOM_NVIDIA_A100']},
//   {alias: 'nic', count: 2, traits: ['CUSTOM_PHYSNET_DATA']}
// ]

MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// For each PCI request, find matching devices
UNWIND $pci_requests AS req
MATCH (host)-[:PARENT_OF*]->(pci_provider)-[:HAS_INVENTORY]->(inv)
WHERE ALL(trait IN req.traits WHERE (pci_provider)-[:HAS_TRAIT]->(:Trait {name: trait}))

// Check available count
OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
WITH host, req, pci_provider, inv,
     (inv.total - inv.reserved) - COALESCE(sum(alloc.used), 0) AS available

WHERE available >= 1
WITH host, req, collect(pci_provider) AS matching_providers
WHERE size(matching_providers) >= req.count

WITH host, collect({request: req, providers: matching_providers}) AS pci_matches
WHERE size(pci_matches) = size($pci_requests)

RETURN host, pci_matches
```

#### AggregateInstanceExtraSpecsFilter

Match flavor extra specs against aggregate metadata.

```cypher
// Parameters:
// $aggregate_extra_specs: {'ssd': 'true', 'gpu_type': 'nvidia'}

MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// Host must be in an aggregate matching all specs, or not in any aggregate with those keys
WITH host
OPTIONAL MATCH (host)-[:MEMBER_OF]->(agg:Aggregate)

WITH host, collect(agg) AS host_aggs
WHERE size(host_aggs) = 0 OR
      ANY(agg IN host_aggs WHERE
        ALL(key IN keys($aggregate_extra_specs) WHERE
          agg[key] IS NULL OR agg[key] = $aggregate_extra_specs[key]
        )
      )

RETURN host
```

### Weigher Implementations

#### RAMWeigher

Weight by available RAM.

```cypher
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)
MATCH (host)-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(:ResourceClass {name: 'MEMORY_MB'})

OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
WITH host, inv,
     (inv.total - inv.reserved) * inv.allocation_ratio AS capacity,
     COALESCE(sum(alloc.used), 0) AS used

WITH host, capacity - used AS free_ram_mb

// Normalize: (value - min) / (max - min)
WITH collect({host: host, free_ram: free_ram_mb}) AS all_hosts
WITH all_hosts,
     reduce(min_val = all_hosts[0].free_ram, h IN all_hosts | CASE WHEN h.free_ram < min_val THEN h.free_ram ELSE min_val END) AS min_ram,
     reduce(max_val = all_hosts[0].free_ram, h IN all_hosts | CASE WHEN h.free_ram > max_val THEN h.free_ram ELSE max_val END) AS max_ram

UNWIND all_hosts AS h
WITH h.host AS host, h.free_ram AS free_ram,
     CASE WHEN max_ram = min_ram THEN 0.0
          ELSE toFloat(h.free_ram - min_ram) / (max_ram - min_ram)
     END AS normalized_weight

// Apply multiplier (positive = spread, negative = stack)
RETURN host, free_ram, normalized_weight * $ram_weight_multiplier AS ram_weight
ORDER BY ram_weight DESC
```

#### CPUWeigher

Weight by available vCPUs.

```cypher
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)
MATCH (host)-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(:ResourceClass {name: 'VCPU'})

OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
WITH host, inv,
     (inv.total - inv.reserved) * inv.allocation_ratio AS capacity,
     COALESCE(sum(alloc.used), 0) AS used

WITH host, capacity - used AS free_vcpus

// Normalize and apply multiplier
WITH collect({host: host, free_vcpus: free_vcpus}) AS all_hosts
// ... normalization similar to RAMWeigher ...

UNWIND all_hosts AS h
RETURN h.host AS host, h.free_vcpus AS free_vcpus,
       toFloat(h.free_vcpus) * $cpu_weight_multiplier AS cpu_weight
ORDER BY cpu_weight DESC
```

#### PCIWeigher

Weight by PCI device availability.

```cypher
// Prefer hosts that match PCI demand level
// High PCI request -> prefer hosts with many PCI devices
// No PCI request -> prefer hosts with no PCI devices
// $requested_pci_count: number of PCI devices requested

MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// Count available PCI devices
OPTIONAL MATCH (host)-[:PARENT_OF*]->(pci:PCIVF)-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(:ResourceClass {name: 'SRIOV_NET_VF'})
OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
WITH host,
     COALESCE(sum(inv.total - inv.reserved - COALESCE(alloc.used, 0)), 0) AS available_pci

// Weight calculation
WITH host, available_pci,
     CASE
       WHEN $requested_pci_count = 0 AND available_pci = 0 THEN 1.0  // Perfect match: no PCI needed, no PCI available
       WHEN $requested_pci_count = 0 THEN 0.0  // Penalize wasting PCI-capable hosts
       WHEN available_pci >= $requested_pci_count THEN toFloat(available_pci) / 100  // Prefer hosts with PCI when needed
       ELSE -1.0  // Can't satisfy request
     END AS pci_weight

WHERE pci_weight >= 0 OR $requested_pci_count = 0
RETURN host, available_pci, pci_weight * $pci_weight_multiplier AS weighted_pci
ORDER BY weighted_pci DESC
```

#### IoOpsWeigher

Weight by current I/O operations.

```cypher
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// Count instances in I/O heavy states
OPTIONAL MATCH (consumer:Consumer)-[:SCHEDULED_ON]->(host)
WHERE consumer.task_state IN ['spawning', 'resize_migrating', 'rebuilding', 
                               'resize_prep', 'image_snapshot', 'image_backup', 
                               'rescuing', 'unshelving']

WITH host, count(consumer) AS io_ops

// Lower is better (default negative multiplier)
RETURN host, io_ops, -1 * io_ops * $io_ops_weight_multiplier AS io_weight
ORDER BY io_weight DESC
```

#### ServerGroupSoftAffinityWeigher

```cypher
MATCH (sg:ServerGroup {uuid: $group_uuid})
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// Count group members on each host
OPTIONAL MATCH (sg)-[:HAS_MEMBER]->(member:Consumer)-[:SCHEDULED_ON]->(host)
WITH host, count(member) AS group_instance_count

// More instances = higher weight (prefer collocation)
RETURN host, group_instance_count,
       group_instance_count * $soft_affinity_weight_multiplier AS affinity_weight
ORDER BY affinity_weight DESC
```

#### ServerGroupSoftAntiAffinityWeigher

```cypher
MATCH (sg:ServerGroup {uuid: $group_uuid})
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// Count group members on each host
OPTIONAL MATCH (sg)-[:HAS_MEMBER]->(member:Consumer)-[:SCHEDULED_ON]->(host)
WITH host, count(member) AS group_instance_count

// Fewer instances = higher weight (prefer spreading)
// Use negative count so lowest count gets highest weight
RETURN host, group_instance_count,
       -1 * group_instance_count * $soft_anti_affinity_weight_multiplier AS anti_affinity_weight
ORDER BY anti_affinity_weight DESC
```

#### TraitAffinityWeigher

Weight by preferred and avoided trait matching. This is the soft constraint
equivalent of required/forbidden trait filtering.

**Configuration Parameters:**
- `$preferred_traits`: List of `{name, weight}` for preferred traits
- `$avoided_traits`: List of `{name, weight}` for avoided traits
- `$trait_weight_multiplier`: Overall multiplier for trait-based scoring

```cypher
// TraitAffinityWeigher - Score hosts based on preferred/avoided traits
// Preferred traits give positive scores, avoided traits give negative scores

MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// Calculate score for preferred traits (bonus for having them)
WITH host,
     reduce(preferred = 0.0, p IN $preferred_traits |
       preferred + CASE WHEN (host)-[:HAS_TRAIT]->(:Trait {name: p.name}) 
                        THEN COALESCE(p.weight, 1.0) 
                        ELSE 0.0 END
     ) AS preferred_score

// Calculate penalty for avoided traits (penalty for having them)
WITH host, preferred_score,
     reduce(avoided = 0.0, a IN $avoided_traits |
       avoided + CASE WHEN (host)-[:HAS_TRAIT]->(:Trait {name: a.name}) 
                      THEN COALESCE(a.weight, 1.0) 
                      ELSE 0.0 END
     ) AS avoided_penalty

// Combined score: preferred bonus minus avoided penalty
WITH host, preferred_score, avoided_penalty,
     (preferred_score - avoided_penalty) AS raw_trait_score

// Normalize across all hosts for fair weighing
WITH collect({host: host, raw_score: raw_trait_score, 
              preferred: preferred_score, avoided: avoided_penalty}) AS all_hosts
WITH all_hosts,
     reduce(min_s = all_hosts[0].raw_score, h IN all_hosts | 
            CASE WHEN h.raw_score < min_s THEN h.raw_score ELSE min_s END) AS min_score,
     reduce(max_s = all_hosts[0].raw_score, h IN all_hosts | 
            CASE WHEN h.raw_score > max_s THEN h.raw_score ELSE max_s END) AS max_score

UNWIND all_hosts AS h
WITH h.host AS host, h.raw_score AS raw_score, 
     h.preferred AS preferred_score, h.avoided AS avoided_penalty,
     CASE WHEN max_score = min_score THEN 0.5
          ELSE toFloat(h.raw_score - min_score) / (max_score - min_score)
     END AS normalized_score

RETURN host, preferred_score, avoided_penalty, raw_score,
       normalized_score * $trait_weight_multiplier AS trait_affinity_weight
ORDER BY trait_affinity_weight DESC
```

**Simpler Version (Without Normalization):**

```cypher
// Simple trait affinity weigher - direct score calculation
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// Count matching traits with weights
WITH host,
     size([p IN $preferred_traits WHERE (host)-[:HAS_TRAIT]->(:Trait {name: p.name})]) AS preferred_count,
     size([a IN $avoided_traits WHERE (host)-[:HAS_TRAIT]->(:Trait {name: a.name})]) AS avoided_count

// Simple scoring: +1 per preferred, -1 per avoided
RETURN host, preferred_count, avoided_count,
       (preferred_count - avoided_count) * $trait_weight_multiplier AS trait_weight
ORDER BY trait_weight DESC
```

**Per-Aggregate Trait Weight Multipliers:**

```cypher
// Support per-aggregate trait_weight_multiplier override
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// Get aggregate-level multiplier override
OPTIONAL MATCH (host)-[:MEMBER_OF]->(agg:Aggregate)
WHERE agg.trait_weight_multiplier IS NOT NULL
WITH host, collect(agg.trait_weight_multiplier) AS agg_multipliers

// Use minimum aggregate multiplier, fall back to global
WITH host, 
     CASE WHEN size(agg_multipliers) > 0 
          THEN reduce(m = agg_multipliers[0], x IN agg_multipliers | 
                      CASE WHEN x < m THEN x ELSE m END)
          ELSE $trait_weight_multiplier 
     END AS effective_multiplier

// Calculate trait scores...
WITH host, effective_multiplier,
     reduce(score = 0.0, p IN $preferred_traits |
       score + CASE WHEN (host)-[:HAS_TRAIT]->(:Trait {name: p.name}) THEN p.weight ELSE 0 END
     ) - reduce(penalty = 0.0, a IN $avoided_traits |
       penalty + CASE WHEN (host)-[:HAS_TRAIT]->(:Trait {name: a.name}) THEN a.weight ELSE 0 END
     ) AS raw_trait_score

RETURN host, raw_trait_score * effective_multiplier AS trait_affinity_weight
ORDER BY trait_affinity_weight DESC
```

**Flavor-Based Trait Affinity:**

```cypher
// Extract soft trait constraints from flavor and apply weighing
MATCH (flavor:Flavor {uuid: $flavor_uuid})
OPTIONAL MATCH (flavor)-[req:REQUIRES_TRAIT]->(trait:Trait)
WHERE req.constraint IN ['preferred', 'avoided']

WITH collect({
  name: trait.name, 
  constraint: req.constraint, 
  weight: COALESCE(req.weight, 1.0)
}) AS soft_traits

WITH [t IN soft_traits WHERE t.constraint = 'preferred'] AS preferred,
     [t IN soft_traits WHERE t.constraint = 'avoided'] AS avoided

// Apply to candidate hosts
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

WITH host, preferred, avoided,
     reduce(score = 0.0, p IN preferred |
       score + CASE WHEN (host)-[:HAS_TRAIT]->(:Trait {name: p.name}) THEN p.weight ELSE 0 END
     ) AS preferred_score,
     reduce(penalty = 0.0, a IN avoided |
       penalty + CASE WHEN (host)-[:HAS_TRAIT]->(:Trait {name: a.name}) THEN a.weight ELSE 0 END
     ) AS avoided_penalty

RETURN host, preferred_score, avoided_penalty,
       (preferred_score - avoided_penalty) * $trait_weight_multiplier AS trait_affinity_weight
ORDER BY trait_affinity_weight DESC
```

#### BuildFailureWeigher

```cypher
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// Get recent build failures (stored as property or separate relationship)
WITH host, COALESCE(host.recent_build_failures, 0) AS failures

// Higher failures = lower weight
RETURN host, failures,
       -1 * failures * $build_failure_weight_multiplier AS failure_weight
ORDER BY failure_weight DESC
```

#### HypervisorVersionWeigher

```cypher
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)
  AND host.hypervisor_version IS NOT NULL

WITH host, host.hypervisor_version AS version

// Normalize versions
WITH collect({host: host, version: version}) AS all_hosts
WITH all_hosts,
     reduce(max_v = 0, h IN all_hosts | CASE WHEN h.version > max_v THEN h.version ELSE max_v END) AS max_version

UNWIND all_hosts AS h
WITH h.host AS host, h.version AS version,
     toFloat(h.version) / max_version AS normalized_version

// Positive multiplier = prefer newer versions
RETURN host, version,
       normalized_version * $hypervisor_version_weight_multiplier AS version_weight
ORDER BY version_weight DESC
```

#### Combined Weigher Scoring

```cypher
// Combine all weigher scores including trait affinity
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// RAM weight
MATCH (host)-[:HAS_INVENTORY]->(mem_inv)-[:OF_CLASS]->(:ResourceClass {name: 'MEMORY_MB'})
OPTIONAL MATCH (mem_inv)<-[m_alloc:CONSUMES]-()
WITH host, (mem_inv.total - mem_inv.reserved) * mem_inv.allocation_ratio - COALESCE(sum(m_alloc.used), 0) AS free_ram

// CPU weight
MATCH (host)-[:HAS_INVENTORY]->(cpu_inv)-[:OF_CLASS]->(:ResourceClass {name: 'VCPU'})
OPTIONAL MATCH (cpu_inv)<-[c_alloc:CONSUMES]-()
WITH host, free_ram,
     (cpu_inv.total - cpu_inv.reserved) * cpu_inv.allocation_ratio - COALESCE(sum(c_alloc.used), 0) AS free_vcpus

// Trait affinity weight (preferred - avoided)
WITH host, free_ram, free_vcpus,
     reduce(pref = 0.0, p IN $preferred_traits |
       pref + CASE WHEN (host)-[:HAS_TRAIT]->(:Trait {name: p.name}) THEN p.weight ELSE 0 END
     ) AS preferred_score,
     reduce(avoid = 0.0, a IN $avoided_traits |
       avoid + CASE WHEN (host)-[:HAS_TRAIT]->(:Trait {name: a.name}) THEN a.weight ELSE 0 END
     ) AS avoided_penalty

// Calculate final weight with all components
WITH host, free_ram, free_vcpus, preferred_score, avoided_penalty,
     (free_ram / 1024.0) * $ram_weight_multiplier +
     free_vcpus * $cpu_weight_multiplier +
     (preferred_score - avoided_penalty) * $trait_weight_multiplier AS total_weight

RETURN host, free_ram, free_vcpus, preferred_score, avoided_penalty, total_weight
ORDER BY total_weight DESC
LIMIT $host_subset_size
```

### Prefilter Optimizations

#### Disabled Compute Exclusion (Mandatory)

```cypher
// Always applied - exclude disabled computes
MATCH (rp:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(rp)
  AND NOT (rp)-[:HAS_TRAIT]->(:Trait {name: 'COMPUTE_STATUS_DISABLED'})
  AND COALESCE(rp.disabled, false) = false
```

#### Image Type Support Prefilter

```cypher
// Exclude hosts that don't support image disk format
// $disk_format: 'qcow2'

MATCH (rp:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(rp)
  AND (rp)-[:HAS_TRAIT]->(:Trait {name: 'COMPUTE_IMAGE_TYPE_' + toUpper($disk_format)})
```

#### Aggregate Trait Isolation Prefilter

```cypher
// Ensure required traits match aggregate isolation requirements
// $required_traits: traits from flavor/image

MATCH (rp:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(rp)

// Get aggregates with trait requirements
OPTIONAL MATCH (rp)-[:MEMBER_OF]->(agg:Aggregate)
WHERE agg.required_traits IS NOT NULL

WITH rp, collect(agg) AS isolated_aggs

// Provider is valid if:
// 1. Not in any isolated aggregate, OR
// 2. Required traits match aggregate requirements
WHERE size(isolated_aggs) = 0 OR
      ALL(agg IN isolated_aggs WHERE
        ALL(t IN agg.required_traits WHERE t IN $required_traits)
      )

RETURN rp
```

---

## Indexes and Constraints

This section defines Neo4j indexes and constraints for optimal query
performance and data integrity.

### Uniqueness Constraints

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

// Flavor - FlavorID must be unique
CREATE CONSTRAINT flavor_flavorid_unique IF NOT EXISTS
FOR (f:Flavor)
REQUIRE f.flavorid IS UNIQUE;

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

### Property Existence Constraints

Ensure required properties are always present.

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

### Performance Indexes

Indexes for common query patterns.

```cypher
// Resource Provider indexes
CREATE INDEX rp_disabled IF NOT EXISTS
FOR (rp:ResourceProvider)
ON (rp.disabled);

CREATE INDEX rp_hypervisor_type IF NOT EXISTS
FOR (rp:ResourceProvider)
ON (rp.hypervisor_type);

// Trait name index (for trait lookups)
CREATE INDEX trait_name IF NOT EXISTS
FOR (t:Trait)
ON (t.name);

// Resource Class name index
CREATE INDEX rc_name IF NOT EXISTS
FOR (rc:ResourceClass)
ON (rc.name);

// Consumer UUID index (queries by instance UUID)
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

// PCI device address index
CREATE INDEX pci_address IF NOT EXISTS
FOR (pci:PCIDevice)
ON (pci.address);

// PCI device status index
CREATE INDEX pci_status IF NOT EXISTS
FOR (pci:PCIDevice)
ON (pci.status);
```

### Composite Indexes

For multi-property lookups.

```cypher
// Inventory lookup by provider and resource class
// (Covered by relationship traversal, but useful for direct queries)

// PCI device lookup by vendor and product
CREATE INDEX pci_vendor_product IF NOT EXISTS
FOR (pci:PCIDevice)
ON (pci.vendor_id, pci.product_id);

// Resource Provider by hypervisor type and version
CREATE INDEX rp_hv_type_version IF NOT EXISTS
FOR (rp:ResourceProvider)
ON (rp.hypervisor_type, rp.hypervisor_version);
```

### Full-Text Indexes

For searching by name patterns.

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

### Relationship Property Indexes

For queries on relationship properties.

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

### Index Usage Guidelines

#### Query Patterns and Recommended Indexes

| Query Pattern | Recommended Index | Notes |
|--------------|-------------------|-------|
| Find provider by UUID | `rp_uuid_unique` | Uniqueness constraint creates index |
| Find provider by name | `rp_name_unique` | Uniqueness constraint creates index |
| Filter disabled providers | `rp_disabled` | Bitmap index, frequent filter |
| Find traits by name | `trait_name` | Critical for trait filtering |
| Find providers by hypervisor | `rp_hypervisor_type` | Image properties filter |
| Find consumers by instance | `consumer_uuid` | Allocation lookups |
| Find aggregates by UUID | `agg_uuid` | member_of filtering |
| Find PCI by address | `pci_address` | Device lookup |
| Find PCI by vendor/product | `pci_vendor_product` | Alias resolution |

#### Index Maintenance

```cypher
// Show all indexes
SHOW INDEXES;

// Show index usage statistics
CALL db.stats.retrieve('INDEX USAGE');

// Drop unused index
DROP INDEX index_name IF EXISTS;

// Rebuild index (if needed)
// Neo4j handles this automatically, but can be triggered
CALL db.index.fulltext.createNodeIndex('rp_name_fulltext', ['ResourceProvider'], ['name']);
```

### Performance Considerations

#### Query Planning

Use `EXPLAIN` and `PROFILE` to analyze queries:

```cypher
// Explain query plan
EXPLAIN
MATCH (rp:ResourceProvider)-[:HAS_TRAIT]->(:Trait {name: 'HW_CPU_X86_AVX2'})
RETURN rp;

// Profile with actual execution metrics
PROFILE
MATCH (rp:ResourceProvider)-[:HAS_TRAIT]->(:Trait {name: 'HW_CPU_X86_AVX2'})
RETURN rp;
```

#### Relationship Traversal vs Property Lookup

```cypher
// PREFERRED: Use relationship traversal with indexed node lookup
MATCH (rp:ResourceProvider)-[:HAS_TRAIT]->(t:Trait {name: 'HW_CPU_X86_AVX2'})
RETURN rp;

// AVOID: Pattern that doesn't use index effectively
MATCH (rp:ResourceProvider)-[:HAS_TRAIT]->(t:Trait)
WHERE t.name = 'HW_CPU_X86_AVX2'
RETURN rp;
```

#### Batch Operations

For bulk updates, use UNWIND with transactions:

```cypher
// Batch create traits
UNWIND $traits AS trait_name
MERGE (t:Trait {name: trait_name})
ON CREATE SET t.standard = NOT trait_name STARTS WITH 'CUSTOM_',
              t.created_at = datetime(),
              t.updated_at = datetime();
```

---

## Telemetry Integration Hooks

This section defines interfaces for external telemetry systems (Prometheus/Aetos)
to inform scheduling decisions. The model provides hooks for real-time metrics
without storing time-series data in Neo4j.

### Telemetry Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     TELEMETRY INTEGRATION                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐        │
│  │  Prometheus  │     │    Aetos     │     │   Watcher    │        │
│  │   Server     │────►│   Service    │────►│   Service    │        │
│  └──────────────┘     └──────────────┘     └──────────────┘        │
│         │                    │                    │                 │
│         │                    │                    │                 │
│         ▼                    ▼                    ▼                 │
│  ┌─────────────────────────────────────────────────────────┐       │
│  │                  Tachyon Scheduler                       │       │
│  │  ┌───────────────────────────────────────────────────┐  │       │
│  │  │              Telemetry Plugin Interface            │  │       │
│  │  │                                                    │  │       │
│  │  │  query_metrics(provider_uuid, metric_names)        │  │       │
│  │  │  get_utilization(provider_uuid)                    │  │       │
│  │  │  register_callback(event_type, handler)            │  │       │
│  │  └───────────────────────────────────────────────────┘  │       │
│  └─────────────────────────────────────────────────────────┘       │
│                              │                                      │
│                              ▼                                      │
│                    ┌──────────────────┐                            │
│                    │     Neo4j        │                            │
│                    │  (Graph Data)    │                            │
│                    └──────────────────┘                            │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### MetricEndpoint Node

Represents a telemetry data source.

```
:MetricEndpoint
  uuid:         String!     # Unique identifier
  name:         String!     # Human-readable name
  endpoint_url: String!     # Prometheus/metrics endpoint URL
  type:         String!     # 'prometheus', 'pushgateway', 'aetos'
  scrape_interval: Integer  # Scrape interval in seconds
  enabled:      Boolean!    # Whether endpoint is active
  created_at:   DateTime!
  updated_at:   DateTime!
```

#### Metric Endpoint Creation

```cypher
CREATE (me:MetricEndpoint {
  uuid: randomUUID(),
  name: 'prometheus-main',
  endpoint_url: 'http://prometheus:9090',
  type: 'prometheus',
  scrape_interval: 15,
  enabled: true,
  created_at: datetime(),
  updated_at: datetime()
})
```

### MetricSource Relationship

Links resource providers to their metric endpoints.

```
(:ResourceProvider)-[:HAS_METRIC_SOURCE {labels}]->(:MetricEndpoint)
```

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| labels | Map | Prometheus labels for this provider (e.g., `{instance: 'compute-001:9100'}`) |
| job | String | Prometheus job name |

```cypher
// Link compute node to Prometheus endpoint
MATCH (rp:ResourceProvider {name: 'compute-001'})
MATCH (me:MetricEndpoint {name: 'prometheus-main'})
CREATE (rp)-[:HAS_METRIC_SOURCE {
  labels: {instance: 'compute-001:9100', job: 'node'},
  job: 'node'
}]->(me)
```

### Telemetry Property Placeholders

Resource providers can have placeholder properties for real-time metrics
that are populated by the telemetry plugin at query time.

```
:ResourceProvider
  // ... standard properties ...
  
  // Telemetry placeholders (populated at query time)
  _cpu_utilization:       Float     # Current CPU utilization (0-100)
  _memory_utilization:    Float     # Current memory utilization (0-100)
  _disk_io_utilization:   Float     # Current disk I/O utilization
  _network_utilization:   Float     # Current network utilization
  _load_average:          Float     # System load average
  _memory_pressure:       Float     # Memory pressure indicator
  _power_consumption:     Float     # Power consumption in watts
  _temperature:           Float     # Temperature in Celsius
```

**Note:** Properties prefixed with `_` are transient and not persisted.
They are populated by the telemetry plugin during query execution.

### Telemetry Plugin Interface

The scheduler calls the telemetry plugin to enrich queries with real-time data.

#### Python Interface Definition

```python
class TelemetryPlugin(abc.ABC):
    """Abstract interface for telemetry data providers."""
    
    @abc.abstractmethod
    def query_metrics(
        self,
        provider_uuids: List[str],
        metric_names: List[str],
        time_range: Optional[Tuple[datetime, datetime]] = None
    ) -> Dict[str, Dict[str, float]]:
        """
        Query metrics for providers.
        
        Args:
            provider_uuids: List of resource provider UUIDs
            metric_names: List of metric names to query
            time_range: Optional (start, end) for historical data
            
        Returns:
            Dict mapping provider_uuid -> {metric_name: value}
        """
        pass
    
    @abc.abstractmethod
    def get_utilization(
        self,
        provider_uuid: str
    ) -> Dict[str, float]:
        """
        Get current utilization metrics for a provider.
        
        Returns:
            Dict with keys: cpu, memory, disk_io, network
        """
        pass
    
    @abc.abstractmethod
    def register_callback(
        self,
        event_type: str,
        handler: Callable[[str, Dict], None]
    ) -> str:
        """
        Register callback for telemetry events.
        
        Args:
            event_type: 'threshold_exceeded', 'anomaly_detected', etc.
            handler: Callback function(provider_uuid, event_data)
            
        Returns:
            Registration ID
        """
        pass
```

#### Prometheus Plugin Implementation

```python
class PrometheusPlugin(TelemetryPlugin):
    """Prometheus-based telemetry plugin."""
    
    def __init__(self, prometheus_url: str):
        self.client = PrometheusConnect(url=prometheus_url)
    
    def query_metrics(self, provider_uuids, metric_names, time_range=None):
        results = {}
        for uuid in provider_uuids:
            # Get labels for this provider from Neo4j
            labels = self._get_provider_labels(uuid)
            results[uuid] = {}
            
            for metric in metric_names:
                query = f'{metric}{{{self._format_labels(labels)}}}'
                value = self.client.custom_query(query)
                results[uuid][metric] = float(value[0]['value'][1]) if value else None
        
        return results
    
    def get_utilization(self, provider_uuid):
        labels = self._get_provider_labels(provider_uuid)
        label_str = self._format_labels(labels)
        
        return {
            'cpu': self._query(f'100 - (avg(irate(node_cpu_seconds_total{{mode="idle",{label_str}}}[5m])) * 100)'),
            'memory': self._query(f'(1 - (node_memory_MemAvailable_bytes{{{label_str}}} / node_memory_MemTotal_bytes{{{label_str}}})) * 100'),
            'disk_io': self._query(f'rate(node_disk_io_time_seconds_total{{{label_str}}}[5m]) * 100'),
            'network': self._query(f'rate(node_network_receive_bytes_total{{{label_str}}}[5m]) + rate(node_network_transmit_bytes_total{{{label_str}}}[5m])')
        }
```

### Telemetry-Aware Scheduling Queries

#### Utilization-Based Weigher

Weight hosts by current resource utilization.

```cypher
// This query is enhanced by the telemetry plugin
// The plugin populates _cpu_utilization and _memory_utilization

MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)
  AND host.disabled <> true

// Plugin enriches hosts with telemetry data
// CALL tachyon.enrichWithTelemetry(collect(host))

WITH host,
     COALESCE(host._cpu_utilization, 50.0) AS cpu_util,
     COALESCE(host._memory_utilization, 50.0) AS mem_util

// Prefer hosts with lower utilization
WITH host, (100 - cpu_util) * 0.5 + (100 - mem_util) * 0.5 AS available_capacity

RETURN host, cpu_util, mem_util, available_capacity
ORDER BY available_capacity DESC
```

#### Threshold-Based Filtering

Exclude hosts exceeding utilization thresholds.

```cypher
// Filter out overloaded hosts
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)
  AND host.disabled <> true

// After telemetry enrichment
WITH host
WHERE COALESCE(host._cpu_utilization, 0) < $cpu_threshold
  AND COALESCE(host._memory_utilization, 0) < $memory_threshold

RETURN host
```

#### Power-Aware Scheduling

Consider power consumption in placement decisions.

```cypher
// Prefer hosts with lower power consumption
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

WITH host,
     COALESCE(host._power_consumption, 0) AS power_watts,
     COALESCE(host._temperature, 25) AS temp_celsius

// Penalize high power consumption and temperature
WITH host, power_watts, temp_celsius,
     CASE
       WHEN temp_celsius > 80 THEN -1000  // Critical temperature
       WHEN temp_celsius > 70 THEN -100   // High temperature
       ELSE 0
     END AS temp_penalty,
     -1 * (power_watts / 1000.0) AS power_penalty

RETURN host, power_watts, temp_celsius,
       (temp_penalty + power_penalty) * $power_weight_multiplier AS power_weight
ORDER BY power_weight DESC
```

### Event-Driven Scheduling Hooks

#### Webhook Registration

```cypher
// Register webhook for telemetry events
CREATE (wh:Webhook {
  uuid: randomUUID(),
  name: 'threshold-alert',
  url: 'http://tachyon-api:8080/webhooks/telemetry',
  event_types: ['cpu_threshold_exceeded', 'memory_threshold_exceeded'],
  enabled: true,
  created_at: datetime(),
  updated_at: datetime()
})
```

#### Threshold Alert Node

```
:ThresholdAlert
  uuid:          String!
  provider_uuid: String!     # Affected resource provider
  metric:        String!     # Metric name
  threshold:     Float!      # Threshold value
  current_value: Float!      # Current metric value
  severity:      String!     # 'warning', 'critical'
  acknowledged:  Boolean!
  created_at:    DateTime!
```

```cypher
// Create threshold alert
CREATE (alert:ThresholdAlert {
  uuid: randomUUID(),
  provider_uuid: $provider_uuid,
  metric: 'cpu_utilization',
  threshold: 90.0,
  current_value: 95.5,
  severity: 'critical',
  acknowledged: false,
  created_at: datetime()
})

// Link to provider
MATCH (rp:ResourceProvider {uuid: $provider_uuid})
CREATE (rp)-[:HAS_ALERT]->(alert)
```

#### Query with Active Alerts

```cypher
// Exclude hosts with unacknowledged critical alerts
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)
  AND NOT EXISTS {
    MATCH (host)-[:HAS_ALERT]->(alert:ThresholdAlert)
    WHERE alert.severity = 'critical'
      AND alert.acknowledged = false
  }

RETURN host
```

### Metric Definitions

Standard metrics for scheduling decisions:

| Metric Name | Description | Unit | Source |
|-------------|-------------|------|--------|
| `node_cpu_seconds_total` | CPU time | seconds | node_exporter |
| `node_memory_MemAvailable_bytes` | Available memory | bytes | node_exporter |
| `node_memory_MemTotal_bytes` | Total memory | bytes | node_exporter |
| `node_disk_io_time_seconds_total` | Disk I/O time | seconds | node_exporter |
| `node_network_receive_bytes_total` | Network RX | bytes | node_exporter |
| `node_network_transmit_bytes_total` | Network TX | bytes | node_exporter |
| `node_load1` | 1-minute load average | - | node_exporter |
| `node_hwmon_temp_celsius` | Hardware temperature | Celsius | node_exporter |
| `node_power_supply_power_watt` | Power consumption | Watts | node_exporter |

---

## Placement API Migration Mapping

This section documents the bidirectional mapping between OpenStack Placement
API operations and Tachyon Neo4j operations to enable gradual migration.

### API Endpoint Mapping

#### Resource Providers

| Placement API | HTTP | Tachyon Neo4j Operation |
|---------------|------|-------------------------|
| `GET /resource_providers` | GET | `MATCH (rp:ResourceProvider) ...` |
| `POST /resource_providers` | POST | `CREATE (rp:ResourceProvider {...})` |
| `GET /resource_providers/{uuid}` | GET | `MATCH (rp:ResourceProvider {uuid: $uuid})` |
| `PUT /resource_providers/{uuid}` | PUT | `MATCH (rp:ResourceProvider {uuid: $uuid}) SET ...` |
| `DELETE /resource_providers/{uuid}` | DELETE | `MATCH (rp:ResourceProvider {uuid: $uuid}) DETACH DELETE rp` |

**GET /resource_providers - List with filters:**

```cypher
// Placement: GET /resource_providers?name=compute&in_tree=<root_uuid>&resources=VCPU:4
MATCH (rp:ResourceProvider)

// Name filter (contains)
WHERE ($name IS NULL OR rp.name CONTAINS $name)

// in_tree filter
AND ($in_tree IS NULL OR EXISTS {
  MATCH (root:ResourceProvider {uuid: $in_tree})-[:PARENT_OF*0..]->(rp)
})

// resources filter
AND ($resources IS NULL OR ALL(req IN $resources WHERE
  EXISTS {
    MATCH (rp)-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(:ResourceClass {name: req.rc})
    OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
    WITH inv, (inv.total - inv.reserved) * inv.allocation_ratio AS capacity,
         COALESCE(sum(alloc.used), 0) AS used
    WHERE capacity - used >= req.amount
  }
))

// required traits filter
AND ($required IS NULL OR ALL(t IN $required WHERE
  (rp)-[:HAS_TRAIT]->(:Trait {name: t})
))

// member_of filter
AND ($member_of IS NULL OR EXISTS {
  MATCH (rp)-[:MEMBER_OF]->(agg:Aggregate)
  WHERE agg.uuid IN $member_of
})

RETURN rp
```

**POST /resource_providers - Create:**

```cypher
// Placement: POST /resource_providers
// Body: {"name": "compute-001", "uuid": "...", "parent_provider_uuid": "..."}

// Validate parent exists if specified
OPTIONAL MATCH (parent:ResourceProvider {uuid: $parent_provider_uuid})
WITH parent
WHERE $parent_provider_uuid IS NULL OR parent IS NOT NULL

CREATE (rp:ResourceProvider {
  uuid: COALESCE($uuid, randomUUID()),
  name: $name,
  generation: 0,
  created_at: datetime(),
  updated_at: datetime()
})

// Create parent relationship if specified
WITH rp, parent
FOREACH (_ IN CASE WHEN parent IS NOT NULL THEN [1] ELSE [] END |
  CREATE (parent)-[:PARENT_OF]->(rp)
)

RETURN rp
```

#### Inventories

| Placement API | HTTP | Tachyon Neo4j Operation |
|---------------|------|-------------------------|
| `GET /resource_providers/{uuid}/inventories` | GET | `MATCH (rp)-[:HAS_INVENTORY]->(inv)` |
| `PUT /resource_providers/{uuid}/inventories` | PUT | Replace all inventories |
| `GET /resource_providers/{uuid}/inventories/{rc}` | GET | `MATCH (rp)-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(:RC {name: $rc})` |
| `PUT /resource_providers/{uuid}/inventories/{rc}` | PUT | Create/update single inventory |
| `DELETE /resource_providers/{uuid}/inventories/{rc}` | DELETE | Delete single inventory |

**PUT /resource_providers/{uuid}/inventories - Replace all:**

```cypher
// Placement: PUT /resource_providers/{uuid}/inventories
// Body: {"inventories": {"VCPU": {...}, "MEMORY_MB": {...}}, "resource_provider_generation": 5}

MATCH (rp:ResourceProvider {uuid: $uuid})
WHERE rp.generation = $resource_provider_generation

// Delete existing inventories without allocations
OPTIONAL MATCH (rp)-[:HAS_INVENTORY]->(old_inv)
WHERE NOT (old_inv)<-[:CONSUMES]-()
DETACH DELETE old_inv

// Create new inventories
WITH rp
UNWIND keys($inventories) AS rc_name
MATCH (rc:ResourceClass {name: rc_name})

MERGE (rp)-[:HAS_INVENTORY]->(inv:Inventory)-[:OF_CLASS]->(rc)
SET inv.total = $inventories[rc_name].total,
    inv.reserved = COALESCE($inventories[rc_name].reserved, 0),
    inv.min_unit = COALESCE($inventories[rc_name].min_unit, 1),
    inv.max_unit = COALESCE($inventories[rc_name].max_unit, $inventories[rc_name].total),
    inv.step_size = COALESCE($inventories[rc_name].step_size, 1),
    inv.allocation_ratio = COALESCE($inventories[rc_name].allocation_ratio, 1.0),
    inv.updated_at = datetime()

// Increment generation
WITH rp
SET rp.generation = rp.generation + 1,
    rp.updated_at = datetime()

RETURN rp
```

#### Traits

| Placement API | HTTP | Tachyon Neo4j Operation |
|---------------|------|-------------------------|
| `GET /traits` | GET | `MATCH (t:Trait) RETURN t` |
| `PUT /traits/{name}` | PUT | `MERGE (t:Trait {name: $name})` |
| `GET /traits/{name}` | GET | `MATCH (t:Trait {name: $name})` |
| `DELETE /traits/{name}` | DELETE | `MATCH (t:Trait {name: $name}) DELETE t` |
| `GET /resource_providers/{uuid}/traits` | GET | `MATCH (rp)-[:HAS_TRAIT]->(t)` |
| `PUT /resource_providers/{uuid}/traits` | PUT | Replace all traits |

**PUT /resource_providers/{uuid}/traits - Replace all:**

```cypher
// Placement: PUT /resource_providers/{uuid}/traits
// Body: {"traits": ["HW_CPU_X86_AVX2", "CUSTOM_TRAIT1"], "resource_provider_generation": 5}

MATCH (rp:ResourceProvider {uuid: $uuid})
WHERE rp.generation = $resource_provider_generation

// Remove existing trait relationships
OPTIONAL MATCH (rp)-[r:HAS_TRAIT]->()
DELETE r

// Create new trait relationships
WITH rp
UNWIND $traits AS trait_name
MERGE (t:Trait {name: trait_name})
ON CREATE SET t.standard = NOT trait_name STARTS WITH 'CUSTOM_',
              t.created_at = datetime(),
              t.updated_at = datetime()
CREATE (rp)-[:HAS_TRAIT]->(t)

// Increment generation
WITH rp
SET rp.generation = rp.generation + 1,
    rp.updated_at = datetime()

RETURN rp
```

#### Aggregates

| Placement API | HTTP | Tachyon Neo4j Operation |
|---------------|------|-------------------------|
| `GET /resource_providers/{uuid}/aggregates` | GET | `MATCH (rp)-[:MEMBER_OF]->(agg)` |
| `PUT /resource_providers/{uuid}/aggregates` | PUT | Replace all aggregates |

**PUT /resource_providers/{uuid}/aggregates:**

```cypher
// Placement: PUT /resource_providers/{uuid}/aggregates
// Body: {"aggregates": ["agg-uuid-1", "agg-uuid-2"], "resource_provider_generation": 5}

MATCH (rp:ResourceProvider {uuid: $uuid})
WHERE rp.generation = $resource_provider_generation

// Remove existing aggregate memberships
OPTIONAL MATCH (rp)-[r:MEMBER_OF]->()
DELETE r

// Create new aggregate memberships
WITH rp
UNWIND $aggregates AS agg_uuid
MERGE (agg:Aggregate {uuid: agg_uuid})
ON CREATE SET agg.created_at = datetime(),
              agg.updated_at = datetime()
CREATE (rp)-[:MEMBER_OF]->(agg)

// Increment generation
WITH rp
SET rp.generation = rp.generation + 1,
    rp.updated_at = datetime()

RETURN rp
```

#### Allocations

| Placement API | HTTP | Tachyon Neo4j Operation |
|---------------|------|-------------------------|
| `GET /allocations/{consumer_uuid}` | GET | `MATCH (c:Consumer {uuid})-[:CONSUMES]->()` |
| `PUT /allocations/{consumer_uuid}` | PUT | Replace consumer allocations |
| `DELETE /allocations/{consumer_uuid}` | DELETE | Delete all consumer allocations |
| `POST /allocations` | POST | Bulk reshaper operation |

**GET /allocations/{consumer_uuid}:**

```cypher
// Placement: GET /allocations/{consumer_uuid}

MATCH (c:Consumer {uuid: $consumer_uuid})
OPTIONAL MATCH (c)-[alloc:CONSUMES]->(inv)-[:OF_CLASS]->(rc:ResourceClass)
OPTIONAL MATCH (inv)<-[:HAS_INVENTORY]-(rp:ResourceProvider)
OPTIONAL MATCH (c)-[:OWNED_BY]->(proj:Project)
OPTIONAL MATCH (c)-[:CREATED_BY]->(user:User)

RETURN {
  allocations: collect({
    resource_provider: {uuid: rp.uuid},
    resources: {[rc.name]: alloc.used}
  }),
  consumer_generation: c.generation,
  project_id: proj.external_id,
  user_id: user.external_id
} AS allocation_data
```

**PUT /allocations/{consumer_uuid}:**

```cypher
// Placement: PUT /allocations/{consumer_uuid}
// Body: {"allocations": {"rp-uuid": {"resources": {"VCPU": 4}}}, 
//        "project_id": "...", "user_id": "...", "consumer_generation": 0}

// Check provider generations
UNWIND keys($allocations) AS rp_uuid
MATCH (rp:ResourceProvider {uuid: rp_uuid})
WHERE rp.generation = $allocations[rp_uuid].generation
WITH collect(rp) AS providers, count(*) AS provider_count
WHERE provider_count = size(keys($allocations))

// Get or create consumer
MERGE (c:Consumer {uuid: $consumer_uuid})
ON CREATE SET c.generation = 0, c.created_at = datetime()

// Check consumer generation
WITH c
WHERE $consumer_generation IS NULL OR c.generation = $consumer_generation

// Link to project and user
MERGE (proj:Project {external_id: $project_id})
MERGE (user:User {external_id: $user_id})
MERGE (c)-[:OWNED_BY]->(proj)
MERGE (c)-[:CREATED_BY]->(user)

// Remove existing allocations
OPTIONAL MATCH (c)-[old:CONSUMES]->()
DELETE old

// Create new allocations
WITH c
UNWIND keys($allocations) AS rp_uuid
UNWIND keys($allocations[rp_uuid].resources) AS rc_name
MATCH (rp:ResourceProvider {uuid: rp_uuid})-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(:ResourceClass {name: rc_name})
CREATE (c)-[:CONSUMES {
  used: $allocations[rp_uuid].resources[rc_name],
  created_at: datetime(),
  updated_at: datetime()
}]->(inv)

// Increment consumer generation
WITH c
SET c.generation = c.generation + 1,
    c.updated_at = datetime()

RETURN c
```

#### Allocation Candidates

| Placement API | HTTP | Tachyon Neo4j Operation |
|---------------|------|-------------------------|
| `GET /allocation_candidates` | GET | Complex graph query (see Cypher examples) |

**Query parameter mapping:**

| Placement Parameter | Tachyon Equivalent |
|--------------------|--------------------|
| `resources` | Filter on HAS_INVENTORY with capacity check |
| `required` | ALL traits must exist via HAS_TRAIT |
| `forbidden` | NONE of traits exist via HAS_TRAIT |
| `member_of` | MEMBER_OF aggregate relationship |
| `in_tree` | PARENT_OF path from specified root |
| `limit` | LIMIT clause |
| `group_policy` | Provider isolation in result grouping |

#### Usages

| Placement API | HTTP | Tachyon Neo4j Operation |
|---------------|------|-------------------------|
| `GET /resource_providers/{uuid}/usages` | GET | Sum CONSUMES.used per resource class |
| `GET /usages?project_id=X` | GET | Sum by project across all providers |

**GET /resource_providers/{uuid}/usages:**

```cypher
MATCH (rp:ResourceProvider {uuid: $uuid})-[:HAS_INVENTORY]->(inv)-[:OF_CLASS]->(rc:ResourceClass)
OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()

WITH rc.name AS resource_class, COALESCE(sum(alloc.used), 0) AS usage
RETURN {usages: collect({resource_class: resource_class, usage: usage})} AS result
```

#### Resource Classes

| Placement API | HTTP | Tachyon Neo4j Operation |
|---------------|------|-------------------------|
| `GET /resource_classes` | GET | `MATCH (rc:ResourceClass) RETURN rc` |
| `POST /resource_classes` | POST | `CREATE (rc:ResourceClass {name: $name})` |
| `GET /resource_classes/{name}` | GET | `MATCH (rc:ResourceClass {name: $name})` |
| `PUT /resource_classes/{name}` | PUT | Update custom resource class |
| `DELETE /resource_classes/{name}` | DELETE | Delete custom resource class |

### Data Migration Scripts

#### Export from Placement to Neo4j

```python
# Python migration script outline
def migrate_placement_to_tachyon(placement_client, neo4j_driver):
    """Migrate all Placement data to Tachyon Neo4j."""
    
    # 1. Migrate resource classes
    for rc in placement_client.get_resource_classes():
        with neo4j_driver.session() as session:
            session.run("""
                MERGE (rc:ResourceClass {name: $name})
                SET rc.standard = $standard,
                    rc.created_at = datetime()
            """, name=rc.name, standard=not rc.name.startswith('CUSTOM_'))
    
    # 2. Migrate traits
    for trait in placement_client.get_traits():
        with neo4j_driver.session() as session:
            session.run("""
                MERGE (t:Trait {name: $name})
                SET t.standard = $standard,
                    t.created_at = datetime()
            """, name=trait.name, standard=not trait.name.startswith('CUSTOM_'))
    
    # 3. Migrate resource providers (with hierarchy)
    providers = placement_client.get_resource_providers()
    # Sort by parent to ensure parents created first
    sorted_providers = topological_sort_by_parent(providers)
    
    for rp in sorted_providers:
        with neo4j_driver.session() as session:
            session.run("""
                CREATE (rp:ResourceProvider {
                    uuid: $uuid,
                    name: $name,
                    generation: $generation,
                    created_at: datetime()
                })
                
                WITH rp
                OPTIONAL MATCH (parent:ResourceProvider {uuid: $parent_uuid})
                FOREACH (_ IN CASE WHEN parent IS NOT NULL THEN [1] ELSE [] END |
                    CREATE (parent)-[:PARENT_OF]->(rp)
                )
            """, uuid=rp.uuid, name=rp.name, generation=rp.generation,
                 parent_uuid=rp.parent_provider_uuid)
    
    # 4. Migrate inventories
    for rp in providers:
        inventories = placement_client.get_inventories(rp.uuid)
        for rc_name, inv in inventories.items():
            with neo4j_driver.session() as session:
                session.run("""
                    MATCH (rp:ResourceProvider {uuid: $rp_uuid})
                    MATCH (rc:ResourceClass {name: $rc_name})
                    CREATE (rp)-[:HAS_INVENTORY]->(inv:Inventory {
                        total: $total,
                        reserved: $reserved,
                        min_unit: $min_unit,
                        max_unit: $max_unit,
                        step_size: $step_size,
                        allocation_ratio: $allocation_ratio,
                        created_at: datetime()
                    })-[:OF_CLASS]->(rc)
                """, rp_uuid=rp.uuid, rc_name=rc_name, **inv)
    
    # 5. Migrate traits associations
    for rp in providers:
        traits = placement_client.get_provider_traits(rp.uuid)
        with neo4j_driver.session() as session:
            session.run("""
                MATCH (rp:ResourceProvider {uuid: $rp_uuid})
                UNWIND $traits AS trait_name
                MATCH (t:Trait {name: trait_name})
                CREATE (rp)-[:HAS_TRAIT]->(t)
            """, rp_uuid=rp.uuid, traits=traits)
    
    # 6. Migrate aggregates
    # ... similar pattern
    
    # 7. Migrate allocations
    for consumer_uuid in placement_client.get_consumer_uuids():
        allocations = placement_client.get_allocations(consumer_uuid)
        # ... create Consumer and CONSUMES relationships
```

### Compatibility Layer

For gradual migration, Tachyon can expose a Placement-compatible REST API:

```python
# Flask/FastAPI route example
@app.get("/placement/resource_providers")
async def list_resource_providers(
    name: Optional[str] = None,
    in_tree: Optional[str] = None,
    resources: Optional[str] = None,
    required: Optional[str] = None,
    member_of: Optional[str] = None
):
    """Placement-compatible resource providers list."""
    
    query = build_cypher_query(name, in_tree, resources, required, member_of)
    
    with neo4j_driver.session() as session:
        result = session.run(query)
        
    return {
        "resource_providers": [
            {
                "uuid": r["rp"].get("uuid"),
                "name": r["rp"].get("name"),
                "generation": r["rp"].get("generation"),
                "root_provider_uuid": r["root_uuid"],
                "parent_provider_uuid": r["parent_uuid"]
            }
            for r in result
        ]
    }
```

---

## Use Case Coverage Matrix

This section cross-references the use cases from [usecases.md](usecases.md)
with Tachyon graph model components that support them.

### Tachyon-Specific Use Cases

| Use Case | Model Components | Key Queries |
|----------|------------------|-------------|
| Prefer hosts matching resources without unused capabilities | Weigher combining resource availability and trait count | `PCIWeigher` pattern, trait-aware weighing |
| Optimize heterogeneous infrastructure | Multi-resource weighing with trait penalties | Combined weigher with negative trait scores |
| Better placement for custom resource classes | Native resource class support | Standard `HAS_INVENTORY` pattern |
| Preferred traits (soft affinity) | `:REQUIRES_TRAIT {constraint: 'preferred', weight}` | TraitAffinityWeigher with positive scoring |
| Avoided traits (soft anti-affinity) | `:REQUIRES_TRAIT {constraint: 'avoided', weight}` | TraitAffinityWeigher with negative penalty |
| Weighted trait preferences | `weight` property on soft trait constraints | Per-trait weight in scoring calculation |
| Real-time consumable resource view | Graph query over entire topology | Tree traversal with inventory aggregation |
| Translate PCI alias to resource requirements | `:PCIAlias` node linking to traits/resources | Alias resolution query |
| Watcher: versioned notifications | Event nodes with version properties | Stream of change events |
| Watcher: Enhanced Platform Awareness (NUMA, hugepages, etc.) | Full NUMA/PCI hierarchy in graph | Subtree queries for topology |
| Watcher: network availability tracking | Physnet traits, bandwidth inventory | Network-aware allocation candidates |
| Watcher: live migration constraints | Hypervisor version properties, storage traits | Compatibility filtering queries |
| Notification volume control | Delta-based change tracking | Incremental sync patterns |

### Resource Allocation and Quantitative Scheduling

| Use Case | Model Components | Implementation |
|----------|------------------|----------------|
| Basic compute resources (VCPU, MEMORY_MB, DISK_GB) | `:Inventory` nodes, `:ResourceClass` | Standard inventory pattern |
| Configurable allocation ratios (override mode) | `allocation_ratio` property on Inventory | Capacity calculation in queries |
| Configurable allocation ratios (initial mode) | Same property, external update allowed | API for ratio updates |
| Reserved host resources | `reserved` property on Inventory | Subtracted in capacity calculation |
| Custom resource classes | `:ResourceClass` with CUSTOM_ prefix | Same pattern as standard classes |
| Nested resource provider trees | `:PARENT_OF` relationship | Tree traversal queries |
| Sharing resource providers | `:SHARES_RESOURCES` relationship | Sharing provider inclusion in candidates |
| Granular resource groups with isolation | Group suffix in allocations, `group_policy` | Multi-group allocation queries |

### Qualitative Scheduling via Traits

| Use Case | Model Components | Implementation |
|----------|------------------|----------------|
| Required traits (`trait:X=required`) | `:HAS_TRAIT` relationship, hard filter | `ALL(trait IN required WHERE ...)` |
| Forbidden traits (`trait:X=forbidden`) | Absence of `:HAS_TRAIT`, hard filter | `NONE(trait IN forbidden WHERE ...)` |
| Preferred traits (`trait:X=preferred`) | `:REQUIRES_TRAIT {constraint: 'preferred'}` | TraitAffinityWeigher positive score |
| Avoided traits (`trait:X=avoided`) | `:REQUIRES_TRAIT {constraint: 'avoided'}` | TraitAffinityWeigher negative penalty |
| Weighted soft traits | `weight` property on REQUIRES_TRAIT | Weighted scoring in TraitAffinityWeigher |
| Any-of traits (OR) | `:HAS_TRAIT` with ANY predicate | `ANY(trait IN traits WHERE ...)` |
| Root provider traits | Trait check on root of tree | Root traversal + trait check |
| Auto-reported compute capabilities | Traits synced to `:ResourceProvider` | Compute driver trait sync |
| Image metadata traits | Image properties to trait matching | Image property extraction |

### Host Aggregates and Availability Zones

| Use Case | Model Components | Implementation |
|----------|------------------|----------------|
| Host aggregates with metadata | `:Aggregate` node with properties | Property matching in filters |
| Tenant isolation (filter_tenant_id) | `:TENANT_ALLOWED` relationship | Tenant isolation constraint query |
| Availability zones | `:AvailabilityZone` node, `:DEFINES_AZ` | AZ membership query |
| Per-aggregate weight multipliers | Aggregate properties for weights | Multiplier lookup in weighers |
| Image-to-aggregate isolation | `:IMAGE_ALLOWED` relationship | Image isolation query |

### Server Groups (Affinity and Anti-Affinity)

| Use Case | Model Components | Implementation |
|----------|------------------|----------------|
| Affinity policy | `:ServerGroup`, `:HAS_MEMBER`, `:SCHEDULED_ON` | Same-host constraint query |
| Anti-affinity policy | Same relationships | Different-host constraint query |
| Soft-affinity | Same relationships | Affinity weigher (count members) |
| Soft-anti-affinity | Same relationships | Anti-affinity weigher (negative count) |
| max_server_per_host | `rules` property on ServerGroup | Count-based filtering |

### NUMA Topology and CPU Management

| Use Case | Model Components | Implementation |
|----------|------------------|----------------|
| NUMA-aware scheduling | `:NUMANode` nested providers | NUMA topology filter query |
| Dedicated CPU pinning | `cpuset`, `pcpuset` on NUMANode | CPU availability tracking |
| Mixed CPU policy | Per-NUMA CPU inventories | Split dedicated/shared inventory |
| Emulator thread pinning | Emulator CPU pool tracking | Separate inventory for emulator |
| CPU thread policies | SMT/sibling information | Thread topology in NUMANode |
| Custom CPU topology | vCPU topology properties | Flavor extra spec parsing |
| NUMA-aware live migration | NUMA state in migration context | Pre-migration NUMA fitting |

### Memory Management

| Use Case | Model Components | Implementation |
|----------|------------------|----------------|
| Huge pages (2MB, 1GB) | `hugepages` map on NUMANode | Hugepage inventory per size |
| Hugepages + NUMA affinity | Combined NUMA + hugepage query | Single NUMA node satisfaction |
| Restrict hugepage usage | Flavor extra spec validation | Policy enforcement in allocation |

### PCI Passthrough and SR-IOV

| Use Case | Model Components | Implementation |
|----------|------------------|----------------|
| PCI device passthrough | `:PCIDevice`, `:PCIPF`, `:PCIVF` nodes | PCI device allocation query |
| PCI device specifications | Vendor/product ID properties | Device matching filters |
| PCI aliases | Trait-based alias resolution | Alias to trait/resource mapping |
| SR-IOV virtual functions | VF hierarchy under PF | VF allocation in tree |
| PCI-NUMA affinity policies | `:NUMA_AFFINITY` relationship | NUMA-aware PCI allocation |
| PCI devices in Placement | Resource class per device type | Standard inventory pattern |
| Trusted VFs | Trait on VF provider | Trait filtering |
| Remote-managed devices (SmartNIC) | Specific traits for DPU | Trait-based exclusion |

### Virtual GPUs (vGPU)

| Use Case | Model Components | Implementation |
|----------|------------------|----------------|
| vGPU resources | `:PhysicalGPU`, `:vGPUType` hierarchy | vGPU inventory allocation |
| Multiple vGPU types per GPU | Multiple vGPU type children | Type selection in query |
| vGPU as child resource providers | `:PARENT_OF` from GPU to type | Tree allocation pattern |
| Custom traits for vGPU types | Traits on vGPU type providers | Trait-based vGPU selection |
| vGPU live migration | Migration-compatible trait | Trait check in migration |

### Network-Aware Scheduling

| Use Case | Model Components | Implementation |
|----------|------------------|----------------|
| Neutron ports with resource requests | Resource requests from port | Extended allocation candidates |
| SR-IOV ports by physnet | Physnet traits on PF/VF | Trait-filtered VF allocation |
| Extended resource requests (BW + PPS) | Multiple resource groups | Group-based allocation |
| group_policy for VF isolation | Provider isolation in query | Different-provider constraint |

### Scheduler Prefilters

| Use Case | Model Components | Implementation |
|----------|------------------|----------------|
| Exclude unsupported disk formats | `COMPUTE_IMAGE_TYPE_*` traits | Trait presence check |
| Exclude disabled computes | `COMPUTE_STATUS_DISABLED` trait | Mandatory prefilter |
| Aggregate trait isolation | Required traits on aggregates | Aggregate trait matching |

### Scheduler Filters

| Use Case | Model Components | Implementation |
|----------|------------------|----------------|
| ComputeFilter | `disabled` property, status trait | Basic filter query |
| ImagePropertiesFilter | Image properties to traits | Property-based trait matching |
| NUMATopologyFilter | NUMA node providers | NUMA fitting query |
| PciPassthroughFilter | PCI device providers | PCI availability query |
| ServerGroupAffinityFilter | Server group relationships | Affinity constraint query |
| ServerGroupAntiAffinityFilter | Same | Anti-affinity constraint query |
| AggregateInstanceExtraSpecsFilter | Aggregate properties | Property matching |
| AggregateImagePropertiesIsolation | `:IMAGE_ALLOWED` | Isolation query |
| AggregateMultiTenancyIsolation | `:TENANT_ALLOWED` | Tenant isolation query |
| AggregateIoOpsFilter | Aggregate I/O limits | Workload counting |
| AggregateNumInstancesFilter | Aggregate instance limits | Instance counting |
| ComputeCapabilitiesFilter | Provider properties | Property comparison |
| IoOpsFilter | Task state tracking | I/O operation count |
| NumInstancesFilter | Instance relationship count | Count query |
| IsolatedHostsFilter | Isolated hosts/images lists | List membership check |
| DifferentHostFilter | `:SCHEDULED_ON` relationship | Host exclusion query |
| SameHostFilter | Same | Host inclusion query |
| AllHostsFilter | No filter | Pass-through |

### Scheduler Weighers

| Use Case | Model Components | Implementation |
|----------|------------------|----------------|
| RAMWeigher | MEMORY_MB inventory | Capacity-based weighing |
| CPUWeigher | VCPU inventory | Same pattern |
| DiskWeigher | DISK_GB inventory | Same pattern |
| IoOpsWeigher | Task state properties | Workload-based weighing |
| PCIWeigher | PCI device availability | PCI-aware weighing |
| BuildFailureWeigher | Failure count property | Failure penalty weighing |
| ServerGroupSoftAffinityWeigher | Group membership count | Affinity scoring |
| ServerGroupSoftAntiAffinityWeigher | Same | Anti-affinity scoring |
| MetricsWeigher | Telemetry hooks | External metric integration |
| CrossCellWeigher | Cell relationship | Cell locality scoring |
| HypervisorVersionWeigher | `hypervisor_version` property | Version-based weighing |
| NumInstancesWeigher | Instance count | Instance density weighing |
| ImagePropertiesWeigher | Image property matching | Co-location weighing |
| TraitAffinityWeigher | Preferred/avoided trait scoring | Soft trait constraint weighing |
| Per-aggregate weight multipliers | Aggregate properties | Multiplier lookup |
| host_subset_size | LIMIT clause | Random selection from top N |

### Instance Lifecycle and Move Operations

| Use Case | Model Components | Implementation |
|----------|------------------|----------------|
| Live migration validation | Constraint checking | Full constraint query |
| Cold migration (resize) | New allocation candidates | Standard candidates query |
| Evacuate operations | Host exclusion + candidates | Modified candidates query |
| Unshelve operations | Full scheduling | Standard scheduling flow |
| Cross-cell migration | Cell relationships | Cell-aware allocation |

### Cells Scheduling Considerations

| Use Case | Model Components | Implementation |
|----------|------------------|----------------|
| Enable/disable cells | `disabled` on Cell node | Cell filtering in queries |
| Pre-disabled cells | Create Cell with disabled=true | Initial state support |
| Cell changes take effect | Query always checks state | Real-time cell status |

### Placement Query Features

| Use Case | Model Components | Implementation |
|----------|------------------|----------------|
| Allocation candidates API | Full candidates query | Core scheduling query |
| member_of query | `:MEMBER_OF` relationship | Aggregate membership filter |
| in_tree filtering | `:PARENT_OF` path | Tree membership filter |
| same_subtree constraints | Common ancestor query | Ancestor matching |
| Resourceless request groups | Trait-only groups | Trait filtering without resources |
| Forbidden aggregate membership | Aggregate exclusion | NOT in aggregate query |

---

## Appendix: Quick Reference

### Node Labels

```
:ResourceProvider, :Inventory, :Consumer, :ResourceClass, :Trait,
:Aggregate, :Project, :User, :ConsumerType, :Flavor, :Image,
:ServerGroup, :AvailabilityZone, :Cell, :NUMANode, :PCIDevice,
:PCIPF, :PCIVF, :PhysicalGPU, :vGPUType, :ComputeHost,
:MetricEndpoint, :ThresholdAlert, :Webhook
```

### Relationship Types

```
:PARENT_OF, :HAS_INVENTORY, :OF_CLASS, :HAS_TRAIT, :MEMBER_OF,
:CONSUMES, :OWNED_BY, :CREATED_BY, :OF_TYPE, :DEFINES_AZ,
:LOCATED_IN, :HAS_MEMBER, :SCHEDULED_ON, :REQUIRES_TRAIT,
:REQUIRES_RESOURCE, :SHARES_RESOURCES, :NUMA_AFFINITY,
:TENANT_ALLOWED, :IMAGE_ALLOWED, :HAS_PCI_DEVICE, :PCI_PARENT_OF,
:HAS_NUMA_NODE, :HAS_METRIC_SOURCE, :HAS_ALERT
```

### Key Property Patterns

```cypher
// Optimistic concurrency
WHERE node.generation = $expected_generation
SET node.generation = node.generation + 1

// Capacity calculation
(inv.total - inv.reserved) * inv.allocation_ratio AS capacity

// Usage calculation
OPTIONAL MATCH (inv)<-[c:CONSUMES]-()
WITH inv, COALESCE(sum(c.used), 0) AS usage

// Availability
capacity - usage AS available
```

### Trait Constraint Types

| Constraint | Type | Extra Spec Syntax | Behavior |
|------------|------|-------------------|----------|
| `required` | Hard | `trait:X=required` | MUST have trait (filter) |
| `forbidden` | Hard | `trait:X=forbidden` | MUST NOT have trait (filter) |
| `preferred` | Soft | `trait:X=preferred` | Prefer hosts WITH trait (weigher +) |
| `avoided` | Soft | `trait:X=avoided` | Prefer hosts WITHOUT trait (weigher -) |

```cypher
// Hard constraints (filter stage)
WHERE ALL(t IN required_traits WHERE (rp)-[:HAS_TRAIT]->(:Trait {name: t}))
  AND NONE(t IN forbidden_traits WHERE (rp)-[:HAS_TRAIT]->(:Trait {name: t}))

// Soft constraints (weigher stage)
WITH rp,
     reduce(s = 0.0, p IN preferred | s + CASE WHEN (rp)-[:HAS_TRAIT]->(:Trait {name: p.name}) THEN p.weight ELSE 0 END) -
     reduce(s = 0.0, a IN avoided | s + CASE WHEN (rp)-[:HAS_TRAIT]->(:Trait {name: a.name}) THEN a.weight ELSE 0 END)
     AS trait_affinity_score
```

### Document References

- [placement-model.md](placement-model.md) - OpenStack Placement data model
- [nova-model.md](nova-model.md) - Nova scheduling entities and extra specs
- [scheduling-overview.md](scheduling-overview.md) - Nova filter/weigher implementations
- [usecases.md](usecases.md) - Required use case coverage

---

**Document Version:** 1.0  
**Last Updated:** 2025-12-06  
**Target Audience:** Developers, operators, LLMs implementing Tachyon


