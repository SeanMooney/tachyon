# Nova Data Model Reference

**Purpose:** Comprehensive reference for OpenStack Nova data model entities, optimized for LLM consumption and Tachyon implementation.

**Focus:** Scheduling-relevant entities, flavor extra specs, and image properties.

**Keywords:** nova, openstack, scheduling, flavor, extra_specs, image_properties, instance, compute_node, placement, numa, pci, migration

---

## Table of Contents

1. [Core Scheduling Entities](#core-scheduling-entities)
   - Instance (Virtual Machine)
   - Flavor (Instance Type)
   - ComputeNode
   - Migration
   - BlockDeviceMapping
2. [Flavor Extra Specs Reference](#flavor-extra-specs-reference)
   - Quick Reference Table
   - Detailed Specifications by Namespace
3. [Image Properties Reference](#image-properties-reference)
   - Quick Reference Table
   - Detailed Specifications by Category
4. [NUMA and CPU Topology](#numa-and-cpu-topology)
5. [PCI Devices](#pci-devices)
6. [Server Groups](#server-groups)
7. [Service Management](#service-management)
8. [Request Context](#request-context)
9. [Key Relationships](#key-relationships)
10. [State Machines](#state-machine)
11. [Database Tables](#database-tables-key)
12. [Configuration Impact](#configuration-impact-on-scheduling)

---

## Core Scheduling Entities

**Section ID:** `core-entities`

This section describes the primary data model entities used in Nova scheduling.

### Instance (Virtual Machine)

**Entity Type:** Core scheduling entity  
**Database Table:** `instances`  
**Key Fields:** `uuid`, `host`, `node`, `vm_state`, `flavor`

The central entity representing a guest VM.

```
Instance:
  id:                       int           # internal DB ID
  uuid:                     UUID          # external identifier
  user_id:                  string        # Keystone user UUID
  project_id:               string        # Keystone project/tenant UUID
  
  # Image and boot
  image_ref:                string        # Glance image UUID
  kernel_id:                string|null   # kernel image UUID
  ramdisk_id:               string|null   # ramdisk image UUID
  
  # Resource requirements (from flavor)
  memory_mb:                int           # RAM in MB
  vcpus:                    int           # vCPU count
  root_gb:                  int           # root disk size
  ephemeral_gb:             int           # ephemeral disk size
  ephemeral_key_uuid:       UUID|null     # encryption key for ephemeral
  
  # Placement
  host:                     string|null   # compute host name
  node:                     string|null   # hypervisor node (e.g., NUMA node)
  compute_id:               int|null      # FK to ComputeNode
  availability_zone:        string|null   # requested AZ
  
  # State
  vm_state:                 string        # ACTIVE, BUILDING, PAUSED, SUSPENDED, etc.
  task_state:               string|null   # spawning, migrating, resizing, etc.
  power_state:              int           # NOSTATE=0, RUNNING=1, PAUSED=3, etc.
  
  # Flavor
  instance_type_id:         int|null      # FK to flavor (deprecated)
  flavor:                   Flavor        # current flavor object
  old_flavor:               Flavor|null   # flavor before resize
  new_flavor:               Flavor|null   # target flavor for resize
  
  # Identity
  display_name:             string|null   # user-visible name
  display_description:      string|null   # user description
  hostname:                 string|null   # guest hostname
  
  # Networking
  access_ip_v4:             IPv4|null     # primary IPv4
  access_ip_v6:             IPv6|null     # primary IPv6
  
  # Lifecycle
  launched_at:              datetime|null
  terminated_at:            datetime|null
  launched_on:              string|null   # original host
  
  # Configuration
  key_name:                 string|null   # SSH keypair name
  config_drive:             string|null   # config drive config
  user_data:                text|null     # cloud-init user data
  
  # Security
  locked:                   bool          # admin/owner lock
  locked_by:                enum|null     # 'owner' | 'admin'
  hidden:                   bool          # hide from user API
  
  # Architecture
  os_type:                  string|null   # linux, windows, etc.
  architecture:             string|null   # x86_64, aarch64, etc.
  vm_mode:                  string|null   # hvm, xen, etc.
  
  # Devices
  root_device_name:         string|null   # /dev/vda, etc.
  default_ephemeral_device: string|null
  default_swap_device:      string|null
  
  # Scheduling metadata
  reservation_id:           string|null   # batch launch ID
  launch_index:             int|null      # index in batch
  
  # Extended attributes (stored in instance_extra table)
  numa_topology:            InstanceNUMATopology|null
  pci_requests:             InstancePCIRequests|null
  pci_devices:              PciDeviceList|null
  device_metadata:          InstanceDeviceMetadata|null
  vcpu_model:               VirtCPUModel|null
  migration_context:        MigrationContext|null
  trusted_certs:            TrustedCerts|null
  resources:                ResourceList|null  # arbitrary resource requests
  
  # Relationships
  metadata:                 dict[str, str]      # user key-value metadata
  system_metadata:          dict[str, str|null] # system key-value metadata
  info_cache:               InstanceInfoCache
  security_groups:          SecurityGroupList
  tags:                     TagList
  keypairs:                 KeyPairList
  fault:                    InstanceFault|null
  
  created_at:               datetime
  updated_at:               datetime
  deleted_at:               datetime|null
  deleted:                  int            # soft delete flag
```

**VM States:**
- `BUILDING`: Instance being created
- `ACTIVE`: Instance is running
- `STOPPED`: Instance shut down
- `PAUSED`: Instance paused in memory
- `SUSPENDED`: Instance hibernated to disk
- `RESIZED`: Resize/migration complete, awaiting confirm
- `ERROR`: Error state
- `DELETED`: Deleted (soft delete)
- `SOFT_DELETED`: User-initiated soft delete

**Task States:** (dozens of transient states during operations)
- `scheduling`, `block_device_mapping`, `networking`
- `spawning`, `image_uploading`, `image_snapshot`
- `resize_prep`, `resize_migrating`, `resize_migrated`
- `rebuilding`, `reboot_pending`, `migrating`

### Flavor (Instance Type)

**Entity Type:** Core scheduling entity  
**Database Table:** `instance_types` (API DB)  
**Key Fields:** `flavorid`, `memory_mb`, `vcpus`, `root_gb`, `extra_specs`

Defines compute, memory, and storage capacity.

```
Flavor:
  id:                int              # internal DB ID
  flavorid:          string           # external ID (e.g., "m1.small")
  name:              string           # display name
  memory_mb:         int              # RAM
  vcpus:             int              # vCPU count
  root_gb:           int              # root disk
  ephemeral_gb:      int              # ephemeral disk
  swap:              int              # swap in MB (0 = no swap)
  rxtx_factor:       float            # network I/O multiplier
  vcpu_weight:       int|null         # CPU scheduling weight
  disabled:          bool             # disabled flag
  is_public:         bool             # public vs private
  description:       string|null      # flavor description
  
  # Extended attributes
  extra_specs:       dict[str, str]   # key-value scheduling hints
  projects:          list[string]     # allowed projects (if not public)
  
  created_at:        datetime
  updated_at:        datetime
  deleted_at:        datetime|null
  deleted:           bool
```

## Flavor Extra Specs Reference

Extra specs are key-value pairs attached to flavors that control scheduling and instance configuration. All extra specs are validated against registered validators.

### Quick Reference: Extra Spec Namespaces

| Namespace | Purpose | Example |
|-----------|---------|--------|
| `resources:` | Placement resource requests | `resources:VCPU=4`, `resources:CUSTOM_GPU=1` |
| `trait:` | Trait requirements/forbiddance | `trait:HW_CPU_X86_AVX2=required` |
| `hw:` | Hardware configuration | `hw:cpu_policy=dedicated`, `hw:numa_nodes=2` |
| `pci_passthrough:` | PCI device passthrough | `pci_passthrough:alias=net1:2` |
| `hw_rng:` | Random number generator | `hw_rng:allowed=true` |
| `hw_video:` | Video RAM limits | `hw_video:ram_max_mb=64` |
| `quota:` | Resource quotas | `quota:cpu_shares=2048` |
| `aggregate_instance_extra_specs:` | Aggregate metadata matching | `aggregate_instance_extra_specs:zone==us-east` |
| `os:` | Operating system settings | `os:secure_boot=required` |
| `vmware:` | VMware-specific | `vmware:hw_version=vmx-13` |
| `accel:` | Accelerator devices | `accel:device_profile=gpu-profile` |
| `capabilities:` | Compute node filtering | `capabilities:hypervisor_type==QEMU` |

**Pattern:** `<namespace>:<key>=<value>` or `<key>=<value>` (non-namespaced)

### Pattern Matching Reference

**CPU Set Format:** `^?N(-M)?(,^?N(-M)?)*`
- `^` = exclude
- `N-M` = range (inclusive)
- `,` = separator
- Examples: `0-3` (CPUs 0,1,2,3), `^0-1` (all except 0,1), `0-3,^2` (0,1,3)

**Resource Group Format:** `[a-zA-Z0-9_-]{1,64}` (optional, 1-64 chars)

**Custom Resource/Trait Pattern:** `CUSTOM_[A-Z0-9_]+`

**Filter Operators (capabilities, aggregate_instance_extra_specs):**
- Numeric: `=`, `==`, `!=`, `>=`, `<=`
- String: `s==`, `s!=`, `s>=`, `s>`, `s<=`, `s<`
- Containment: `<in>`, `<all-in>`
- Logic: `<or>`
- Exact match: specific value

### Resource Requests (`resources:` namespace)

Request Placement resources (standard or custom).

**Standard resources:**
```
resources{group}:VCPU=<N>                    # vCPU count (group optional)
resources{group}:MEMORY_MB=<N>               # memory in MB
resources{group}:DISK_GB=<N>                 # disk in GB
resources{group}:PCPU=<N>                    # physical CPU count
resources{group}:<STANDARD_CLASS>=<N>        # any standard resource class
```

**Custom resources:**
```
resources{group}:CUSTOM_<NAME>=<N>           # custom resource class
```

- `{group}`: Optional resource group name (1-64 chars, alphanumeric, underscore, hyphen)
- Standard resource classes include: VCPU, MEMORY_MB, DISK_GB, PCPU, etc.
- Custom resources must match pattern: `CUSTOM_[A-Z0-9_]+`

**Group policy:**
```
group_policy=isolate|none                    # resource group isolation policy
```

### Trait Requirements (`trait:` namespace)

Require or forbid traits on compute nodes.

**Standard traits:**
```
trait{group}:<TRAIT>=required|forbidden     # require or forbid trait
```

**Custom traits:**
```
trait{group}:CUSTOM_<NAME>=required|forbidden
```

- `{group}`: Optional resource group name (1-64 chars)
- Standard traits include: HW_CPU_X86_AVX2, HW_NIC_SRIOV, COMPUTE_VOLUME_MULTI_ATTACH, etc.
- Custom traits must match pattern: `CUSTOM_[A-Z0-9_]+`
- Examples:
  - `trait:HW_CPU_X86_AVX2=required`
  - `trait:CUSTOM_WINDOWS=forbidden`
  - `root:trait:COMPUTE_VOLUME_MULTI_ATTACH=required`

### Hardware Configuration (`hw:` namespace)

#### CPU Policy and Pinning

| Extra Spec | Type | Values/Format | Description |
|------------|------|---------------|-------------|
| `hw:cpu_policy` | enum | `dedicated\|shared\|mixed` | CPU allocation policy. `dedicated`: pinned, no overcommit. `shared`: can float, no overcommit. `mixed`: per-CPU policy via masks |
| `hw:cpu_thread_policy` | enum | `prefer\|isolate\|require` | Hardware thread policy. `prefer`: prefer hosts with threads (default). `require`: require hardware threads. `isolate`: forbid hardware threads |
| `hw:emulator_threads_policy` | enum | `share\|isolate` | Emulator thread policy. `share`: use shared core pool. `isolate`: dedicated core |
| `hw:cpu_dedicated_mask` | string | `^?N(-M)?(,^?N(-M)?)*` | Guest CPUs to pin (mixed policy). Example: `0-3,^2` (CPUs 0,1,3 pinned) |
| `hw:cpu_realtime` | bool | `true\|false` | Enable realtime priority |
| `hw:cpu_realtime_mask` | string | `(^)?N(-M)?(,(^)?N(-M)?)*` | CPUs excluded from realtime. Example: `^0-1` (all except 0,1) |

**CPU Set Format:** `^?N(-M)?(,^?N(-M)?)*` where `^` excludes, `N-M` is a range, `,` separates entries.

#### NUMA Topology

| Extra Spec | Type | Values/Format | Constraints | Description |
|------------|------|---------------|-------------|-------------|
| `hw:numa_nodes` | int | `<N>` | min: 1 | Number of guest NUMA nodes |
| `hw:numa_cpus.<N>` | string | `<cpuset>` | CPU set format | Guest CPUs for NUMA node N. Example: `hw:numa_cpus.0=0-3` |
| `hw:numa_mem.<N>` | int | `<MB>` | min: 1 | Memory (MB) for NUMA node N. Example: `hw:numa_mem.0=2048` |
| `hw:pci_numa_affinity_policy` | enum | `required\|preferred\|legacy\|socket` | - | PCI device NUMA affinity. `required`: only same NUMA node. `preferred`: prefer same NUMA node. `legacy`: required unless no NUMA info. `socket`: same socket (broader than node) |

#### CPU Topology

| Extra Spec | Type | Values/Format | Constraints | Description |
|------------|------|---------------|-------------|-------------|
| `hw:cpu_sockets` | int | `<N>` | min: 1 | Virtual CPU sockets |
| `hw:cpu_cores` | int | `<N>` | min: 1 | Cores per socket |
| `hw:cpu_threads` | int | `<N>` | min: 1 | Threads per core |
| `hw:cpu_max_sockets` | int | `<N>` | min: 1 | Max sockets (limits image requests) |
| `hw:cpu_max_cores` | int | `<N>` | min: 1 | Max cores per socket (limits image requests) |
| `hw:cpu_max_threads` | int | `<N>` | min: 1 | Max threads per core (limits image requests) |

#### Memory Configuration

| Extra Spec | Type | Values/Format | Description |
|------------|------|---------------|-------------|
| `hw:mem_page_size` | string | `large\|small\|any\|<size>` | Memory page size. `large`: huge pages. `small`: 4KB pages. `any`: no preference. `<size>`: explicit (e.g., `2048KiB`, `2MB`) |
| `hw:locked_memory` | bool | `true\|false` | Lock guest memory (prevent swap). Required for some DMA transfers |
| `hw:mem_encryption` | bool | `true\|false` | Enable memory encryption (AMD SEV) |
| `hw:mem_encryption_model` | enum | `amd-sev\|amd-sev-es` | Memory encryption model. Requires `hw:mem_encryption=true` |

#### Feature Flags

| Extra Spec | Type | Values/Format | Constraints | Description |
|------------|------|---------------|-------------|-------------|
| `hw:hide_hypervisor_id` | bool | `true\|false` | - | Hide hypervisor ID from guest |
| `hw:boot_menu` | bool | `true\|false` | - | Show BIOS boot menu |
| `hw:vif_multiqueue_enabled` | bool | `true\|false` | - | Enable virtio-net multiqueue (queues = vCPU count) |
| `hw:pmem` | string | `<labels>` | Comma-separated | Persistent memory device labels. Example: `pmem0,pmem1` |
| `hw:pmu` | bool | `true\|false` | - | Enable Performance Monitoring Unit (vPMU). Used by perf tools in guest |
| `hw:serial_port_count` | int | `<N>` | min: 0 | Number of serial ports |
| `hw:tpm_model` | enum | `tpm-tis\|tpm-crb` | - | TPM device model |
| `hw:tpm_version` | enum | `1.2\|2.0` | Required if `tpm_model` set | TPM version |
| `hw:tpm_secret_security` | enum | `user\|host\|deployment` | - | TPM secret security policy |
| `hw:watchdog_action` | enum | `none\|pause\|poweroff\|reset\|disabled` | - | Watchdog timer action |
| `hw:viommu_model` | enum | `intel\|smmuv3\|virtio\|auto` | - | Virtual IOMMU model |
| `hw:virtio_packed_ring` | bool | `true\|false` | - | Enable virtio packed ring format |
| `hw:sound_model` | string | `<model>` | - | Sound device model (e.g., `ac97`, `ich6`, `hda`) |
| `hw:usb_model` | string | `<model>` | - | USB controller model (e.g., `piix3-uhci`, `piix4-uhci`, `ehci`) |
| `hw:redirected_usb_ports` | int | `<N>` | 0-15 | Number of USB redirection ports |

#### Ephemeral Storage Encryption

| Extra Spec | Type | Values/Format | Description |
|------------|------|---------------|-------------|
| `hw:ephemeral_encryption` | bool | `true\|false` | Enable ephemeral storage encryption |
| `hw:ephemeral_encryption_format` | enum | `<format>` | Encryption format (e.g., `luks`, `plain`) |

### PCI Passthrough (`pci_passthrough:` namespace)

```
pci_passthrough:alias=<alias>:<count>        # PCI device alias and count
                                              # format: alias:count(,alias:count)*
                                              # example: pci_passthrough:alias=net1:2,gpu1:1
```

### Hardware RNG (`hw_rng:` namespace)

```
hw_rng:allowed=true|false                    # allow RNG device configuration
                                              # (legacy: before 21.0.0 this enabled RNG)
```

```
hw_rng:rate_bytes=<N>                        # bytes per period (min: 0)
```

```
hw_rng:rate_period=<N>                       # period duration in ms (min: 0)
```

### Hardware Video (`hw_video:` namespace)

```
hw_video:ram_max_mb=<N>                      # max video RAM (MB, min: 0)
                                              # limits hw_video_ram image property
```

### Quota and Limits (`quota:` namespace)

#### VMware Quotas

**CPU quotas:**
```
quota:cpu_limit=<MHz>                        # CPU limit in MHz (0 = unlimited, min: 0)
quota:cpu_reservation=<MHz>                  # CPU reservation in MHz
quota:cpu_shares_level=custom|high|normal|low
quota:cpu_shares_share=<N>                   # CPU shares (if level=custom, min: 0)
```

**Memory quotas:**
```
quota:memory_limit=<MB>                      # memory limit in MB (0 = unlimited, min: 0)
quota:memory_reservation=<MB>                # memory reservation in MB
quota:memory_shares_level=custom|high|normal|low
quota:memory_shares_share=<N>                # memory shares (if level=custom, min: 0)
```

**Disk IO quotas:**
```
quota:disk_io_limit=<IOPS>                   # disk IO limit (0 = unlimited, min: 0)
quota:disk_io_reservation=<IOPS>             # disk IO reservation
quota:disk_io_shares_level=custom|high|normal|low
quota:disk_io_shares_share=<N>               # disk IO shares (if level=custom, min: 0)
```

**VIF quotas:**
```
quota:vif_limit=<Mbps>                       # VIF limit in Mbps (0 = unlimited, min: 0)
quota:vif_reservation=<Mbps>                 # VIF reservation in Mbps
quota:vif_shares_level=custom|high|normal|low
quota:vif_shares_share=<N>                   # VIF shares (if level=custom, min: 0)
```

#### Libvirt CPU Quotas

```
quota:cpu_shares=<N>                         # CPU proportional weight (min: 0)
                                              # relative measure (e.g., 2048 = 2x 1024)
```

```
quota:cpu_period=<us>                        # enforcement interval in microseconds (min: 0)
                                              # range: 1,000 - 1,000,000
```

```
quota:cpu_quota=<us>                         # max bandwidth in microseconds
                                              # range: 1,000 - 2^64 or negative
                                              # negative = unlimited
```

#### Libvirt Disk Quotas

```
quota:disk_read_bytes_sec=<bytes>            # read bytes/sec (min: 0)
quota:disk_write_bytes_sec=<bytes>           # write bytes/sec (min: 0)
quota:disk_total_bytes_sec=<bytes>           # total bytes/sec (min: 0)
quota:disk_read_iops_sec=<iops>              # read IOPS/sec (min: 0)
quota:disk_write_iops_sec=<iops>             # write IOPS/sec (min: 0)
quota:disk_total_iops_sec=<iops>             # total IOPS/sec (min: 0)
```

#### Libvirt VIF Quotas (legacy nova-network)

```
quota:vif_inbound_average=<kbps>             # inbound average (min: 0)
quota:vif_outbound_average=<kbps>            # outbound average (min: 0)
quota:vif_inbound_peak=<kbps>                # inbound peak (min: 0)
quota:vif_outbound_peak=<kbps>               # outbound peak (min: 0)
quota:vif_inbound_burst=<kbps>               # inbound burst (min: 0)
quota:vif_outbound_burst=<kbps>              # outbound burst (min: 0)
```

### Aggregate Instance Extra Specs (`aggregate_instance_extra_specs:` namespace)

```
aggregate_instance_extra_specs:<key>=<value> # require aggregate metadata
                                              # value supports filter operators:
                                              # =, ==, !=, >=, <=
                                              # s==, s!=, s>=, s>, s<=, s<
                                              # <in>, <all-in>, <or>
                                              # or specific value
```

### Operating System (`os:` namespace)

```
os:secure_boot=disabled|required              # secure boot requirement
                                              # disabled: no secure boot
                                              # required: require secure boot
```

### VMware (`vmware:` namespace)

```
vmware:hw_version=<version>                  # hardware version string
                                              # e.g., "vmx-13"
```

```
vmware:storage_policy=<policy>                # storage policy name
                                              # requires SPBM enabled
```

### Accelerator (`accel:` namespace)

```
accel:device_profile=<profile>                # device profile name
                                              # "flavor for devices"
```

### Capabilities (`capabilities:` namespace)

Filter compute nodes by capabilities. Used by `ComputeCapabilitiesFilter`.

**Non-nested capabilities:**
```
capabilities:id=<filter>
capabilities:uuid=<filter>
capabilities:host=<filter>
capabilities:vcpus=<filter>
capabilities:memory_mb=<filter>
capabilities:local_gb=<filter>
capabilities:vcpus_used=<filter>
capabilities:memory_mb_used=<filter>
capabilities:local_gb_used=<filter>
capabilities:hypervisor_type=<filter>
capabilities:hypervisor_version=<filter>
capabilities:hypervisor_hostname=<filter>
capabilities:free_ram_mb=<filter>
capabilities:free_disk_gb=<filter>
capabilities:current_workload=<filter>
capabilities:running_vms=<filter>
capabilities:disk_available_least=<filter>
capabilities:host_ip=<filter>
capabilities:mapped=<filter>
capabilities:cpu_allocation_ratio=<filter>
capabilities:ram_allocation_ratio=<filter>
capabilities:disk_allocation_ratio=<filter>
capabilities:total_usable_ram_mb=<filter>
capabilities:total_usable_disk_gb=<filter>
capabilities:disk_mb_used=<filter>
capabilities:free_disk_mb=<filter>
capabilities:vcpus_total=<filter>
capabilities:num_instances=<filter>
capabilities:num_io_ops=<filter>
capabilities:failed_builds=<filter>
capabilities:aggregates=<filter>
capabilities:cell_uuid=<filter>
capabilities:updated=<filter>
```

**Nested capabilities (with optional filters):**
```
capabilities:cpu_info[:<filter>]=<filter>
capabilities:metrics[:<filter>]=<filter>
capabilities:stats[:<filter>]=<filter>
capabilities:numa_topology[:<filter>]=<filter>
capabilities:supported_hv_specs[:<filter>]=<filter>
capabilities:pci_device_pools[:<filter>]=<filter>
capabilities:nodename[:<filter>]=<filter>
capabilities:pci_stats[:<filter>]=<filter>
capabilities:supported_instances[:<filter>]=<filter>
capabilities:limits[:<filter>]=<filter>
capabilities:instances[:<filter>]=<filter>
```

**Filter operators for capabilities:**
- `=`, `==`, `!=`, `>=`, `<=` (numeric comparison)
- `s==`, `s!=`, `s>=`, `s>`, `s<=`, `s<` (string comparison)
- `<in>`, `<all-in>` (substring/containment)
- `<or>` (OR logic)
- Specific value (exact match)

### Non-Namespaced Extra Specs (Deprecated)

```
hide_hypervisor_id=true|false                # DEPRECATED: use hw:hide_hypervisor_id
                                              # not compatible with AggregateInstanceExtraSpecsFilter
```

```
group_policy=isolate|none                    # resource group isolation policy
                                              # isolate: separate resource groups
                                              # none: no isolation
```

## Image Properties Reference

Image properties are metadata attached to Glance images that control instance configuration. Properties prefixed with `hw_` affect guest hardware, `img_` affect image handling, and `os_` affect guest OS setup.

### Quick Reference: Image Property Prefixes

| Prefix | Category | Purpose | Example |
|--------|----------|---------|---------|
| `hw_` | Hardware | Guest VM hardware configuration | `hw_cpu_sockets=2`, `hw_mem_page_size=large` |
| `img_` | Image | Image handling and processing | `img_hv_type=kvm`, `img_config_drive=mandatory` |
| `os_` | Operating System | Guest OS configuration | `os_type=linux`, `os_distro=ubuntu` |
| `trait:` | Traits | Required traits (parsed to `traits_required`) | `trait:HW_CPU_X86_AVX2=required` |

**Note:** Legacy property names are automatically mapped to current names (see Legacy Property Names section).

### Architecture and Emulation

```
hw_architecture=<arch>                       # guest hardware architecture
                                              # e.g., i686, x86_64, ppc64, aarch64
```

```
hw_emulation_architecture=<arch>              # desired emulation architecture
                                              # e.g., i686, x86_64, ppc64
```

### CPU Configuration

| Property | Type | Values/Format | Description |
|----------|------|---------------|-------------|
| `hw_cpu_sockets` | int | `<N>` | Preferred CPU sockets |
| `hw_cpu_cores` | int | `<N>` | Preferred cores per socket |
| `hw_cpu_threads` | int | `<N>` | Preferred threads per core |
| `hw_cpu_max_sockets` | int | `<N>` | Maximum CPU sockets |
| `hw_cpu_max_cores` | int | `<N>` | Maximum cores per socket |
| `hw_cpu_max_threads` | int | `<N>` | Maximum threads per core |
| `hw_cpu_policy` | enum | `dedicated\|shared\|mixed` | CPU allocation policy |
| `hw_cpu_thread_policy` | enum | `require\|prefer\|isolate` | CPU thread policy |
| `hw_cpu_realtime_mask` | string | `<cpuset>` | Realtime CPU mask. Format: `^?N(-M)?(,^?N(-M)?)*`. Example: `^0-1` |

### NUMA Topology

| Property | Type | Values/Format | Constraints | Description |
|----------|------|---------------|-------------|-------------|
| `hw_numa_nodes` | int | `<N>` | max: 128 | Number of guest NUMA nodes |
| `hw_numa_cpus.<N>` | string | `<cpuset>` | CPU spec format | CPUs for NUMA node N. Example: `hw_numa_cpus.0=0-3,^2` |
| `hw_numa_mem.<N>` | int | `<MB>` | - | Memory (MB) for NUMA node N |
| `hw_pci_numa_affinity_policy` | enum | `required\|preferred\|legacy\|socket` | - | PCI NUMA affinity policy |

### Memory Configuration

| Property | Type | Values/Format | Description |
|----------|------|---------------|-------------|
| `hw_mem_page_size` | string | `small\|large\|any\|<size>` | Memory page size. `small`: 4KB. `large`: huge pages. `any`: no preference. `<size>`: explicit (e.g., `2048KiB`) |
| `hw_mem_encryption` | bool | `true\|false` | Enable memory encryption (AMD SEV) |
| `hw_mem_encryption_model` | enum | `amd-sev\|amd-sev-es` | Memory encryption model |
| `hw_locked_memory` | bool | `true\|false` | Lock guest memory (prevent swap) |

### Device Buses and Controllers

| Property | Type | Values/Format | Description |
|----------|------|---------------|-------------|
| `hw_disk_bus` | enum | `virtio\|scsi\|ide\|usb\|lxc\|uml` | Hard disk bus |
| `hw_cdrom_bus` | enum | `virtio\|scsi\|ide\|usb\|lxc\|uml` | CDROM bus |
| `hw_floppy_bus` | enum | `fd\|scsi\|ide` | Floppy disk bus |
| `hw_scsi_model` | string | `virtio-scsi\|lsilogic\|vmpvscsi\|pvscsi\|...` | SCSI controller model |
| `hw_disk_type` | string | `<type>` | Disk allocation mode (e.g., `preallocated`) |

### Network Devices

| Property | Type | Values/Format | Description |
|----------|------|---------------|-------------|
| `hw_vif_model` | enum | `virtio\|e1000\|e1000e\|rtl8139\|ne2k_pci\|pcnet\|lan9118\|igb` | NIC device model |
| `hw_vif_multiqueue_enabled` | bool | `true\|false` | Enable virtio-net multiqueue |
| `hw_viommu_model` | enum | `intel\|smmuv3\|virtio\|auto` | Virtual IOMMU model |

### Video and Display

| Property | Type | Values/Format | Description |
|----------|------|---------------|-------------|
| `hw_video_model` | enum | `cirrus\|vga\|xen\|qxl\|gop\|virtio\|none\|bochs` | Video adapter model |
| `hw_video_ram` | int | `<MB>` | Video RAM in MB (e.g., `64`) |

### Input/Output Devices

| Property | Type | Values/Format | Constraints | Description |
|----------|------|---------------|-------------|-------------|
| `hw_pointer_model` | string | `<model>` | - | Pointer model type |
| `hw_input_bus` | enum | `usb\|virtio` | - | Input bus type |
| `hw_sound_model` | string | `<model>` | - | Sound device model (e.g., `ac97`, `ich6`, `hda`) |
| `hw_usb_model` | string | `<model>` | - | USB controller model (e.g., `piix3-uhci`, `piix4-uhci`, `ehci`) |
| `hw_redirected_usb_ports` | int | `<N>` | max: 15 | Number of USB redirection ports |

### Serial Ports and RNG

```
hw_serial_port_count=<N>                     # number of serial ports
```

```
hw_rng_model=virtio                         # RNG device type
```

### Firmware and Boot

```
hw_firmware_type=bios|uefi                   # firmware type
```

```
hw_firmware_stateless=true|false            # stateless firmware
```

```
hw_boot_menu=true|false                     # show BIOS boot menu
```

```
hw_ipxe_boot=true|false                     # use iPXE for network boot
```

```
hw_machine_type=<type>                       # QEMU machine type
                                              # free-form string (e.g., pc-i440fx-2.1)
```

### Security Features

```
hw_tpm_model=tpm-tis|tpm-crb                # TPM device model
```

```
hw_tpm_version=1.2|2.0                      # TPM version
```

```
os_secure_boot=disabled|required|optional   # secure boot requirement
```

### Watchdog

```
hw_watchdog_action=none|pause|poweroff|reset|disabled
                                              # watchdog action
```

### Performance Features

```
hw_pmu=true|false                           # enable Performance Monitoring Unit
```

```
hw_virtio_packed_ring=true|false            # enable virtio packed ring format
```

```
hw_time_hpet=true|false                     # enable HPET timer
```

### Memory Address Configuration

```
hw_maxphysaddr_mode=<mode>                  # physical address mode
```

```
hw_maxphysaddr_bits=<N>                     # physical address bits
```

### Ephemeral Storage Encryption

```
hw_ephemeral_encryption=true|false          # enable ephemeral encryption
```

```
hw_ephemeral_encryption_format=<format>     # encryption format
                                              # e.g., luks, plain
```

```
hw_ephemeral_encryption_secret_uuid=<uuid>   # encryption secret UUID
```

### Rescue Configuration

```
hw_rescue_bus=virtio|scsi|ide|usb|lxc|uml   # rescue disk bus
```

```
hw_rescue_device=disk|cdrom|floppy|lun      # rescue device type
```

### Image Handling (`img_` prefix)

```
img_hv_type=kvm|qemu|xen|vmware|ironic|lxd  # hypervisor type
```

```
img_hv_requested_version=<predicate>         # hypervisor version requirement
                                              # e.g., >=2.6
```

```
img_hide_hypervisor_id=true|false           # hide hypervisor ID from guest
```

```
img_config_drive=optional|mandatory|forbidden
                                              # config drive policy
```

```
img_cache_in_nova=true|false                # cache image on host
```

```
img_compression_level=<1-9>                 # image compression level
```

```
img_bittorrent=true|false                   # download via BitTorrent
```

```
img_linked_clone=true|false                 # use linked clone (VMware)
```

```
img_use_agent=true|false                    # use nova agent
```

```
img_version=<N>                             # image version (typically 1)
```

```
img_owner_id=<uuid>                          # image owner project ID
```

```
img_root_device_name=<device>                # root device name
                                              # e.g., /dev/vda
```

```
img_mappings=<mappings>                      # image device mappings (dict/list)
```

```
img_block_device_mapping=<bdm>               # block device mapping (dict/list)
```

```
img_bdm_v2=true|false                       # BDM format version
```

### Operating System (`os_` prefix)

```
os_type=linux|windows|solaris|netbsd|openbsd|freebsd
                                              # OS family
```

```
os_distro=<distro>                          # OS distribution name
                                              # free-form (e.g., ubuntu, centos, windows)
```

```
os_admin_user=<username>                     # admin username
```

```
os_command_line=<args>                       # kernel command line arguments
```

```
os_require_quiesce=true|false               # require disk quiesce for snapshots
```

```
os_skip_agent_inject_files_at_boot=true|false
                                              # skip file injection (cloud-init)
```

```
os_skip_agent_inject_ssh=true|false         # skip SSH key injection (cloud-init)
```

### Traits

```
traits_required=<list>                       # list of required traits
                                              # e.g., ["HW_CPU_X86_AVX2"]
```

**Trait format in image properties:**
- Properties like `trait:HW_CPU_X86_AVX2=required` are parsed into `traits_required` list
- Trait name extracted (e.g., `HW_CPU_X86_AVX2`)

### Image Signature Verification

```
img_signature=<base64>                       # base64-encoded image signature
```

```
img_signature_hash_method=<method>           # signature hash method
```

```
img_signature_certificate_uuid=<uuid>        # certificate UUID
```

```
img_signature_key_type=<type>                # signature key type
```

### Legacy Property Names

The following legacy property names are automatically mapped to current names:

- `architecture` → `hw_architecture`
- `owner_id` → `img_owner_id`
- `vmware_disktype` → `hw_disk_type`
- `vmware_image_version` → `img_version`
- `vmware_ostype` → `os_distro`
- `auto_disk_config` → `hw_auto_disk_config`
- `ipxe_boot` → `hw_ipxe_boot`
- `xenapi_device_id` → `hw_device_id`
- `xenapi_image_compression_level` → `img_compression_level`
- `vmware_linked_clone` → `img_linked_clone`
- `xenapi_use_agent` → `img_use_agent`
- `xenapi_skip_agent_inject_ssh` → `os_skip_agent_inject_ssh`
- `xenapi_skip_agent_inject_files_at_boot` → `os_skip_agent_inject_files_at_boot`
- `cache_in_nova` → `img_cache_in_nova`
- `vm_mode` → `hw_vm_mode`
- `bittorrent` → `img_bittorrent`
- `mappings` → `img_mappings`
- `block_device_mapping` → `img_block_device_mapping`
- `bdm_v2` → `img_bdm_v2`
- `root_device_name` → `img_root_device_name`
- `hypervisor_version_requires` → `img_hv_requested_version`
- `hypervisor_type` → `img_hv_type`
- `vmware_adaptertype` → `hw_disk_bus` (ide → ide, others → scsi with `hw_scsi_model`)

### ComputeNode

**Entity Type:** Core scheduling entity  
**Database Table:** `compute_nodes`  
**Key Fields:** `host`, `vcpus`, `memory_mb`, `hypervisor_type`, `numa_topology`

Represents compute capacity on a hypervisor.

```
ComputeNode:
  id:                     int
  uuid:                   UUID
  service_id:             int|null      # FK to Service
  host:                   string        # hostname
  hypervisor_hostname:    string        # libvirt node name
  
  # Capacity (total)
  vcpus:                  int           # total vCPUs
  memory_mb:              int           # total RAM
  local_gb:               int           # total local disk
  
  # Usage (used)
  vcpus_used:             int
  memory_mb_used:         int
  local_gb_used:          int
  
  # Availability (computed)
  free_ram_mb:            int|null
  free_disk_gb:           int|null
  disk_available_least:   int|null      # smallest available disk
  
  # Hypervisor
  hypervisor_type:        string        # QEMU, KVM, VMware, etc.
  hypervisor_version:     int           # version as integer
  host_ip:                IP            # management IP
  
  # CPU architecture & topology
  cpu_info:               JSON          # CPU model, topology, features
  supported_hv_specs:     list[HVSpec]  # supported (arch, hv_type, vm_mode)
  
  # NUMA topology
  numa_topology:          JSON|null     # NUMATopology object serialized
  
  # PCI devices
  pci_device_pools:       PciDevicePoolList|null
  
  # Allocation ratios
  cpu_allocation_ratio:   float         # overcommit ratio for CPU
  ram_allocation_ratio:   float         # overcommit ratio for RAM
  disk_allocation_ratio:  float         # overcommit ratio for disk
  
  # Workload tracking
  running_vms:            int|null      # instance count
  current_workload:       int|null      # active operations count
  
  # Statistics
  stats:                  dict          # arbitrary stats (JSON)
  metrics:                JSON|null     # custom metrics
  extra_resources:        JSON|null     # additional resources
  
  # Placement sync
  mapped:                 int           # synced to Placement (0/1)
  
  created_at:             datetime
  updated_at:             datetime
  deleted_at:             datetime|null
  deleted:                int
```

**cpu_info structure:**
```json
{
  "arch": "x86_64",
  "model": "IvyBridge",
  "vendor": "Intel",
  "topology": {
    "sockets": 2,
    "cores": 8,
    "threads": 2
  },
  "features": ["avx", "avx2", "sse4_2", ...]
}
```

### Migration

Tracks instance moves (live migration, resize, evacuate).

```
Migration:
  id:                     int
  uuid:                   UUID
  instance_uuid:          UUID          # FK to Instance
  
  # Source
  source_compute:         string|null   # source hostname
  source_node:            string|null   # source node name
  
  # Destination
  dest_compute:           string|null   # dest hostname
  dest_node:              string|null   # dest node name
  dest_compute_id:        int|null      # FK to ComputeNode
  dest_host:              string|null   # dest IP
  
  # Flavor change (for resize)
  old_instance_type_id:   int|null      # old flavor ID
  new_instance_type_id:   int|null      # new flavor ID
  
  # Status
  status:                 string        # pre-migrating, migrating, done, error, etc.
  migration_type:         enum          # 'migration', 'resize', 'live-migration', 'evacuation'
  hidden:                 bool          # hide from API
  cross_cell_move:        bool          # cross-cell migration
  
  # Progress tracking
  memory_total:           int|null      # total memory to transfer (MB)
  memory_processed:       int|null      # memory transferred
  memory_remaining:       int|null
  disk_total:             int|null      # total disk to transfer (GB)
  disk_processed:         int|null
  disk_remaining:         int|null
  
  # Audit
  user_id:                string|null   # initiating user
  project_id:             string|null   # initiating project
  
  created_at:             datetime
  updated_at:             datetime
  deleted_at:             datetime|null
  deleted:                int
```

**Migration Types:**
- `migration`: Cold migration (shut down and move)
- `resize`: Change flavor (requires confirm)
- `live-migration`: Live migration (minimal downtime)
- `evacuation`: Rebuild on new host after failure

**Migration Statuses:**
- `queued`, `preparing`, `running`, `post-migrating`
- `completed`, `confirmed`, `reverted`, `error`

### BlockDeviceMapping (BDM)

Storage device attachments for instances.

```
BlockDeviceMapping:
  id:                       int
  uuid:                     UUID
  instance_uuid:            UUID         # FK to Instance
  
  # Source
  source_type:              enum         # image, volume, snapshot, blank
  image_id:                 UUID|null    # Glance image
  snapshot_id:              UUID|null    # Cinder snapshot
  volume_id:                UUID|null    # Cinder volume
  
  # Destination
  destination_type:         enum         # local, volume
  guest_format:             string|null  # fs format (ext4, swap, etc.)
  
  # Device properties
  device_type:              enum         # disk, cdrom, floppy, lun
  disk_bus:                 string|null  # virtio, scsi, ide, usb, etc.
  device_name:              string|null  # /dev/vdb, etc.
  boot_index:               int|null     # boot order (-1 = no boot)
  
  # Size and behavior
  volume_size:              int|null     # size in GB
  volume_type:              string|null  # Cinder volume type
  delete_on_termination:    bool
  no_device:                bool         # device explicitly removed
  
  # Volume attachment
  attachment_id:            UUID|null    # Cinder attachment UUID
  connection_info:          JSON|null    # iSCSI/RBD connection details
  
  # Encryption
  encrypted:                bool
  encryption_secret_uuid:   UUID|null    # Barbican secret
  encryption_format:        enum|null    # luks, plain
  encryption_options:       string|null  # JSON options
  
  # Metadata
  tag:                      string|null  # device tag
  
  created_at:               datetime
  updated_at:               datetime
  deleted_at:               datetime|null
  deleted:                  int
```

## NUMA and CPU Topology

### InstanceNUMATopology

NUMA topology for an instance (stored in instance_extra).

```
InstanceNUMATopology:
  cells:                    list[InstanceNUMACell]
  emulator_threads_policy:  enum|null     # share, isolate
  
InstanceNUMACell:
  id:                       int           # NUMA cell ID
  cpuset:                   set[int]      # vCPU IDs
  pcpuset:                  set[int]      # pCPUs pinned (if dedicated)
  memory:                   int           # memory in MB
  pagesize:                 int|null      # huge page size (KB)
  cpu_policy:               enum|null     # dedicated, shared, mixed
  cpu_thread_policy:        enum|null     # require, prefer, isolate
  cpu_pinning:              dict          # {vcpu: pcpu} mapping
```

### NUMATopology (ComputeNode)

Physical NUMA topology of compute host.

```
NUMATopology:
  cells:                    list[NUMACell]
  
NUMACell:
  id:                       int           # NUMA cell ID
  cpuset:                   set[int]      # CPU IDs in this cell
  pcpuset:                  set[int]      # CPUs for pinned
  memory:                   int           # total memory (MB)
  memory_usage:             int           # used memory
  pinned_cpus:              set[int]      # currently pinned CPUs
  siblings:                 list[set]     # CPU thread siblings
  mempages:                 list[dict]    # huge pages config
```

## PCI Devices

### PciDevice

Physical PCI device assigned to instance.

```
PciDevice:
  id:                       int
  uuid:                     UUID
  compute_node_id:          int           # FK to ComputeNode
  address:                  string        # PCI address (0000:04:00.1)
  
  # Hardware identification
  vendor_id:                string        # PCI vendor ID (8086)
  product_id:               string        # PCI product ID (10ed)
  dev_type:                 enum          # type-PCI, type-PF, type-VF
  dev_id:                   string        # device identifier
  
  # Allocation
  instance_uuid:            UUID|null     # assigned instance
  request_id:               UUID|null     # request that claimed it
  status:                   enum          # available, claimed, allocated
  
  # PCI specifications
  label:                    string        # alias label
  numa_node:                int|null      # NUMA affinity
  parent_addr:              string|null   # parent PF address (for VF)
  
  # Extra metadata (JSON)
  extra_info:               JSON          # {physical_network, capabilities, ...}
  
  created_at:               datetime
  updated_at:               datetime
  deleted_at:               datetime|null
  deleted:                  int
```

**Device Types:**
- `type-PCI`: Standard PCI device
- `type-PF`: SR-IOV Physical Function
- `type-VF`: SR-IOV Virtual Function

**Statuses:**
- `available`: Unallocated
- `claimed`: Reserved during scheduling
- `allocated`: Assigned to instance
- `unavailable`: Temporarily unavailable

### PciDevicePool

Aggregated view of similar PCI devices.

```
PciDevicePool:
  product_id:               string
  vendor_id:                string
  numa_node:                int|null
  tags:                     dict          # traits and metadata
  count:                    int           # available devices
```

## Server Groups

### InstanceGroup (ServerGroup)

Affinity/anti-affinity policies for instances.

```
InstanceGroup:
  id:                       int
  uuid:                     UUID
  user_id:                  string
  project_id:               string
  name:                     string
  
  # Policy
  policies:                 list[string]  # affinity, anti-affinity, soft-*
  rules:                    dict          # {max_server_per_host: N}
  
  # Members
  members:                  list[UUID]    # instance UUIDs
  hosts:                    list[string]  # scheduled hosts
  
  created_at:               datetime
  updated_at:               datetime
  deleted_at:               datetime|null
  deleted:                  int
```

**Policies:**
- `affinity`: Schedule all instances to same host
- `anti-affinity`: Schedule instances to different hosts
- `soft-affinity`: Prefer same host (best effort)
- `soft-anti-affinity`: Prefer different hosts (best effort)

**Rules:**
```json
{
  "max_server_per_host": 3  // max instances per host (anti-affinity)
}
```

## Service Management

### Service

Represents a Nova service process.

```
Service:
  id:                       int
  uuid:                     UUID
  host:                     string        # hostname
  binary:                   string        # nova-compute, nova-scheduler, etc.
  topic:                    string        # RPC topic
  
  # Health
  disabled:                 bool          # administratively disabled
  disabled_reason:          string|null
  forced_down:              bool          # forced down by admin
  last_seen_up:             datetime|null
  report_count:             int           # periodic update counter
  
  # Version
  version:                  int           # service version
  
  created_at:               datetime
  updated_at:               datetime
  deleted_at:               datetime|null
  deleted:                  int
```

## Request Context

### RequestSpec

Encapsulates scheduling request (not persisted, passed via RPC).

```
RequestSpec:
  instance_uuid:            UUID
  instance_type:            Flavor
  image:                    dict          # image properties
  numa_topology:            InstanceNUMATopology|null
  pci_requests:             InstancePCIRequests|null
  
  # Placement query
  requested_resources:      list[ResourceRequest]
  requested_destination:    Destination|null
  
  # Hints
  scheduler_hints:          dict          # user scheduler hints
  availability_zone:        string|null
  force_hosts:              list[string]|null
  force_nodes:              list[string]|null
  
  # Policies
  retry:                    dict          # retry history
  limits:                   dict          # resource limits
  security_groups:          list
  project_id:               string
  user_id:                  string
```

## Key Relationships

```
Instance relationships:
  - 1:1 → Flavor (current, old, new)
  - 1:1 → InstanceInfoCache (network info)
  - 1:N → BlockDeviceMapping (storage)
  - 1:N → PciDevice (assigned devices)
  - 1:1 → InstanceNUMATopology (in instance_extra)
  - 1:1 → InstancePCIRequests (in instance_extra)
  - M:N → SecurityGroup
  - M:1 → InstanceGroup (server group membership)
  - 1:N → Migration (history of moves)
  - 1:N → Tag

ComputeNode relationships:
  - 1:1 → Service
  - 1:N → Instance (via host match)
  - 1:N → PciDevice
  - 1:1 → NUMATopology (embedded JSON)

Flavor relationships:
  - 1:N → FlavorExtraSpecs (key-value pairs)
  - M:N → Project (flavor access, if not public)
```

---

## State Machine

**Section ID:** `state-machines`

State transitions for instances and migrations.

**Instance VM States:**
```
NULL → BUILDING → ACTIVE ⇄ PAUSED
         ↓           ↓
       ERROR    STOPPED → ACTIVE
                   ↓
              SUSPENDED → ACTIVE
                   ↓
                DELETED
```

**Migration Flow:**
```
NULL → queued → preparing → running → post-migrating
                    ↓           ↓
                  error    completed → confirmed/reverted
```

---

## Database Tables (Key)

**Section ID:** `database-tables`

Key database tables and their relationships.

```sql
-- Core tables
instances (id, uuid, user_id, project_id, host, node, vm_state, ...)
compute_nodes (id, uuid, host, vcpus, memory_mb, hypervisor_type, ...)
services (id, uuid, host, binary, topic, disabled, ...)
migrations (id, uuid, instance_uuid, source_compute, dest_compute, ...)

-- Flavor
instance_types (id, flavorid, name, memory_mb, vcpus, root_gb, ...)  [API DB]
instance_type_extra_specs (instance_type_id, key, value)              [API DB]
instance_type_projects (instance_type_id, project_id)                 [API DB]

-- Extended instance data
instance_extra (instance_uuid, numa_topology, pci_requests, flavor, ...)
instance_metadata (instance_uuid, key, value)
instance_system_metadata (instance_uuid, key, value)
instance_info_caches (instance_uuid, network_info)

-- Storage
block_device_mapping (id, instance_uuid, volume_id, device_name, ...)

-- PCI
pci_devices (id, compute_node_id, address, instance_uuid, ...)

-- Server groups
instance_groups (id, uuid, name, user_id, project_id, policies, ...)    [API DB]
instance_group_member (instance_group_id, instance_uuid)                [API DB]
instance_group_policy (instance_group_id, policy, rules)                [API DB]

-- Networking (legacy nova-network, mostly unused)
security_groups (id, name, project_id, ...)
security_group_instance_association (instance_uuid, security_group_id)

-- Tagging
tags (resource_id, tag)
```

---

## Configuration Impact on Scheduling

**Section ID:** `config-impact`

**Key Config Options:**

| Config Option | Purpose | Impact |
|---------------|---------|--------|
| `cpu_allocation_ratio` | CPU overcommit ratio | Multiplies available vCPUs |
| `ram_allocation_ratio` | RAM overcommit ratio | Multiplies available RAM |
| `disk_allocation_ratio` | Disk overcommit ratio | Multiplies available disk |
| `reserved_host_cpus` | Reserved CPUs | Reduces available CPUs |
| `reserved_host_memory_mb` | Reserved RAM | Reduces available RAM |
| `reserved_host_disk_mb` | Reserved disk | Reduces available disk |
| `cpu_dedicated_set` | Dedicated CPU set | NUMA CPU partitioning |
| `cpu_shared_set` | Shared CPU set | NUMA CPU partitioning |
| `pci_passthrough_whitelist` | PCI device whitelist | PCI device configuration |
| `pci_alias` | PCI device aliases | PCI device configuration |
| `enabled_filters` | Scheduler filters | Filtering behavior |
| `enabled_weighers` | Scheduler weighers | Weighing behavior |
| `weight_multiplier` | Per-weigher multiplier | Weighing impact |
| `max_server_per_host_filter_weight_multiplier` | Anti-affinity weight | Anti-affinity behavior |

---

## Quick Lookup Index

**Extra Specs by Category:**
- CPU: `hw:cpu_policy`, `hw:cpu_thread_policy`, `hw:cpu_sockets`, `hw:cpu_cores`, `hw:cpu_threads`
- NUMA: `hw:numa_nodes`, `hw:numa_cpus.<N>`, `hw:numa_mem.<N>`, `hw:pci_numa_affinity_policy`
- Memory: `hw:mem_page_size`, `hw:mem_encryption`, `hw:locked_memory`
- Resources: `resources:VCPU`, `resources:MEMORY_MB`, `resources:DISK_GB`, `resources:CUSTOM_*`
- Traits: `trait:HW_CPU_X86_AVX2`, `trait:CUSTOM_*`
- PCI: `pci_passthrough:alias`
- Quotas: `quota:cpu_shares`, `quota:disk_*`, `quota:vif_*`

**Image Properties by Category:**
- CPU: `hw_cpu_*`, `hw_cpu_policy`, `hw_cpu_thread_policy`
- NUMA: `hw_numa_*`, `hw_pci_numa_affinity_policy`
- Memory: `hw_mem_*`, `hw_locked_memory`
- Devices: `hw_disk_bus`, `hw_cdrom_bus`, `hw_vif_model`, `hw_video_model`
- Firmware: `hw_firmware_type`, `hw_firmware_stateless`
- OS: `os_type`, `os_distro`, `os_secure_boot`
- Image: `img_hv_type`, `img_config_drive`, `img_cache_in_nova`

