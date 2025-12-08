---
title: Use Case Coverage Matrix
description: Traceability between use cases and implementation
keywords: [traceability, matrix, coverage, use-cases, watcher, simulation]
related:
  - reference/use-cases.md
  - 07-watcher-integration/README.md
implements: []
section: appendix
---

# Use Case Coverage Matrix

Cross-reference between use cases and Tachyon implementation.

## Tachyon-Specific Use Cases

| Use Case | Model Components | Key Queries |
|----------|------------------|-------------|
| Prefer hosts matching resources | Weigher with trait count | PCIWeigher pattern |
| Optimize heterogeneous infrastructure | Multi-resource weighing | Combined weigher |
| Custom resource class placement | Native resource support | HAS_INVENTORY pattern |
| Preferred traits | `REQUIRES_TRAIT {constraint: 'preferred'}` | TraitAffinityWeigher |
| Avoided traits | `REQUIRES_TRAIT {constraint: 'avoided'}` | TraitAffinityWeigher |
| Weighted trait preferences | `weight` property | Per-trait scoring |
| Real-time resource view | Graph query over topology | Tree traversal |
| PCI alias translation | Trait/resource mapping | Alias resolution |

## Resource Allocation

| Use Case | Implementation |
|----------|----------------|
| Basic compute resources | `:Inventory` nodes |
| Allocation ratios | `allocation_ratio` property |
| Reserved resources | `reserved` property |
| Custom resource classes | `:ResourceClass` with CUSTOM_ |
| Nested provider trees | `:PARENT_OF` relationship |
| Sharing providers | `:SHARES_RESOURCES` relationship |
| Resource group isolation | `group_policy` in queries |

## Qualitative Scheduling

| Use Case | Implementation |
|----------|----------------|
| Required traits | `ALL(t WHERE HAS_TRAIT)` |
| Forbidden traits | `NONE(t WHERE HAS_TRAIT)` |
| Preferred traits | TraitAffinityWeigher + score |
| Avoided traits | TraitAffinityWeigher - penalty |
| Any-of traits | `ANY(t WHERE HAS_TRAIT)` |
| Root provider traits | Root traversal + trait check |

## Aggregates and Zones

| Use Case | Implementation |
|----------|----------------|
| Host aggregates | `:Aggregate` with properties |
| Tenant isolation | `:TENANT_ALLOWED` relationship |
| Availability zones | `:AvailabilityZone`, `:DEFINES_AZ` |
| Per-aggregate multipliers | Aggregate properties |
| Image isolation | `:IMAGE_ALLOWED` relationship |

## Server Groups

| Use Case | Implementation |
|----------|----------------|
| Affinity | Same-host constraint |
| Anti-affinity | Different-host constraint |
| Soft-affinity | Affinity weigher |
| Soft-anti-affinity | Anti-affinity weigher |
| max_server_per_host | Count-based filter |

## NUMA and CPU

| Use Case | Implementation |
|----------|----------------|
| NUMA-aware scheduling | `:NUMANode` nested providers |
| CPU pinning | `cpuset`, `pcpuset` properties |
| Mixed CPU policy | Per-NUMA inventories |
| Custom CPU topology | Flavor extra specs |

## PCI and vGPU

| Use Case | Implementation |
|----------|----------------|
| PCI passthrough | `:PCIDevice`, `:PCIPF`, `:PCIVF` |
| SR-IOV VFs | VF hierarchy under PF |
| PCI-NUMA affinity | `:NUMA_AFFINITY` relationship |
| vGPU resources | `:PhysicalGPU`, `:vGPUType` |
| Multiple vGPU types | Multiple children per GPU |

## Filters

| Nova Filter | Tachyon Implementation |
|-------------|------------------------|
| ComputeFilter | `disabled` + status trait |
| ImagePropertiesFilter | Property-trait matching |
| NUMATopologyFilter | NUMA fitting query |
| PciPassthroughFilter | PCI availability query |
| ServerGroupAffinityFilter | Affinity constraint |
| ServerGroupAntiAffinityFilter | Anti-affinity constraint |
| AggregateTenancyIsolation | TENANT_ALLOWED query |
| AggregateImageIsolation | IMAGE_ALLOWED query |

## Weighers

| Nova Weigher | Tachyon Implementation |
|--------------|------------------------|
| RAMWeigher | MEMORY_MB capacity |
| CPUWeigher | VCPU capacity |
| DiskWeigher | DISK_GB capacity |
| IoOpsWeigher | Task state counting |
| PCIWeigher | PCI availability |
| ServerGroupSoftAffinityWeigher | Member count |
| ServerGroupSoftAntiAffinityWeigher | Negative count |
| TraitAffinityWeigher | Preferred/avoided scoring |

## Watcher Integration

| Use Case | Model Components | Key Operations |
|----------|------------------|----------------|
| Data model delegation | Graph schema maps to NetworkX model | Query via Cypher instead of in-memory |
| Stateless decision engine | Tachyon stores all state | No local NetworkX graph required |
| Horizontal scaling | Shared graph backend | Multiple DE instances query same state |
| Real-time consistency | Notification-driven updates | Consumers/providers updated atomically |

## Simulation Sessions

| Use Case | Implementation | Key Queries |
|----------|----------------|-------------|
| Create session | `:SimulationSession` node | Session lifecycle operations |
| Record move delta | `:SpeculativeDelta` with `type: 'MOVE'` | `[:HAS_DELTA]` relationship |
| Record allocation | `:SpeculativeDelta` with `type: 'ALLOCATE'` | Delta chain tracking |
| Record deallocation | `:SpeculativeDelta` with `type: 'DEALLOCATE'` | Delta chain tracking |
| Query virtual state | Overlay deltas on global graph | Virtual usage calculation |
| Find migration targets | Consider session deltas | Capacity check with deltas |
| Session isolation | Separate `:SimulationSession` nodes | No cross-session interference |

## Optimization Metrics

| Use Case | Implementation | Key Queries |
|----------|----------------|-------------|
| Resource balance score | Standard deviation of utilization | Aggregation over virtual state |
| Utilization variance | Virtual usage / capacity | Per-provider calculation |
| Compare strategies | Multi-session queries | Side-by-side metric comparison |
| Migration impact | Before/after delta analysis | Metric delta calculation |

## Session Lifecycle

| Use Case | Implementation | Key Operations |
|----------|----------------|----------------|
| Session creation | Create `:SimulationSession` | Anchor to global generation |
| Session expiry | TTL-based cleanup | `expires_at` timestamp check |
| Session commit | Apply deltas to global graph | Atomic transaction |
| Session rollback | Delete deltas | Mark session rolled_back |
| Conflict detection | Generation comparison | Stale session detection |

## Watcher Model Mapping

| Watcher Entity | Tachyon Equivalent | Relationship |
|----------------|-------------------|--------------|
| `ComputeNode` | `:ResourceProvider` | `:HAS_INVENTORY` → `:Inventory` |
| `Instance` | `:Consumer` | `:CONSUMES` → `:Inventory` |
| `StorageNode` | `:ResourceProvider` with storage trait | `:HAS_TRAIT` |
| `Pool` | Child `:ResourceProvider` | `:PARENT_OF` |
| `Volume` | `:Consumer` | `:CONSUMES` → `:Inventory` |
| `IronicNode` | `:ResourceProvider` with baremetal trait | `:HAS_TRAIT` |
| `migrate_instance()` | Speculative delta or commit | `MOVE` delta type |
| `get_node_used_resources()` | Aggregation query | Virtual state overlay |

