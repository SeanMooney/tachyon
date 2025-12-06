# Nova Scheduling Overview - LLM Optimized Reference

## Purpose
This document provides a comprehensive, structured overview of OpenStack Nova's scheduling system optimized for LLM understanding and reference. It synthesizes information from multiple Nova documentation sources to explain how scheduling works, what mechanisms are available, and how to configure them.

---

## Table of Contents
1. [Core Concepts](#core-concepts)
2. [Scheduling Workflow](#scheduling-workflow)
3. [Prefilters](#prefilters)
4. [Filters](#filters)
5. [Weighers](#weighers)
6. [Scheduler Hints vs Flavor Extra Specs](#scheduler-hints-vs-flavor-extra-specs)
7. [Allocation Ratios](#allocation-ratios)
8. [Compute Capabilities as Traits](#compute-capabilities-as-traits)
9. [Custom Extensions](#custom-extensions)
10. [Historical Context and Evolution](#historical-context-and-evolution)

---

## Core Concepts

### What is the Nova Scheduler?
The `nova-scheduler` service determines **where** (which host or node) a VM should launch when compute requests are dispatched. It operates at the deployment level (via "super conductor") and coordinates with the Placement service to find suitable hosts.

### Key Services
- **nova-scheduler**: Main scheduling service that makes placement decisions
- **Placement Service**: Resource provider inventory and allocation tracking
- **Super Conductor**: Top-level conductor that coordinates across cells
- **Cell Conductor**: Per-cell conductor that handles instance builds within a specific cell

### Default Scheduling Criteria
In the default configuration, the scheduler considers hosts that meet ALL of the following:

1. **Availability Zone**: In the requested AZ (via `map_az_to_placement_aggregate` placement prefilter)
2. **Service Status**: Can service the request (nova-compute is available and not disabled via `ComputeFilter`)
3. **Extra Specs**: Satisfy flavor extra specs (via `ComputeCapabilitiesFilter`)
4. **Image Properties**: Satisfy architecture, hypervisor type, or VM mode from image (via `ImagePropertiesFilter`)
5. **Anti-Affinity**: On a different host than other group instances if requested (via `ServerGroupAntiAffinityFilter`)
6. **Affinity**: In the set of group hosts if requested (via `ServerGroupAffinityFilter`)

### When Scheduling Occurs
The scheduler chooses a new host when an instance is:
- Created (initial boot)
- Migrated (live or cold)
- Resized (flavor change)
- Evacuated (host failure recovery)
- Unshelved (after being shelve offloaded)

---

## Scheduling Workflow

### High-Level Process (Pike 16.0.0+)

```
┌────────────────┐
│ Super Conductor│
│   (Request)    │
└───────┬────────┘
        │ 1. Request Spec
        ↓
┌────────────────┐
│   Scheduler    │
└───────┬────────┘
        │ 2. Resource Requirements
        ↓
┌────────────────┐
│   Placement    │←─── Resource Providers (Compute Nodes)
└───────┬────────┘
        │ 3-5. Query, Construct Data, Return Provider Summaries
        ↓
┌────────────────┐
│   Scheduler    │
│  (Processing)  │
└───────┬────────┘
        │ 6-13. Filter, Weigh, Select, Claim, Create Alternates
        ↓
┌────────────────┐
│ Super Conductor│
└───────┬────────┘
        │ 14-15. Route to Cell
        ↓
┌────────────────┐
│ Cell Conductor │
│   (Build)      │
└────────────────┘
```

### Detailed Step-by-Step Process

1. **Request Reception**: Scheduler receives a request spec from super conductor containing resource requirements

2. **Placement Query**: Scheduler sends requirements to Placement service

3. **Resource Provider Query**: Placement queries resource providers (compute nodes) that can satisfy requirements

4. **Data Structure Construction**: Placement constructs data structure for each matching compute node with:
   - Provider summaries
   - AllocationRequest (used to claim resources if selected)

5. **Return to Scheduler**: Placement returns this data to Scheduler

6. **HostState Creation**: Scheduler creates HostState objects for each compute node in the provider summaries

7. **Per-Instance Loop**: For each requested instance, scheduler repeats steps 8-13

8. **Filter and Weigh**: Scheduler runs HostState objects through filters and weighers to refine and rank hosts

9. **Selection**: Scheduler selects the top-ranked HostState and gets its AllocationRequest

10. **Resource Claim**: Scheduler sends AllocationRequest to Placement to claim resources
    - If claim fails (resources consumed by another process), move to next host
    - Repeat until successful claim

11. **Alternate Selection**: Scheduler selects alternate hosts from same cell (count controlled by `scheduler.max_attempts`)

12. **List Creation**: Create two lists per instance:
    - Host list (selected + alternates)
    - AllocationRequest list

13. **Cell Determination**: Determine cell of selected host and find alternates in same cell

14. **Return Results**: Scheduler returns 2-tuple to super conductor:
    - List of lists of hosts
    - List of lists of AllocationRequests

15. **Cell Routing**: Super conductor routes each instance request to target cell conductor

16. **Build Attempt**: Cell conductor attempts build on selected host
    - If fails: unclaim resources, try alternates in order
    - Only fails completely when all alternates exhausted

---

## Prefilters

**Purpose**: Prefilters augment the request sent to Placement to reduce candidate compute hosts based on attributes Placement can answer efficiently. Introduced in Rocky release.

### Available Prefilters

#### 1. Compute Image Type Support (Train 20.0.0+)
**Config**: `scheduler.query_placement_for_image_type_support = True`

**Purpose**: Excludes compute nodes that don't support the `disk_format` of the boot image

**Use Case**: 
- Libvirt driver with Ceph ephemeral backend doesn't support `qcow2` images (without expensive conversion)
- Ensures scheduler doesn't send qcow2 boot requests to Ceph-backed computes

#### 2. Compute Disabled Status Support (Train 20.0.0+)
**Mandatory**: Yes (cannot be disabled)

**Purpose**: Excludes disabled compute nodes

**Mechanism**:
- Compute node resource providers with `COMPUTE_STATUS_DISABLED` trait are excluded
- Trait managed by `nova-compute` service
- Mirrors `disabled` status in compute service record (os-services API)
- Similar to but doesn't fully replace `ComputeFilter`

**Synchronization**:
- If compute is down when status changes: synchronized on restart
- If error occurs setting trait: synchronized by `update_available_resource` periodic task (controlled by `update_resources_interval` config)

#### 3. Isolate Aggregates (Train 20.0.0+)
**Config**: `scheduler.enable_isolated_aggregate_filtering = True`

**Purpose**: Ensures traits required in flavor/image match those required in aggregate metadata

**Mechanism**: If aggregate has `trait:CUSTOM_X=required` metadata, only instances with that trait requirement can boot on hosts in that aggregate

**Key Benefit**: Solves bug 1677217 where `AggregateImagePropertiesIsolation` filter would pass even without matching metadata

**Example Use Case**: License-based isolation
```
Aggregate ABC: trait:CUSTOM_LICENSED_WINDOWS=required
Hosts: HOST1, HOST2 (both have CUSTOM_LICENSED_WINDOWS trait)
Result:
  - Instances with trait:CUSTOM_LICENSED_WINDOWS=required → can use HOST1/HOST2
  - Instances without that trait → CANNOT use HOST1/HOST2
```

#### 4. Availability Zones
See `map_az_to_placement_aggregate` and documentation on availability-zones-with-placement

#### 5. Tenant Isolation
See documentation on tenant-isolation-with-placement

---

## Filters

**Purpose**: Filters are binary decisions - either a host passes (accepted) or fails (rejected). Applied after prefilters.

### Configuration
- `filter_scheduler.available_filters`: Defines filter classes available (can be specified multiple times)
- `filter_scheduler.enabled_filters`: Defines which filters are actually applied
- Default: `nova.scheduler.filters.all_filters` (all built-in filters)

### Performance Considerations
- Filter order affects performance
- General rule: Filter out invalid hosts ASAP to avoid unnecessary costs
- Example: `ComputeFilter` before `NUMATopologyFilter` (avoid expensive NUMA calculations for disabled hosts)

### Complete Filter List

#### Aggregate-Based Filters

##### AggregateImagePropertiesIsolation
**Purpose**: Matches image metadata properties against aggregate metadata

**Behavior**:
- Host in aggregate with matching metadata → candidate for that image
- Host not in any aggregate → can boot all images

**Config Options**:
- `filter_scheduler.aggregate_image_properties_isolation_namespace`
- `filter_scheduler.aggregate_image_properties_isolation_separator`

**Limitations**: Bug 1677217 - addressed by isolate-aggregates prefilter

**Version Note**: Liberty 12.0.0+ only parses standard Glance metadata (not arbitrary metadata)

**Example**:
```bash
# Aggregate with Windows metadata
$ openstack aggregate show myWinAgg
properties: os_distro='windows'
hosts: ['sf-devel']

# Image with Windows property
$ openstack image show Win-2012
properties: os_distro='windows'

# Result: Win-2012 boots on sf-devel host
```

##### AggregateInstanceExtraSpecsFilter
**Purpose**: Matches flavor extra specs against aggregate properties

**Scoping**: Works with `aggregate_instance_extra_specs` scope
- Also works with non-scoped specs (discouraged - conflicts with ComputeCapabilitiesFilter)

**Multi-Value**: Supports comma-separated lists

##### AggregateIoOpsFilter
**Purpose**: Filters by disk I/O operations per host

**Mechanism**: 
- Per-aggregate `max_io_ops_per_host` metadata value
- Falls back to `filter_scheduler.max_io_ops_per_host` config
- Multiple aggregates → minimum value used

##### AggregateMultiTenancyIsolation
**Purpose**: Tenant-isolated aggregates

**Mechanism**:
- Aggregate with `filter_tenant_id` metadata → only specified tenant(s) can use
- Value can be single tenant or comma-separated list
- Host not in any isolated aggregate → all tenants can use
- Does NOT restrict tenant from using other hosts

**Example**:
```
HostA: No aggregate
HostB: Aggregate with filter_tenant_id=X

Tenant X request: Can use HostA OR HostB
Tenant Y request: Can use HostA only
```

##### AggregateNumInstancesFilter
**Purpose**: Limit instances per host via aggregate

**Mechanism**:
- Per-aggregate `max_instances_per_host` metadata
- Falls back to `filter_scheduler.max_instances_per_host` config
- Multiple aggregates → minimum value used

##### AggregateTypeAffinityFilter
**Purpose**: Filter by flavor name match in aggregate

**Mechanism**:
- Aggregate metadata key: `instance_type`
- Value: Single flavor name or comma-separated list (e.g., `m1.nano,m1.small`)
- Host passes if flavor matches OR key not set

**Note**: "instance_type" is historical name for flavors

#### Capability Filters

##### ComputeCapabilitiesFilter
**Purpose**: Match flavor extra specs against compute capabilities

**Namespace Handling**:
- Key with colon: `namespace:key` (e.g., `capabilities:cpu_info:features`)
- Non-`capabilities` namespace → ignored
- No namespace → treated as key (discouraged - conflicts with AggregateInstanceExtraSpecsFilter)

**Operators**:
- Numeric: `=`, `==`, `!=`, `>=`, `<=`
- String: `s==`, `s!=`, `s>=`, `s>`, `s<=`, `s<`
- Special: `<in>` (substring), `<all-in>` (all elements), `<or>` (find one)
- Default: `s==` if no operator specified

**Common Attributes**:
- `free_ram_mb`: Available RAM (e.g., `>= 4096`)
- `free_disk_mb`: Available disk (e.g., `>= 10240`)
- `host`: Host name (e.g., `<in> compute`, `s== compute_01`)
- `hypervisor_type`: Hypervisor (e.g., `s== QEMU`, `s== ironic`)
- `hypervisor_version`: Version number (e.g., `>= 1005003`)
- `num_instances`: Instance count (e.g., `<= 10`)
- `num_io_ops`: I/O operations (e.g., `<= 5`)
- `vcpus_total`: Total vCPUs (e.g., `= 48`, `>=24`)
- `vcpus_used`: Used vCPUs (e.g., `= 0`, `<= 10`)

**Best Practice**: Use traits instead for CPU features (consistent naming, efficient querying)

##### ComputeFilter
**Purpose**: Passes operational and enabled hosts

**Status**: Should ALWAYS be enabled

**Note**: Similar to but not fully replaced by Compute Disabled Status prefilter

##### ImagePropertiesFilter
**Purpose**: Filter by image property requirements

**Properties Checked**:
- `hw_architecture`: Machine architecture (i686, x86_64, arm, ppc64) [Liberty 12.0.0+: was `architecture`]
- `img_hv_type`: Hypervisor type (qemu for both QEMU and KVM) [Liberty 12.0.0+: was `hypervisor_type`]
- `img_hv_requested_version`: Hypervisor version (HyperV only) [Liberty 12.0.0+: was `hypervisor_version_requires`]
- `hw_vm_mode`: Hypervisor ABI (xen, hvm, exe) [Liberty 12.0.0+: was `vm_mode`]

**Example**:
```bash
$ openstack image set --architecture arm --property img_hv_type=qemu img-uuid
# Instance with this image requires ARM processor and QEMU hypervisor
```

##### IsolatedHostsFilter
**Purpose**: Define isolated image/host pairs

**Config**:
- `filter_scheduler.isolated_hosts`: Comma-separated host list
- `filter_scheduler.isolated_images`: Comma-separated image UUID list
- `filter_scheduler.restrict_isolated_hosts_to_isolated_images`: Force isolation (default True)

**Behavior**:
- Isolated images can ONLY run on isolated hosts
- Isolated hosts can ONLY run isolated images (if restrict = True)
- Volume-backed instances: NOT on isolated hosts (if restrict = True), any host (if restrict = False)

**Example**:
```ini
[filter_scheduler]
isolated_hosts = server1, server2
isolated_images = 342b492c-128f-4a42-8d3a-c5088cf27d13, ebd267a6-ca86-4d6c-9a0e-bd132d6b7d09
```

##### IoOpsFilter
**Purpose**: Filter by concurrent I/O operations

**Config**: `filter_scheduler.max_io_ops_per_host`

**Mechanism**: 
- Counts instances in specific task states: build, resize, snapshot, migrate, rescue, unshelve
- Filters out hosts exceeding limit

##### NUMATopologyFilter
**Purpose**: Match NUMA topology requirements

**Mechanism**:
- Matches flavor extra_specs NUMA topology with image properties
- Tries to match exact NUMA cells
- Considers over-subscription limits per NUMA cell
- Provides limits to compute host

**Essential For**:
- Instance NUMA topologies
- CPU pinning

**Behavior**:
- No instance topology → considered for any host
- Instance topology defined → only NUMA-capable hosts considered

##### PciPassthroughFilter
**Purpose**: Match PCI device requests

**Mechanism**: Schedules on hosts with devices meeting flavor `extra_specs` device requests

**Essential For**:
- PCI device passthrough
- SR-IOV networking

##### NumInstancesFilter
**Purpose**: Limit instances per host globally

**Config**: `filter_scheduler.max_instances_per_host`

**Behavior**: Filters hosts with more than configured max instances

#### Hint-Based Filters

##### DifferentHostFilter
**Purpose**: Schedule on different host from specified instances

**Hint Key**: `different_host`
**Hint Value**: List of instance UUIDs

**CLI Example**:
```bash
$ openstack server create \
  --image IMAGE_ID --flavor 1 \
  --hint different_host=UUID1 \
  --hint different_host=UUID2 \
  server-1
```

**API Example**:
```json
{
  "server": { "name": "server-1", "imageRef": "IMAGE_ID", "flavorRef": "1" },
  "os:scheduler_hints": {
    "different_host": ["UUID1", "UUID2"]
  }
}
```

##### SameHostFilter
**Purpose**: Schedule on same host as specified instances

**Hint Key**: `same_host`
**Hint Value**: List of instance UUIDs

**Opposite Of**: DifferentHostFilter

##### SimpleCIDRAffinityFilter
**Purpose**: Schedule based on host IP subnet

**Hints**:
- `build_near_host_ip`: First IP in subnet (e.g., 192.168.1.1)
- `cidr`: CIDR notation (e.g., /24)

**Status**: Unclear if works with Neutron

#### Server Group Filters

##### ServerGroupAffinityFilter
**Purpose**: Restrict group instances to same host(s)

**Requirement**: Server group with `affinity` policy

**Hint Key**: `group`
**Hint Value**: Server group UUID

**Example**:
```bash
$ openstack server group create --policy affinity group-1
$ openstack server create --image IMAGE_ID --flavor 1 \
  --hint group=SERVER_GROUP_UUID server-1
```

##### ServerGroupAntiAffinityFilter
**Purpose**: Restrict group instances to separate hosts

**Requirement**: Server group with `anti-affinity` policy

**Hint Key**: `group`
**Hint Value**: Server group UUID

#### Advanced Filters

##### JsonFilter
**Status**: ⚠️ Not enabled by default, not comprehensively tested, NOT RECOMMENDED

**Purpose**: Custom filter via JSON scheduler hint

**Operators**: `=`, `<`, `>`, `in`, `<=`, `>=`, `not`, `or`, `and`

**Variables** (HostState attributes):
- `$free_ram_mb`
- `$free_disk_mb`
- `$hypervisor_hostname`
- `$total_usable_ram_mb`
- `$vcpus_total`
- `$vcpus_used`

**Recommendation**: Use ImagePropertiesFilter or traits-based scheduling instead

**Example**:
```bash
$ openstack server create --image IMAGE_ID --flavor 1 \
  --hint query='[">=","$free_ram_mb",1024]' server1
```

##### MetricsFilter
**Purpose**: Work with MetricsWeigher

**Mechanism**: Filters hosts not reporting metrics in `metrics.weight_setting` config

**Prevents**: MetricsWeigher failures due to missing metrics

##### AllHostsFilter
**Purpose**: No-op filter (passes all hosts)

**Use Case**: Testing or explicitly bypassing filtering

---

## Weighers

**Purpose**: After filtering, weighers rank remaining hosts to select the best candidate. Multiple weighers can be combined with multipliers.

### Weight Calculation Formula
```
weight = w1_multiplier * norm(w1) + w2_multiplier * norm(w2) + ...
```

Where:
- Weights are normalized before multiplier application
- Multipliers can be positive (prefer higher values) or negative (prefer lower values)
- Largest final weight wins

### Configuration
- `filter_scheduler.host_subset_size`: Limit selection to subset of top hosts
- `filter_scheduler.weight_classes`: List of weigher classes to use

### Per-Aggregate Multipliers (Stein 19.0.0+)
Many weighers support per-aggregate multiplier overrides via aggregate metadata keys. When host is in multiple aggregates with different values, **minimum value is used**.

### Complete Weigher List

#### Resource Weighers

##### RAMWeigher
**Purpose**: Weight by available RAM

**Config**: `filter_scheduler.ram_weight_multiplier`

**Per-Aggregate Key** (Stein+): `ram_weight_multiplier`

**Behavior**:
- Positive multiplier: Prefer most RAM available (spreading)
- Negative multiplier: Prefer least RAM available (stacking)
- Largest weight wins

##### CPUWeigher
**Purpose**: Weight by available vCPUs

**Config**: `filter_scheduler.cpu_weight_multiplier`

**Per-Aggregate Key** (Stein+): `cpu_weight_multiplier`

**Behavior**:
- Positive multiplier: Prefer most CPUs available (spreading)
- Negative multiplier: Prefer least CPUs available (stacking)

##### DiskWeigher
**Purpose**: Weight by free disk space

**Config**: `filter_scheduler.disk_weight_multiplier`

**Per-Aggregate Key** (Stein+): `disk_weight_multiplier`

**Behavior**:
- Positive multiplier: Prefer most disk space (spreading)
- Negative multiplier: Prefer least disk space (stacking)

##### PCIWeigher
**Purpose**: Weight by PCI device availability vs demand

**Config**: `filter_scheduler.pci_weight_multiplier`

**Per-Aggregate Key** (Stein+): `pci_weight_multiplier`

**Logic**:
- Instance requests 1 PCI device → prefer host with few devices
- Instance requests many PCI devices → prefer host with many devices
- Instance requests no PCI devices → prefer host with no devices

**Requirements**: PciPassthroughFilter or NUMATopologyFilter must be enabled

**Important**: ⚠️ Only positive multipliers allowed (negative would cause scheduling issues)

##### NumInstancesWeigher (Bobcat 28.0.0+)
**Purpose**: Weight by number of instances on host

**Config**: `filter_scheduler.num_instances_weight_multiplier`

**Default**: 0.0 (disabled)

**Behavior**:
- Positive multiplier: Prefer hosts with MORE instances (packing)
- Negative multiplier: Prefer hosts with FEWER instances (spreading)

#### Workload Weighers

##### IoOpsWeigher
**Purpose**: Weight by current workload

**Config**: `filter_scheduler.io_ops_weight_multiplier`

**Per-Aggregate Key** (Stein+): `io_ops_weight_multiplier`

**Workload Calculation**: Count instances in:
- `vm_state`: building
- `task_state`: resize_migrating, rebuilding, resize_prep, image_snapshot, image_backup, rescuing, unshelving

**Behavior**:
- Default (negative): Prefer light workload hosts
- Positive multiplier: Prefer heavy workload hosts

##### MetricsWeigher
**Purpose**: Weight by custom compute node metrics

**Config**:
- `metrics.weight_setting`: Metric names and ratios (e.g., `name1=1.0, name2=-1.0`)
- `metrics.required`: Required metrics list
- `metrics.weight_of_unavailable`: Weight for missing metrics
- `metrics.weight_multiplier`: Overall multiplier

**Per-Aggregate Key** (Stein+): `metrics_weight_multiplier`

**Example**:
```ini
[metrics]
weight_setting = name1=1.0, name2=-1.0
```

##### BuildFailureWeigher
**Purpose**: Weight by recent failed boot attempts

**Config**: `filter_scheduler.build_failure_weight_multiplier`

**Per-Aggregate Key** (Stein+): `build_failure_weight_multiplier`

**Default**: Very high value (to offset other weighers)

**Behavior**: Negatively weighs hosts with recent failures

**Important**: ⚠️ All build failures counted, including user errors. Consider lowering multiplier if hosts frequently excluded due to user errors.

#### Server Group Weighers

##### ServerGroupSoftAffinityWeigher
**Purpose**: Prefer hosts with more instances from same server group

**Config**: `filter_scheduler.soft_affinity_weight_multiplier`

**Per-Aggregate Key** (Stein+): `soft_affinity_weight_multiplier`

**Important**: ⚠️ Only positive multipliers allowed

##### ServerGroupSoftAntiAffinityWeigher
**Purpose**: Prefer hosts with fewer instances from same server group

**Config**: `filter_scheduler.soft_anti_affinity_weight_multiplier`

**Per-Aggregate Key** (Stein+): `soft_anti_affinity_weight_multiplier`

**Mechanism**: Counts instances as negative value, largest weight (least negative) wins

**Important**: ⚠️ Only positive multipliers allowed

#### System Weighers

##### CrossCellWeigher (Ussuri 21.0.0+)
**Purpose**: Prefer "local" cells when moving instances

**Config**: `filter_scheduler.cross_cell_move_weight_multiplier`

**Per-Aggregate Key**: `cross_cell_move_weight_multiplier`

**Use Case**: Cross-cell instance operations (migrations, evacuations)

##### HypervisorVersionWeigher (Bobcat 28.0.0+)
**Purpose**: Weight by hypervisor version

**Config**: `filter_scheduler.hypervisor_version_weight_multiplier`

**Default Behavior**: Prefer newer hypervisor versions

**Negative Multiplier**: Prefer older versions

**Important Considerations**:
- Each virt driver uses different version encoding algorithm
- Values not directly comparable across hypervisor types
- Example: Libvirt 7.1.123 → 700100123, Ironic 1.82 → 1

**Mixed Deployments**:
- Ironic vs non-ironic: No special handling needed (custom resource classes separate them)
- Multiple non-ironic drivers: Use aggregates to group by driver type (recommended)

##### ImagePropertiesWeigher (Epoxy 31.0.0+)
**Purpose**: Weight by matching image properties on existing instances

**Config**:
- `filter_scheduler.image_props_weight_multiplier`: Overall multiplier
- `filter_scheduler.image_props_weight_setting`: Specific properties and weights

**Default**: 0.0 (disabled)

**Behavior**:
- Positive multiplier: Prefer hosts with same image properties (packing)
- Negative multiplier: Prefer hosts with different image properties (spreading)

**Property Weighting**: Configure relative importance of properties

**Example**:
```ini
[filter_scheduler]
image_props_weight_setting = os_distro=10,os_secure_boot=1,os_require_quiesce=0
```

This means:
- `os_distro` match counts 10x more than `os_secure_boot` match
- `os_require_quiesce` matches don't count (0 weight)
- Undefined properties: If `image_props_weight_setting` is set, only listed properties count

**Note**: ⚠️ Compares property values as strings. List properties with different ordering considered different values.

---

## Scheduler Hints vs Flavor Extra Specs

### Quick Decision Matrix

| Aspect | Extra Specs | Scheduler Hints |
|--------|-------------|----------------|
| **Control** | Deployer (admin) | End user |
| **Persistence** | Stored with flavor | Only at creation |
| **Discoverability** | Listable (if policy allows) | Not easily discoverable |
| **During Resize** | New flavor specs applied | Original hints reapplied |
| **Retrieval** | Via API (microversion 2.47+) | No API retrieval |
| **Hypervisor Config** | Can affect guest creation | No hypervisor impact |
| **Standardization** | More standardized long-term | Less standardized |

### Extra Specs

**Definition**: Key-value pairs associated with flavors that define:
1. How guest is created in hypervisor (e.g., watchdog action)
2. Scheduling constraints (e.g., aggregate membership)

**Characteristics**:
- Tied to host aggregates
- Cloud-specific and abstracted from end user
- Controlled by deployer (end users can't create flavors by default)
- Can be used interchangeably with image properties for VM behavior
- Persisted and retrievable
- Applied during resize if flavor changes

**Use Case**: Deployment-specific capabilities (e.g., baremetal setup, licensed software)

**Discoverability**: 
- Policy default: End users CAN list extra specs (`os_compute_api:os-flavor-extra-specs:index`)
- But understanding requires documentation (just key/value pairs)
- Some standard specs documented, but not exhaustive

**Recommendation**: ✅ Preferred for long-term standardization

### Scheduler Hints

**Definition**: Per-instance scheduling preferences provided at creation time

**Characteristics**:
- Specified by end user at server creation
- Mapped to specific scheduler filters
- Can be optional (user chooses whether to include)
- NOT stored or retrievable via API
- Original hints reapplied during move operations (resize, migrate, etc.)
- Cannot be specified during resize/move (original hints used)

**Use Case**: Instance-specific placement (e.g., server group membership, same/different host)

**Discoverability**:
- Less discoverable than extra specs
- Some standard hints in API schema, but `additionalProperties: True` allows custom hints
- Requires deployment-specific documentation

**Workaround for Retrieval**: Store hints in server metadata for later retrieval

**Recommendation**: ⚠️ Use when extra specs insufficient, but document thoroughly

### Similarities

1. Both can be used by scheduler filters
2. Both are fully customizable (no whitelist, unlike image properties)
3. Both require deployer consent (filter must be enabled)
4. Neither is more "dynamic" than the other (both are static deployment configuration)

### When to Choose Which?

**Use Extra Specs When**:
- Need to retrieve scheduling criteria later
- Need hypervisor guest configuration
- Want deployer control
- Prefer standardization

**Use Scheduler Hints When**:
- Per-instance decision needed
- End user should control
- Don't need hypervisor configuration
- Extra spec insufficient

**General Guidance**: ✅ Favor extra specs for new features due to better long-term standardization

### Interoperability

**Reality**: Neither extra specs nor scheduler hints are interoperable across clouds
- Each cloud defines its own aggregates, filters, and configuration
- Moving applications between clouds requires understanding each cloud's specific setup
- Documentation is critical for both

---

## Allocation Ratios

### Purpose
Allocation ratios enable **overcommit** of host resources - allocating more virtual resources than physical resources available.

### Configuration Options

#### Override Ratios (Always Applied)
- `cpu_allocation_ratio`: VCPU inventory ratio override
- `ram_allocation_ratio`: MEMORY_MB inventory ratio override
- `disk_allocation_ratio`: DISK_GB inventory ratio override

When set to non-None, nova-compute overwrites any Placement API values.

#### Initial Ratios (Applied at Compute Node Creation)
- `initial_cpu_allocation_ratio`: Default 4.0 (Antelope 27.0.0+), was 16.0 (Stein 19.0.0 - Wallaby 26.x)
- `initial_ram_allocation_ratio`: Default 1.0 (Antelope 27.0.0+), was 1.5 (Stein 19.0.0 - Wallaby 26.x)
- `initial_disk_allocation_ratio`: Default 1.0 (all versions)

**Pre-Stein Defaults** (<19.0.0):
- CPU: 16.0
- RAM: 1.5
- Disk: 1.0

### Where Ratios Are Used
1. **Reporting**: When nova-compute reports resource provider inventory to Placement
2. **Scheduling**: When scheduler makes placement decisions

### Usage Scenarios

#### Scenario 1: Always Override (Configuration Control)
**Goal**: Deployer always controls ratio, no Placement API changes

**Configuration**:
```ini
[DEFAULT]
cpu_allocation_ratio = 4.0
ram_allocation_ratio = 1.5
disk_allocation_ratio = 1.0
```

**Behavior**: nova-compute overwrites any external Placement API changes

#### Scenario 2: Initial Value, Admin Adjustable (Hybrid Control)
**Goal**: Set starting value, allow admin to tune per-host via API

**Configuration**:
```ini
[DEFAULT]
initial_cpu_allocation_ratio = 4.0
initial_ram_allocation_ratio = 1.5
initial_disk_allocation_ratio = 1.0
```

**Management**: Use Placement API or osc-placement CLI

**Example**:
```bash
$ openstack resource provider inventory set \
  --resource VCPU:allocation_ratio=1.0 \
  --amend 815a5634-86fb-4e1e-8824-8a631fee3e06
```

#### Scenario 3: Always Use Placement API (API Control)
**Goal**: All ratio management via Placement API

**Configuration**:
```ini
[DEFAULT]
cpu_allocation_ratio = None
ram_allocation_ratio = None
disk_allocation_ratio = None
```

**Management**: Exclusively use Placement REST API or osc-placement CLI

**Note**: Workaround for bug 1804125

### Reserved Resources

**Purpose**: Set aside resources not consumed by instances (whether overcommitted or not)

**Configuration**:
- `reserved_host_cpus`: CPUs reserved for host
- `reserved_host_memory_mb`: RAM reserved for host (MB)
- `reserved_host_disk_mb`: Disk reserved for host (MB)

**Use Case**: Account for hypervisor-specific overhead

### Version History Summary

| Release | Version | CPU Default | RAM Default | Disk Default |
|---------|---------|-------------|-------------|--------------|
| Pre-Stein | <19.0.0 | 16.0 | 1.5 | 1.0 |
| Stein | 19.0.0 | 16.0 (initial_*) | 1.5 (initial_*) | 1.0 (initial_*) |
| Antelope | 27.0.0+ | 4.0 (initial_*) | 1.0 (initial_*) | 1.0 (initial_*) |

---

## Compute Capabilities as Traits

### Overview (Stein 19.0.0+)

**Purpose**: nova-compute reports `COMPUTE_*` traits based on driver capabilities to Placement service

**Association**: Traits associated with resource provider for compute service

**Usage**: Configure flavors with:
- `trait:TRAIT_NAME=required` (required traits)
- `trait:TRAIT_NAME=forbidden` (forbidden traits)

### Example Traits

From a libvirt compute node:
```
COMPUTE_DEVICE_TAGGING
COMPUTE_NET_ATTACH_INTERFACE
COMPUTE_NET_ATTACH_INTERFACE_WITH_TAG
COMPUTE_TRUSTED_CERTS
COMPUTE_VOLUME_ATTACH_WITH_TAG
COMPUTE_VOLUME_EXTEND
COMPUTE_VOLUME_MULTI_ATTACH
CUSTOM_IMAGE_TYPE_RBD          ← Custom trait (not compute-owned)
HW_CPU_X86_MMX                 ← CPU feature trait
HW_CPU_X86_SSE
HW_CPU_X86_SSE2
HW_CPU_X86_SVM
```

### Use Case Example

**Scenario**: Host aggregate with compute nodes supporting multi-attach volumes

**Configuration**:
1. Add extra spec to flavor: `trait:COMPUTE_VOLUME_MULTI_ATTACH=required`
2. Restrict flavor to aggregate (normal aggregate configuration)

**Result**: Flavor only schedulable on hosts in aggregate with multi-attach capability

### Trait Ownership Rules

1. **Compute Service Owns COMPUTE_* Traits**
   - Automatically added/removed on service start
   - Updated by `update_available_resource` periodic task
   - Interval: `update_resources_interval` config option

2. **Custom Traits NOT Removed**
   - `CUSTOM_*` traits set externally are preserved
   - Only compute-owned traits are managed

3. **External Removal Recovery**
   - If compute-owned traits removed externally (e.g., via `openstack resource provider trait delete`)
   - Re-added on nova-compute restart or SIGHUP

4. **Unsupported Trait Removal**
   - If unsupported compute trait added externally
   - Automatically removed on restart or SIGHUP

5. **Standard Traits Only**
   - Compute capability traits defined in os-traits library
   - Repository: https://opendev.org/openstack/os-traits/src/branch/master/os_traits/compute

### Best Practices

**CPU Features**: Use traits instead of ComputeCapabilitiesFilter when possible
- Consistent naming across virt drivers
- Efficient querying
- Standard trait definitions

**Reference**: See taxonomy_of_traits_and_capabilities in Technical Reference Deep Dives

---

## Custom Extensions

### Writing Your Own Filter

#### Requirements

1. **Inherit from BaseHostFilter**
   - Located in `nova.scheduler.filters`

2. **Implement `host_passes` Method**
   - Parameters:
     - `host_state`: HostState object (host attributes)
     - `spec_obj`: RequestSpec object (user request, flavor, image, scheduler hints)
   - Return: `True` (pass) or `False` (reject)

3. **Register Extra Spec Validators** (if using non-standard extra specs)
   - Examples in `nova.api.validation.extra_specs`
   - Register via `nova.api.extra_spec_validator` entrypoint

4. **Package and Deploy**
   - Must be available to nova-scheduler and nova-api-wsgi services

#### Example Package Structure

```
acmefilter/
  acmefilter/
    __init__.py      ← Filter implementation
    validators.py    ← Extra spec validators
  setup.py           ← Package configuration
```

#### Example Filter Implementation

**File: `__init__.py`**
```python
from oslo_log import log as logging
from nova.scheduler import filters

LOG = logging.getLogger(__name__)

class AcmeFilter(filters.BaseHostFilter):
    def host_passes(self, host_state, spec_obj):
        extra_spec = spec_obj.flavor.extra_specs.get('acme:foo')
        LOG.info("Extra spec value was '%s'", extra_spec)
        
        # Add meaningful filtering logic here
        
        return True
```

#### Example Validator Registration

**File: `validators.py`**
```python
from nova.api.validation.extra_specs import base

def register():
    validators = [
        base.ExtraSpecValidator(
            name='acme:foo',
            description='My custom extra spec.',
            value={
                'type': str,
                'enum': ['bar', 'baz'],
            },
        ),
    ]
    return validators
```

#### Example Setup Configuration

**File: `setup.py`**
```python
from setuptools import setup

setup(
    name='acmefilter',
    version='0.1',
    description='My custom filter',
    packages=['acmefilter'],
    entry_points={
        'nova.api.extra_spec_validators': [
            'acme = acmefilter.validators',
        ],
    },
)
```

#### Nova Configuration

**File: `nova.conf`**
```ini
[filter_scheduler]
available_filters = nova.scheduler.filters.all_filters
available_filters = acmefilter.AcmeFilter
enabled_filters = ComputeFilter,AcmeFilter
```

**Important**: ⚠️ Must add to `available_filters` AND `enabled_filters`

### Writing Your Own Weigher

#### Requirements

1. **Inherit from BaseHostWeigher**
   - Located in `nova.scheduler.weights`

2. **Implement Methods** (choose one approach)

   **Approach 1: Simple Weighing**
   - `weight_multiplier()`: Return multiplier value
   - `_weight_object(obj, weight_properties)`: Return weight for single object

   **Approach 2: Batch Weighing**
   - `weight_objects(obj_list, weight_properties)`: Return list of weights for all objects
   - Used when need access to all objects for weight calculation
   - Don't modify object weights directly (normalization happens separately)

#### Implementation Notes

- Final weights normalized and computed by `weight.BaseWeightHandler`
- Return weight values, not normalized values
- Multiplier applied after normalization

---

## Historical Context and Evolution

### Problems with Legacy Scheduler

#### 1. Tight Coupling
- Scheduler tightly coupled with rest of Nova
- Limited capabilities, accuracy, flexibility, maintainability
- Difficult to work on scheduler in isolation

#### 2. Cross-Project Affinity Challenges
- Boot from volume: Want compute near shared storage
- Network ports: Want compute near port location
- No good mechanism to handle these relationships

#### 3. Limited Filter Scheduler Alternatives
- Different use cases may need radically different schedulers
- Single strong scheduler interface needed for innovation
- Example: Solver scheduler for complex optimization

#### 4. Project Scale Issues
- Nova team lacking bandwidth for all scheduler requests
- Frequent requests for new filters/weighers
- Tight coupling prevents independent scheduler team

### Evolution Goals

#### 1. Versioned Scheduler Placement Interfaces
**Problem**: Dictionaries passed over RPC, backward compatibility issues

**Solution**: oslo.versionedobjects infrastructure for versioned data models

**Focus**: RequestSpec object modeling

#### 2. Host and Node Stats
**Problem**: Need clean data model for compute → scheduler communication

**Goal**: Enable scheduler to have its own database eventually

**Related**: Resource tracker work

#### 3. External Data Integration
**Future**: Send Cinder and Neutron data to scheduler for better decisions

#### 4. Resource Tracker Improvements
**Problem**: No good pattern to extend resource tracker

**Challenge**: NUMA and PCI passthrough exposed limitations

**Solution**: Resource providers model rethink

#### 5. Parallelism and Concurrency
**Problem**: Very racy design, excessive build retries

**Impact**: NUMA features particularly affected

**Current Workaround**: Single scheduler process with small greenthread pool

**Scale Challenge**: 
- Current: Works <1k nodes
- Future Need: 10k+ nodes (cells v2)

**Proposed Solutions**:
- Two-phase commit style resource tracker claims
- Incremental updates (potentially with Kafka)
- Reduce race conditions between multiple scheduler processes

### Key Milestones

- **Pre-Kilo**: Dictionaries over RPC
- **Kilo**: Start using oslo.versionedobjects
- **Rocky**: Prefilters introduction for efficiency
- **Stein (19.0.0)**: Compute capabilities as traits, allocation ratio improvements
- **Train (20.0.0)**: Multiple prefilters (image type, disabled status, isolate aggregates)
- **Ussuri (21.0.0)**: CrossCellWeigher
- **Wallaby (23.0.0)**: Custom scheduler drivers removed (filter scheduler only)
- **Bobcat (28.0.0)**: HypervisorVersionWeigher, NumInstancesWeigher
- **Antelope (27.0.0)**: Allocation ratio default changes
- **Epoxy (31.0.0)**: ImagePropertiesWeigher

### Utilization-Aware Scheduling

**Status**: ⚠️ Poorly tested, may not work as expected, may be removed

**Purpose**: Advanced scheduling based on enhanced usage statistics:
- Memory cache utilization
- Memory bandwidth utilization
- Network bandwidth utilization

**Config**: `metrics.weight_setting`

**Example**:
```ini
[metrics]
weight_setting = "metric1=ratio1, metric2=ratio2"
```

### Cells Considerations

**Feature**: Cells can be disabled for scheduling (maintenance, failures)

**Management**: 
- `nova-manage cell_v2 update_cell`: Enable/disable existing cell
- `nova-manage cell_v2 create_cell`: Create pre-disabled cell

**Important**: ⚠️ Restart or SIGHUP nova-scheduler after cell changes

---

## Quick Reference Tables

### Default Enabled Filters
1. AvailabilityZoneFilter (via prefilter)
2. ComputeFilter
3. ComputeCapabilitiesFilter
4. ImagePropertiesFilter
5. ServerGroupAntiAffinityFilter
6. ServerGroupAffinityFilter

### Mandatory Components
1. Compute Disabled Status prefilter (Train+)
2. ComputeFilter (should always enable)

### Config Option Quick Finder

| Component | Config Option | Default |
|-----------|--------------|---------|
| **Filters** | | |
| Available | filter_scheduler.available_filters | nova.scheduler.filters.all_filters |
| Enabled | filter_scheduler.enabled_filters | [list] |
| Max I/O ops | filter_scheduler.max_io_ops_per_host | - |
| Max instances | filter_scheduler.max_instances_per_host | - |
| Isolated hosts | filter_scheduler.isolated_hosts | - |
| Isolated images | filter_scheduler.isolated_images | - |
| **Weighers** | | |
| Weight classes | filter_scheduler.weight_classes | - |
| Host subset | filter_scheduler.host_subset_size | 1 |
| RAM multiplier | filter_scheduler.ram_weight_multiplier | 1.0 |
| CPU multiplier | filter_scheduler.cpu_weight_multiplier | 1.0 |
| Disk multiplier | filter_scheduler.disk_weight_multiplier | 1.0 |
| **Allocation Ratios** | | |
| CPU override | cpu_allocation_ratio | None |
| RAM override | ram_allocation_ratio | None |
| Disk override | disk_allocation_ratio | None |
| Initial CPU | initial_cpu_allocation_ratio | 4.0 (27.0.0+) |
| Initial RAM | initial_ram_allocation_ratio | 1.0 (27.0.0+) |
| Initial disk | initial_disk_allocation_ratio | 1.0 |
| **Reserved Resources** | | |
| Reserved CPUs | reserved_host_cpus | - |
| Reserved RAM | reserved_host_memory_mb | - |
| Reserved disk | reserved_host_disk_mb | - |
| **Scheduler** | | |
| Max attempts | scheduler.max_attempts | 3 |
| Image type support | scheduler.query_placement_for_image_type_support | False |
| Isolated aggregates | scheduler.enable_isolated_aggregate_filtering | False |
| **Resource Tracking** | | |
| Update interval | update_resources_interval | 0 |

### Trait Prefixes

| Prefix | Owner | Example | Purpose |
|--------|-------|---------|---------|
| COMPUTE_ | nova-compute | COMPUTE_VOLUME_MULTI_ATTACH | Driver capabilities |
| HW_ | os-traits | HW_CPU_X86_SSE2 | Hardware features |
| CUSTOM_ | External | CUSTOM_LICENSED_WINDOWS | Custom deployment needs |

### Common Extra Spec Patterns

| Pattern | Example | Purpose |
|---------|---------|---------|
| capabilities:key | capabilities:cpu_info:features | ComputeCapabilitiesFilter |
| aggregate_instance_extra_specs | aggregate_instance_extra_specs:ssd=true | AggregateInstanceExtraSpecsFilter |
| trait:NAME=required | trait:COMPUTE_VOLUME_EXTEND=required | Required trait |
| trait:NAME=forbidden | trait:CUSTOM_SLOW_DISK=forbidden | Forbidden trait |
| resources:RESOURCE_CLASS | resources:VCPU=4 | Placement resource request |

---

## LLM Query Optimization Tips

### For Answering "How do I...?" Questions

1. **"How do I isolate workloads?"**
   - See: Isolate Aggregates prefilter, AggregateMultiTenancyIsolation, IsolatedHostsFilter

2. **"How do I control resource usage?"**
   - See: Allocation Ratios section, Reserved Resources

3. **"How do I prefer certain hosts?"**
   - See: Weighers section (RAMWeigher, CPUWeigher, custom weighers)

4. **"How do I restrict instances?"**
   - See: Filters section (especially Aggregate-Based Filters)

5. **"How do I use traits?"**
   - See: Compute Capabilities as Traits section

6. **"Should I use hints or extra specs?"**
   - See: Scheduler Hints vs Flavor Extra Specs section

### For Understanding Workflow Questions

1. **"What happens when I boot an instance?"**
   - See: Scheduling Workflow section (step-by-step process)

2. **"How does placement work with scheduler?"**
   - See: Scheduling Workflow steps 2-5, 9-10

3. **"When are filters vs weighers used?"**
   - See: Core Concepts (filters are binary, weighers rank)

4. **"What's the difference between prefilters and filters?"**
   - See: Prefilters section (efficiency optimization before filtering)

### For Configuration Questions

1. **"What should I configure for production?"**
   - See: Default Enabled Filters, Mandatory Components, Allocation Ratios

2. **"How do I tune performance?"**
   - See: Filter order (Performance Considerations), Per-Aggregate Multipliers

3. **"What are sensible defaults?"**
   - See: Version History Summary (allocation ratios), Config Option Quick Finder

### Document Metadata

**Source Documents**:
- `ref/docs/nova/admin/scheduling.rst`
- `ref/src/nova/doc/source/admin/scheduling.rst`
- `ref/src/nova/doc/source/reference/scheduler-hints-vs-flavor-extra-specs.rst`
- `ref/src/nova/doc/source/reference/scheduler-evolution.rst`
- `ref/src/nova/doc/source/reference/scheduling.rst`
- `ref/src/nova/doc/source/reference/isolate-aggregates.rst`

**Last Updated**: 2025-12-05

**Target Audience**: LLMs, developers, operators

**Completeness**: Comprehensive coverage of Nova scheduling as of Epoxy (31.0.0) release

