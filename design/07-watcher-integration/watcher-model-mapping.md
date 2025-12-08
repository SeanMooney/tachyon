---
title: Watcher Model Mapping
description: Mapping Watcher entities to Tachyon graph nodes and relationships
keywords: [watcher, mapping, compute-node, instance, storage, baremetal, networkx]
related:
  - 07-watcher-integration/README.md
  - 07-watcher-integration/simulation-sessions.md
  - 01-schema/nodes/resource-provider.md
  - 01-schema/nodes/consumer.md
implements:
  - "Watcher data model delegation"
section: watcher-integration
---

# Watcher Model Mapping

This document describes how Watcher's in-memory data model (NetworkX-based) maps to Tachyon's graph schema. This mapping enables Watcher's decision engine to delegate data model management to Tachyon while maintaining full compatibility with existing strategies.

## Overview

Watcher currently maintains three in-memory cluster data models:

1. **ModelRoot** (Compute): Compute nodes and instances
2. **StorageModelRoot**: Storage nodes, pools, and volumes
3. **BaremetalModelRoot**: Ironic (baremetal) nodes

Each is implemented as a NetworkX DiGraph with custom node attributes. Tachyon provides a richer graph schema that encompasses all three models with additional relationship semantics.

## Compute Model Mapping

### ComputeNode → ResourceProvider

Watcher's `ComputeNode` element maps to a Tachyon `ResourceProvider` node with associated `Inventory` nodes:

| Watcher `ComputeNode` Field | Tachyon Location |
|---------------------------|------------------|
| `uuid` | `(:ResourceProvider).uuid` |
| `hostname` | `(:ResourceProvider).name` |
| `state` | `(:ResourceProvider)-[:HAS_TRAIT]->(:Trait {name: 'COMPUTE_STATUS_*'})` |
| `status` | `(:ResourceProvider).status` or trait |
| `disabled_reason` | `(:ResourceProvider).disabled_reason` |
| `memory` (total) | `(:Inventory {resource_class: 'MEMORY_MB'}).total` |
| `memory_ratio` | `(:Inventory {resource_class: 'MEMORY_MB'}).allocation_ratio` |
| `memory_mb_reserved` | `(:Inventory {resource_class: 'MEMORY_MB'}).reserved` |
| `disk` (total) | `(:Inventory {resource_class: 'DISK_GB'}).total` |
| `disk_ratio` | `(:Inventory {resource_class: 'DISK_GB'}).allocation_ratio` |
| `disk_gb_reserved` | `(:Inventory {resource_class: 'DISK_GB'}).reserved` |
| `vcpus` (total) | `(:Inventory {resource_class: 'VCPU'}).total` |
| `vcpu_ratio` | `(:Inventory {resource_class: 'VCPU'}).allocation_ratio` |
| `vcpu_reserved` | `(:Inventory {resource_class: 'VCPU'}).reserved` |

**Cypher Representation:**

```cypher
// ComputeNode in Tachyon
(:ResourceProvider {
  uuid: 'node-uuid',
  name: 'compute-host-1',
  status: 'enabled',
  disabled_reason: null,
  generation: 5
})
-[:HAS_INVENTORY]->(:Inventory {
  total: 128,
  reserved: 4,
  allocation_ratio: 16.0,
  min_unit: 1,
  max_unit: 128
})
-[:OF_CLASS]->(:ResourceClass {name: 'VCPU'})
```

### Instance → Consumer

Watcher's `Instance` element maps to a Tachyon `Consumer` node with `CONSUMES` relationships:

| Watcher `Instance` Field | Tachyon Location |
|------------------------|------------------|
| `uuid` | `(:Consumer).uuid` |
| `name` | `(:Consumer).name` |
| `state` | `(:Consumer).state` or trait |
| `memory` | `(:Consumer)-[:CONSUMES {used: N}]->(:Inventory {resource_class: 'MEMORY_MB'})` |
| `disk` | `(:Consumer)-[:CONSUMES {used: N}]->(:Inventory {resource_class: 'DISK_GB'})` |
| `vcpus` | `(:Consumer)-[:CONSUMES {used: N}]->(:Inventory {resource_class: 'VCPU'})` |
| `metadata` | `(:Consumer).metadata` |
| `project_id` | `(:Consumer)-[:OWNED_BY]->(:Project {external_id: 'project-uuid'})` |
| `locked` | `(:Consumer).locked` |
| `watcher_exclude` | `(:Consumer).watcher_exclude` |
| `pinned_az` | `(:Consumer)-[:PINNED_TO]->(:AvailabilityZone)` |
| `flavor_extra_specs` | `(:Consumer)-[:OF_TYPE]->(:Flavor)-[:HAS_EXTRA_SPEC]->(:ExtraSpec)` |

**Cypher Representation:**

```cypher
// Instance in Tachyon
(:Consumer {
  uuid: 'instance-uuid',
  name: 'my-instance',
  state: 'active',
  generation: 2,
  locked: false,
  watcher_exclude: false,
  metadata: {key: 'value'}
})
-[:CONSUMES {used: 4, created_at: datetime()}]->(:Inventory)
-[:OF_CLASS]->(:ResourceClass {name: 'VCPU'})
```

### Instance-to-Node Mapping

Watcher uses NetworkX edges to map instances to compute nodes. In Tachyon, this is implicit through the `CONSUMES` relationship chain:

```
Watcher (NetworkX):
  add_edge(instance.uuid, node.uuid)

Tachyon (Neo4j):
  (consumer:Consumer)-[:CONSUMES]->(inv:Inventory)<-[:HAS_INVENTORY]-(rp:ResourceProvider)
```

**Query to get node for an instance:**

```cypher
// Equivalent to Watcher's get_node_by_instance_uuid()
MATCH (consumer:Consumer {uuid: $instance_uuid})
      -[:CONSUMES]->(:Inventory)
      <-[:HAS_INVENTORY]-(rp:ResourceProvider)
RETURN DISTINCT rp
```

## Watcher Operations → Tachyon Queries

### get_all_compute_nodes()

```cypher
// Get all compute nodes
MATCH (rp:ResourceProvider)
WHERE (rp)-[:HAS_TRAIT]->(:Trait {name: 'COMPUTE_HYPERVISOR'})
   OR NOT (rp)<-[:PARENT_OF]-()  // Root providers
RETURN rp
```

### get_all_instances()

```cypher
// Get all instances (consumers of compute resources)
MATCH (consumer:Consumer)
      -[:CONSUMES]->(:Inventory)
      -[:OF_CLASS]->(:ResourceClass {name: 'VCPU'})
RETURN DISTINCT consumer
```

### get_node_instances(node)

```cypher
// Get all instances on a specific compute node
MATCH (rp:ResourceProvider {uuid: $node_uuid})
      -[:HAS_INVENTORY]->(inv)
      <-[:CONSUMES]-(consumer:Consumer)
RETURN DISTINCT consumer
```

### get_node_used_resources(node)

```cypher
// Get resource usage on a compute node
MATCH (rp:ResourceProvider {uuid: $node_uuid})
      -[:HAS_INVENTORY]->(inv)
      -[:OF_CLASS]->(rc:ResourceClass)
OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-(:Consumer)
WITH rc.name AS resource_class, COALESCE(sum(alloc.used), 0) AS used
RETURN collect({resource: resource_class, used: used}) AS usage
```

### get_node_free_resources(node)

```cypher
// Get free resources on a compute node
MATCH (rp:ResourceProvider {uuid: $node_uuid})
      -[:HAS_INVENTORY]->(inv)
      -[:OF_CLASS]->(rc:ResourceClass)
OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-(:Consumer)
WITH rc.name AS resource_class,
     inv.total AS total,
     inv.reserved AS reserved,
     inv.allocation_ratio AS ratio,
     COALESCE(sum(alloc.used), 0) AS used
WITH resource_class,
     (total - reserved) * ratio AS capacity,
     used
RETURN collect({
  resource: resource_class,
  capacity: capacity,
  used: used,
  free: capacity - used
}) AS resources
```

### migrate_instance(instance, source, destination)

In simulation mode, this becomes a delta operation:

```cypher
// Record speculative migration in simulation session
MATCH (s:SimulationSession {id: $session_id})
MATCH (consumer:Consumer {uuid: $instance_uuid})
      -[alloc:CONSUMES]->(inv)
      -[:OF_CLASS]->(rc:ResourceClass)
      
// Get current resource amounts
WITH s, consumer, collect({resource: rc.name, amount: alloc.used}) AS resources

// Get next sequence
OPTIONAL MATCH (s)-[:HAS_DELTA]->(existing:SpeculativeDelta)
WITH s, consumer, resources, COALESCE(max(existing.sequence), 0) + 1 AS next_seq

// Create MOVE delta
CREATE (s)-[:HAS_DELTA]->(d:SpeculativeDelta {
  sequence: next_seq,
  type: 'MOVE',
  consumer_uuid: consumer.uuid,
  from_provider: $source_node_uuid,
  to_provider: $dest_node_uuid,
  resource_changes: resources,
  created_at: datetime()
})

RETURN d
```

For actual commitment (non-simulation):

```cypher
// Atomic migration in global graph
MATCH (consumer:Consumer {uuid: $instance_uuid})
WHERE consumer.generation = $expected_generation

// Remove old allocations from source
MATCH (consumer)-[old_alloc:CONSUMES]->(old_inv)
      <-[:HAS_INVENTORY]-(source:ResourceProvider {uuid: $source_uuid})
DELETE old_alloc

// Create new allocations on destination
WITH consumer
UNWIND $allocations AS alloc
MATCH (dest:ResourceProvider {uuid: $dest_uuid})
      -[:HAS_INVENTORY]->(inv)
      -[:OF_CLASS]->(:ResourceClass {name: alloc.resource_class})
CREATE (consumer)-[:CONSUMES {used: alloc.used, created_at: datetime()}]->(inv)

// Increment consumer generation
SET consumer.generation = consumer.generation + 1

RETURN consumer
```

## Storage Model Mapping

### StorageNode → ResourceProvider

| Watcher `StorageNode` Field | Tachyon Location |
|---------------------------|------------------|
| `host` | `(:ResourceProvider).name` |
| `zone` | `(:ResourceProvider)-[:LOCATED_IN]->(:AvailabilityZone)` |
| `status` | `(:ResourceProvider).status` |
| `volume_type` | `(:ResourceProvider)-[:HAS_TRAIT]->(:Trait {name: 'STORAGE_TYPE_*'})` |

### Pool → ResourceProvider (child)

Storage pools are modeled as child resource providers:

```cypher
(:ResourceProvider {name: 'storage-host'})
-[:PARENT_OF]->(:ResourceProvider {name: 'pool-1'})
-[:HAS_INVENTORY]->(:Inventory)
-[:OF_CLASS]->(:ResourceClass {name: 'DISK_GB'})
```

### Volume → Consumer

| Watcher `Volume` Field | Tachyon Location |
|----------------------|------------------|
| `uuid` | `(:Consumer).uuid` |
| `name` | `(:Consumer).name` |
| `size` | `(:Consumer)-[:CONSUMES {used: N}]->(:Inventory {resource_class: 'DISK_GB'})` |
| `status` | `(:Consumer).status` |
| `attachments` | `(:Consumer)-[:ATTACHED_TO]->(:Consumer {type: 'instance'})` |
| `bootable` | `(:Consumer).bootable` |
| `project_id` | `(:Consumer)-[:OWNED_BY]->(:Project)` |

### Storage Operations

```cypher
// Get all storage nodes
MATCH (rp:ResourceProvider)
      -[:HAS_TRAIT]->(:Trait {name: 'STORAGE_BACKEND'})
RETURN rp

// Get pools for a storage node
MATCH (storage:ResourceProvider {name: $storage_host})
      -[:PARENT_OF]->(pool:ResourceProvider)
      -[:HAS_INVENTORY]->(:Inventory)
      -[:OF_CLASS]->(:ResourceClass {name: 'DISK_GB'})
RETURN pool

// Get volumes in a pool
MATCH (pool:ResourceProvider {name: $pool_name})
      -[:HAS_INVENTORY]->(inv)
      <-[:CONSUMES]-(volume:Consumer)
WHERE volume.type = 'volume'
RETURN volume
```

## Baremetal Model Mapping

### IronicNode → ResourceProvider

| Watcher `IronicNode` Field | Tachyon Location |
|-------------------------|------------------|
| `uuid` | `(:ResourceProvider).uuid` |
| `power_state` | `(:ResourceProvider).power_state` |
| `maintenance` | `(:ResourceProvider).maintenance` |
| `maintenance_reason` | `(:ResourceProvider).maintenance_reason` |
| `extra` | `(:ResourceProvider).extra` |

**Cypher Representation:**

```cypher
(:ResourceProvider {
  uuid: 'ironic-node-uuid',
  power_state: 'power on',
  maintenance: false
})
-[:HAS_TRAIT]->(:Trait {name: 'COMPUTE_BAREMETAL'})
-[:HAS_INVENTORY]->(:Inventory)
-[:OF_CLASS]->(:ResourceClass {name: 'CUSTOM_BAREMETAL_GOLD'})
```

## Extended Attributes

Watcher's extended compute model (when `enable_extended_attributes = True`) includes additional instance data:

| Extended Field | Tachyon Location |
|---------------|------------------|
| `pinned_az` | `(:Consumer)-[:PINNED_TO]->(:AvailabilityZone)` |
| `flavor_extra_specs` | Via `(:Flavor)-[:HAS_EXTRA_SPEC]->(:ExtraSpec)` |

## Client API Design

The Tachyon client API should mirror Watcher's model interface:

```python
class TachyonClusterModel:
    """Tachyon-backed cluster model compatible with Watcher strategies."""
    
    def __init__(self, tachyon_client, session_id=None):
        self.client = tachyon_client
        self.session_id = session_id  # None = query global state
    
    def get_all_compute_nodes(self) -> Dict[str, ComputeNode]:
        """Get all compute nodes from Tachyon."""
        # Query ResourceProviders with compute trait
        pass
    
    def get_node_by_uuid(self, uuid: str) -> ComputeNode:
        """Get a specific compute node."""
        pass
    
    def get_instance_by_uuid(self, uuid: str) -> Instance:
        """Get a specific instance."""
        pass
    
    def get_node_instances(self, node: ComputeNode) -> List[Instance]:
        """Get all instances on a compute node."""
        pass
    
    def migrate_instance(
        self,
        instance: Instance,
        source_node: ComputeNode,
        destination_node: ComputeNode
    ) -> bool:
        """
        Migrate instance between nodes.
        
        If session_id is set, records a speculative delta.
        If session_id is None, performs actual migration in global state.
        """
        if self.session_id:
            return self._record_move_delta(instance, source_node, destination_node)
        else:
            return self._commit_migration(instance, source_node, destination_node)
    
    def get_node_used_resources(self, node: ComputeNode) -> Dict[str, int]:
        """Get used resources, considering session deltas if applicable."""
        pass
    
    def get_node_free_resources(self, node: ComputeNode) -> Dict[str, int]:
        """Get free resources, considering session deltas if applicable."""
        pass
```

## Compatibility Layer

To maintain backward compatibility with existing Watcher strategies, provide a NetworkX-compatible wrapper:

```python
class TachyonNetworkXAdapter(nx.DiGraph):
    """
    Adapter that presents Tachyon data as a NetworkX DiGraph.
    
    Provides compatibility with existing Watcher strategies that
    directly access the NetworkX graph structure.
    """
    
    def __init__(self, tachyon_model: TachyonClusterModel):
        super().__init__()
        self._tachyon = tachyon_model
        self._cache = {}
        self._dirty = False
    
    def nodes(self, data=False):
        """Return nodes, fetching from Tachyon if needed."""
        pass
    
    def add_edge(self, u, v, **attr):
        """Record edge addition as delta if in simulation mode."""
        pass
    
    def remove_edge(self, u, v):
        """Record edge removal as delta if in simulation mode."""
        pass
```

## Data Synchronization

### Initial Population

When Watcher starts, the collectors populate Tachyon instead of local NetworkX:

```python
class TachyonNovaCollector(NovaClusterDataModelCollector):
    """Nova collector that populates Tachyon instead of local model."""
    
    def execute(self):
        builder = TachyonNovaModelBuilder(self.osc, self.tachyon_client)
        return builder.execute(self._data_model_scope)
```

### Real-time Updates

Notification handlers update Tachyon in real-time:

```python
class TachyonVersionedNotification(VersionedNotification):
    """Handle Nova notifications by updating Tachyon."""
    
    def instance_update(self, payload):
        """Update instance in Tachyon."""
        self.tachyon_client.update_consumer(
            uuid=payload['instance_id'],
            state=payload['state'],
            # ... other fields
        )
```

## Query Performance

### Indexes Required

```cypher
// Resource provider lookups
CREATE INDEX rp_uuid IF NOT EXISTS FOR (rp:ResourceProvider) ON (rp.uuid);
CREATE INDEX rp_name IF NOT EXISTS FOR (rp:ResourceProvider) ON (rp.name);

// Consumer lookups
CREATE INDEX consumer_uuid IF NOT EXISTS FOR (c:Consumer) ON (c.uuid);

// Resource class lookups
CREATE INDEX rc_name IF NOT EXISTS FOR (rc:ResourceClass) ON (rc.name);

// Simulation session lookups
CREATE INDEX session_id IF NOT EXISTS FOR (s:SimulationSession) ON (s.id);
```

### Query Optimization

For frequent Watcher queries, use parameterized prepared statements:

```cypher
// Prepared: Get nodes with available capacity for resource class
:param resource_class => 'VCPU'
:param min_available => 4

MATCH (rp:ResourceProvider)
      -[:HAS_INVENTORY]->(inv)
      -[:OF_CLASS]->(:ResourceClass {name: $resource_class})
OPTIONAL MATCH (inv)<-[alloc:CONSUMES]-()
WITH rp, inv, COALESCE(sum(alloc.used), 0) AS used
WITH rp, (inv.total - inv.reserved) * inv.allocation_ratio - used AS available
WHERE available >= $min_available
RETURN rp.uuid, available
ORDER BY available DESC
```

