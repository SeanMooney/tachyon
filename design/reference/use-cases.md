# Tachyon Use Cases

This document describes the use cases that Tachyon must support to serve as a
complete replacement for Nova's scheduler and Placement API.

## Tachyon-Specific Use Cases

As a cloud operator, I want the scheduler to prefer hosts that closely
match the requested resources and traits without having many unused
specialized capabilities, so that specialized resources remain available
for workloads that actually need them.

As a cloud operator, I want to optimize resource utilization by
directing simple workloads to simple hosts and complex workloads to
hosts with specialized capabilities, maximizing the effective use of
heterogeneous infrastructure without needing to manually partition hosts
using host aggregates.

As a cloud operator, I want better placement decisions when using
custom resource classes such as those used by pci in placement
``CUSTOM_PCI_<vendor_id>_<product_id>`` or vGPUs ``CUSTOM_<type>``
without needing to implement a custom weigher for each resource.

As a cloud operator, I want to be able to express preferred and
avoided traits in the scheduler and flavor, so that I can optimize
the placement decisions based on soft constraints.

As an operator, I want a reliable, semi real-time view of all consumable
resources on each compute node so that I can make placement and capacity
decisions without needing direct database access, configuration access, or
host introspection.

As a service-level, third-party orchestrator, I want to translate PCI alias
names into concrete resource requirements so that I can select suitable
hosts for workloads without scraping multiple Nova and Placement APIs.

As a Watcher developer, I want to consume a stream of versioned Nova resource
notifications to maintain a near real-time model of cloud resources and
topology so that I can avoid heavy polling of Placement and hypervisor APIs
to rebuild the full state of all compute nodes.

As a Watcher developer, I need Enhanced Platform awareness to be able
to optimize NFV and AI workloads. i.e. any workload that uses NUMA
affinity, hugepages, CPU pinning, device passthrough, SR-IOV or DPDK
networking or other specialized hardware like VGPUs and generic mdev
devices.

As a Watcher developer, I need to be able to track network availability
(physnet and L3 segment connectivity) and bandwidth or packets per
second usage to do optimized VM placement while avoiding network
congestion.

As a Watcher developer, I need to account for live migration
constraints such as hypervisor type and version or storage constraints
such as ceph usage.

As a Nova developer and operator, I want resource notifications to expose the
necessary and sufficient information external systems need to build an
accurate model of schedulable resources, while still respecting constraints on
notification volume and payload size so that we do not significantly impact
the performance of the notification bus or compute services.


## Nova Scheduling Capabilities Tachyon Must Support

The following is a comprehensive summary of all scheduling use cases currently
supported by Nova and Placement that Tachyon must implement to serve as a
full replacement.

### Resource Allocation and Quantitative Scheduling

As an operator, I want to schedule workloads based on basic compute resources
(VCPU, MEMORY_MB, DISK_GB) with configurable allocation ratios to support
overcommit policies for CPU, memory, and disk.

As an operator, I want to configure allocation ratios in two modes:
- Override mode (cpu_allocation_ratio, ram_allocation_ratio,
  disk_allocation_ratio) where nova-compute always overwrites any
  externally-set values
- Initial mode (initial_cpu_allocation_ratio, initial_ram_allocation_ratio,
  initial_disk_allocation_ratio) where initial values are set but can be
  adjusted via the Placement API without configuration changes

As an operator, I want to reserve host resources (reserved_host_cpus,
reserved_host_memory_mb, reserved_host_disk_mb) that will not be consumed
by instances, whether overcommitted or not, to account for hypervisor
overhead.

As an operator, I want to define and consume custom resource classes
(e.g., CUSTOM_BAREMETAL_SMALL, CUSTOM_FPGA, VGPU) to model specialized
hardware beyond standard compute resources.

As an operator, I want to model resource provider trees with nested providers
so that child resources (such as NUMA nodes, SR-IOV VFs, or vGPUs) can be
tracked under their parent physical devices while maintaining proper
inventory isolation.

As an operator, I want to configure sharing resource providers so that
resources like shared storage pools (DISK_GB) can be consumed by multiple
compute hosts through aggregate associations.

As a user, I want to request resources from multiple providers using granular
resource request groups with configurable isolation policies (isolate vs none)
to control whether resources come from the same or different providers.

### Qualitative Scheduling via Traits

As an operator, I want to require specific traits on compute hosts through
flavor extra specs (e.g., ``trait:HW_CPU_X86_AVX2=required``) so that
workloads land on hosts with the necessary capabilities.

As an operator, I want to forbid specific traits (e.g.,
``trait:CUSTOM_WINDOWS_LICENSE_POOL=forbidden``) to prevent workloads from
landing on hosts with certain characteristics.

As an operator, I want to filter based on root provider traits
(e.g., COMPUTE_VOLUME_MULTI_ATTACH, COMPUTE_TRUSTED_CERTS) that represent
host-level capabilities independent of specific resource inventories.

As an operator, I want compute capabilities to be automatically reported as
traits so that I can schedule based on driver features like multi-attach
volume support, device tagging, and network interface attachment capabilities.

As a user, I want to specify image metadata traits (e.g., hw_architecture,
img_hv_type) so that instances are scheduled only on compatible hypervisors.

### Host Aggregates and Availability Zones

As an operator, I want to partition my cloud into host aggregates with
metadata so that I can direct workloads with matching flavor extra specs
to specific groups of hosts (e.g., SSD-backed hosts, GPU hosts).

As an operator, I want to isolate tenants to specific host aggregates using
the filter_tenant_id metadata so that certain projects can only schedule
to designated hosts.

As an operator, I want to expose host aggregates as availability zones so
that users can explicitly request placement in specific failure domains or
geographic locations.

As an operator, I want to configure per-aggregate weight multipliers
(e.g., ram_weight_multiplier, cpu_weight_multiplier) so that I can tune
scheduling behavior differently across host groups.

As an operator, I want to isolate images to specific aggregates based on
image properties (e.g., os_distro=windows) so that specialized images only
run on appropriately configured hosts.

### Server Groups (Affinity and Anti-Affinity)

As a user, I want to create server groups with affinity policy so that all
my instances in the group are scheduled to the same host to minimize
network latency between them.

As a user, I want to create server groups with anti-affinity policy so that
my instances are spread across different hosts for fault tolerance.

As a user, I want soft-affinity and soft-anti-affinity policies so that the
scheduler attempts to honor my preference but can still place instances when
strict compliance is not possible.

As an operator, I want to configure max_server_per_host rules for
anti-affinity groups so that I can control how many instances from the same
group can land on a single host.

### NUMA Topology and CPU Management

As an operator, I want NUMA-aware scheduling so that instances with NUMA
topology requirements are placed on hosts where their vCPUs and memory can
be properly affinitized to host NUMA nodes.

As a user, I want to request dedicated CPU pinning (hw:cpu_policy=dedicated)
so that my instance vCPUs are exclusively pinned to host pCPUs without
sharing with other instances.

As a user, I want mixed CPU policy so that I can have some vCPUs pinned
(for real-time workloads) and others shared (for less critical threads)
within the same instance.

As a user, I want to control emulator thread pinning so that hypervisor
overhead threads run on dedicated cores separate from my instance vCPUs.

As a user, I want to specify CPU thread policies (require, isolate, prefer)
to control whether my instance uses SMT/Hyperthreading siblings.

As a user, I want to customize my instance CPU topology (sockets, cores,
threads) for software licensing or performance optimization purposes.

As an operator, I want NUMA-aware live migration so that instances with
NUMA topology, CPU pinning, or hugepages can be live migrated while
properly recalculating their NUMA mappings on the destination host.

### Memory Management

As a user, I want to request huge pages (2MB or 1GB) for my instance so
that memory-intensive workloads benefit from reduced TLB misses and
improved memory access performance.

As a user, I want the scheduler to ensure my huge page requirements can
be satisfied from a single NUMA node when I also request NUMA affinity.

As an operator, I want to restrict huge page usage through flavor settings
(hw:mem_page_size=small) to prevent users from consuming limited huge page
resources when not needed.

### PCI Passthrough and SR-IOV

As a user, I want to request PCI device passthrough through flavor extra
specs (pci_passthrough:alias) so that my instance has direct access to
physical devices like GPUs, FPGAs, or network accelerators.

As an operator, I want to configure PCI device specifications with vendor_id,
product_id, and address filters so that I control which devices are available
for passthrough.

As an operator, I want to define PCI aliases that map friendly names to
device specifications so that users can request devices without knowing
hardware details.

As a user, I want to request SR-IOV virtual functions (type-VF) for
high-performance networking with near-native I/O performance.

As an operator, I want PCI-NUMA affinity policies (required, preferred,
socket, legacy) to control how strictly PCI devices must be affined to
the same NUMA node as the instance.

As an operator, I want PCI devices tracked in Placement using custom
resource classes and traits so that scheduling decisions can leverage
Placement's efficient filtering.

As an operator, I want to mark VFs as trusted so that instances can enable
promiscuous mode or change MAC addresses when the network controller allows.

As an operator, I want to support remote-managed devices (SmartNIC DPUs) with
proper tagging so that they are not accidentally allocated to regular
PCI passthrough requests.

### Virtual GPUs (vGPU)

As a user, I want to request virtual GPU resources (VGPU) so that my instance
can leverage GPU acceleration for graphics or compute workloads.

As an operator, I want to configure multiple vGPU types per physical GPU so
that different performance tiers can be offered (e.g., nvidia-35, nvidia-36).

As an operator, I want vGPUs modeled as child resource providers under their
parent physical GPU so that Placement correctly tracks inventory and
allocations per physical device.

As an operator, I want to use custom traits to differentiate vGPU types so
that users can request specific GPU capabilities through flavor extra specs.

As an operator, I want vGPU live migration support (where hardware allows) so
that instances with virtual GPUs can be migrated without service interruption.

### Network-Aware Scheduling

As a user, I want to boot instances with neutron ports that have resource
requests (e.g., QoS minimum bandwidth rules) so that network performance
guarantees are enforced through Placement allocations.

As an operator, I want SR-IOV ports scheduled based on physical network
connectivity (physnet) so that VFs are allocated from NICs connected to
the correct network segments.

As an operator, I want the scheduler to handle extended resource requests
where a single port may require multiple resource groups (e.g., both
minimum bandwidth and minimum packet rate).

As a user, I want group_policy (isolate/none) to control whether multiple
SR-IOV ports use VFs from the same or different physical functions.

### Scheduler Prefilters

As an operator, I want a prefilter to exclude compute nodes that do not
support the disk_format of the boot image (e.g., exclude ceph-backed
computes that cannot run qcow2 images without expensive conversion).

As an operator, I want disabled compute nodes to be automatically excluded
via the COMPUTE_STATUS_DISABLED trait so that hosts marked as disabled in
the os-services API are not considered for scheduling.

As an operator, I want aggregate isolation prefiltering so that traits
required in a server's flavor and image must match the traits required
in an aggregate's metadata for the server to be eligible on those hosts.

### Scheduler Filters

As an operator, I want the ComputeFilter to exclude hosts where the
nova-compute service is disabled or down.

As an operator, I want the ImagePropertiesFilter to ensure instances only
schedule on hosts matching required architecture (hw_architecture),
hypervisor type (img_hv_type), hypervisor version (img_hv_requested_version),
and VM mode (hw_vm_mode) from image metadata.

As an operator, I want the NUMATopologyFilter to validate that hosts can
satisfy instance NUMA requirements including CPU pinning, hugepages, and
memory placement.

As an operator, I want the PciPassthroughFilter to verify that hosts have
available PCI devices matching flavor PCI alias requests.

As an operator, I want ServerGroupAffinityFilter and
ServerGroupAntiAffinityFilter to enforce server group placement policies.

As an operator, I want aggregate-based filters including:
- AggregateInstanceExtraSpecsFilter to match flavor extra specs scoped with
  aggregate_instance_extra_specs against aggregate metadata
- AggregateImagePropertiesIsolation to match image properties against
  aggregate metadata
- AggregateMultiTenancyIsolation to restrict hosts with filter_tenant_id
  metadata to specific tenants
- AggregateIoOpsFilter to enforce per-aggregate max_io_ops_per_host limits
- AggregateNumInstancesFilter to enforce per-aggregate max_instances_per_host
- AggregateTypeAffinityFilter to restrict aggregates to specific flavor names
  via instance_type metadata

As an operator, I want the ComputeCapabilitiesFilter to match flavor extra
specs against compute host capabilities (free_ram_mb, free_disk_mb, host,
hypervisor_type, hypervisor_version, num_instances, num_io_ops, vcpus_total,
vcpus_used) with support for comparison operators (=, ==, !=, >=, <=, s==,
s!=, <in>, <all-in>, <or>).

As an operator, I want the IoOpsFilter to exclude hosts with too many
concurrent I/O operations (instances in build, resize, snapshot, migrate,
rescue, or unshelve states) based on max_io_ops_per_host.

As an operator, I want the NumInstancesFilter to exclude hosts running more
instances than max_instances_per_host allows.

As an operator, I want the MetricsFilter to exclude hosts that do not report
the metrics required by the MetricsWeigher, ensuring weighing does not fail.

As an operator, I want the IsolatedHostsFilter to define isolated sets of
images and hosts where isolated images can only run on isolated hosts and
optionally isolated hosts can only run isolated images.

As a user, I want the DifferentHostFilter to schedule my instance on a
different host from a specified set of instances using the different_host
scheduler hint.

As a user, I want the SameHostFilter to schedule my instance on the same
host as specified instances using the same_host scheduler hint.

As a user, I want the SimpleCIDRAffinityFilter to schedule instances based
on host IP subnet range using build_near_host_ip and cidr scheduler hints.

As a user, I want the JsonFilter to construct custom filter queries using
JSON-formatted scheduler hints with operators (=, <, >, in, <=, >=, not,
or, and) against host state variables ($free_ram_mb, $free_disk_mb,
$hypervisor_hostname, $total_usable_ram_mb, $vcpus_total, $vcpus_used).

As an operator, I want the AllHostsFilter available as a no-op filter that
accepts all hosts for testing or special scheduling scenarios.

As an operator, I want to implement custom filters to extend scheduling
logic for site-specific requirements, with the ability to register custom
extra spec validators.

### Scheduler Weighers

As an operator, I want resource-based weighers (RAMWeigher, CPUWeigher,
DiskWeigher) to prefer hosts with more (or less, for stacking) available
resources, with configurable weight multipliers that can be negative for
stacking instead of spreading.

As an operator, I want IoOpsWeigher to avoid hosts with many concurrent I/O
operations (instances in building vm_state or resize_migrating, rebuilding,
resize_prep, image_snapshot, image_backup, rescuing, or unshelving
task_states).

As an operator, I want PCIWeigher to prefer hosts with PCI devices for PCI
workloads and avoid wasting PCI-capable hosts on non-PCI workloads. The
weigher must only use positive multipliers to prevent non-PCI instances
from being pushed away from non-PCI hosts.

As an operator, I want BuildFailureWeigher to deprioritize hosts with recent
boot failures to improve scheduling success rates, with a high default
multiplier to give this weigher priority over resource-based weighers.

As an operator, I want ServerGroupSoftAffinityWeigher and
ServerGroupSoftAntiAffinityWeigher to implement soft affinity preferences
when hard constraints cannot be met, preferring hosts with more (affinity)
or fewer (anti-affinity) instances from the same server group.

As an operator, I want MetricsWeigher to make scheduling decisions based on
custom metrics reported by compute nodes, with configurable metric names and
weight ratios (e.g., name1=1.0, name2=-1.0), and handling for required vs
optional metrics.

As an operator, I want CrossCellWeigher to prefer local cells during move
operations to minimize cross-cell migration overhead.

As an operator, I want HypervisorVersionWeigher to prefer hosts with newer
(or older) hypervisor versions for controlled rollouts, understanding that
version numbers are not comparable across different hypervisor types.

As an operator, I want NumInstancesWeigher to balance instance counts across
hosts (spread with negative multiplier) or consolidate onto fewer hosts
(pack with positive multiplier).

As an operator, I want ImagePropertiesWeigher to co-locate instances using
similar image properties (os_distro, hw_machine_type, etc.) for cache
efficiency, with configurable property weights.

As an operator, I want to configure per-aggregate weight multiplier overrides
(ram_weight_multiplier, cpu_weight_multiplier, disk_weight_multiplier,
io_ops_weight_multiplier, pci_weight_multiplier, soft_affinity_weight_multiplier,
soft_anti_affinity_weight_multiplier, build_failure_weight_multiplier,
cross_cell_move_weight_multiplier, metrics_weight_multiplier) so that weigher
behavior can differ across host groups.

As an operator, I want host_subset_size configuration to control how many
of the top-weighted hosts are considered for random selection to provide
load distribution.

As an operator, I want to implement custom weighers by inheriting from
BaseHostWeigher and implementing weight_multiplier and _weight_object
methods or the weight_objects method for access to all hosts.

### Instance Lifecycle and Move Operations

As an operator, I want the scheduler involved in live migration to validate
that the destination host meets all instance requirements including NUMA
topology, PCI devices, and resource availability.

As an operator, I want cold migration (resize) to use the scheduler to find
suitable destination hosts that can accommodate the new flavor requirements.

As an operator, I want evacuate operations to use the scheduler to find
alternative hosts when the original host has failed, with support for
administrator-specified target hosts that are validated by the scheduler.

As an operator, I want unshelve operations to reschedule instances that were
shelve-offloaded back to appropriate hosts.

As an operator, I want cross-cell migration support so that instances can be
moved between cells in a multi-cell deployment.

### Cells Scheduling Considerations

As an operator, I want to enable or disable scheduling to specific cells
so that I can perform cell maintenance, handle failures, or manage capacity
without removing hosts from the deployment.

As an operator, I want to create pre-disabled cells so that new cells can be
added to the deployment without immediately receiving workloads.

As an operator, I want cell enable/disable changes to take effect after a
scheduler service restart or SIGHUP signal.

### Placement Query Features

As an operator, I want the allocation candidates API to return valid
combinations of resource providers that can satisfy complex requests
including nested providers and sharing providers.

As an operator, I want member_of query support to filter candidates to hosts
in specific aggregates for availability zone or host aggregate targeting.

As an operator, I want in_tree filtering to constrain resource selection to
specific provider trees or subtrees.

As an operator, I want same_subtree constraints to ensure related resources
(e.g., VCPU and FPGA) come from providers that share a common ancestor
(same NUMA node or same physical device).

As an operator, I want resourceless request groups to specify trait
requirements for providers without requiring resource allocation from them.

As an operator, I want forbidden aggregate membership queries to exclude
hosts in specific aggregates from consideration.

