# OpenStack Placement Data Model Reference

This document describes the complete data model exposed by the OpenStack
Placement API, optimized for LLM consumption and Tachyon implementation.

## Core Entities

### ResourceProvider

The fundamental entity representing a source of resources.

```
ResourceProvider:
  id:                    int        # internal DB ID
  uuid:                  UUID       # external identifier
  name:                  string     # human-readable name (unique, max 200 chars)
  generation:            int        # optimistic concurrency version (auto-incremented)
  root_provider_id:      int        # FK to root of tree (self if root)
  parent_provider_id:    int|null   # FK to parent (null if root)
  root_provider_uuid:    UUID       # computed: root's UUID
  parent_provider_uuid:  UUID|null  # computed: parent's UUID
  created_at:            timestamp
  updated_at:            timestamp
```

**Hierarchy Rules:**
- Forms trees with parent-child relationships
- `root_provider_id == id` when provider is a tree root
- `parent_provider_id == null` when provider is a tree root
- Child inherits root from parent on creation
- Cannot delete provider with children
- Cannot create cycles in tree

### Inventory

Quantitative resources available on a resource provider.

```
Inventory:
  id:                    int
  resource_provider_id:  int        # FK to ResourceProvider
  resource_class_id:     int        # FK to ResourceClass
  total:                 int        # total amount of resource
  reserved:              int        # amount reserved for other uses
  min_unit:              int        # minimum allocation unit
  max_unit:              int        # maximum allocation unit
  step_size:             int        # allocation granularity
  allocation_ratio:      float      # overcommit ratio
  created_at:            timestamp
  updated_at:            timestamp

Computed:
  capacity = (total - reserved) * allocation_ratio
```

**Constraints:**
- One inventory per (resource_provider, resource_class) pair
- Cannot delete inventory with active allocations
- Modifying inventory increments provider's generation

### Allocation

Records resource consumption by a consumer.

```
Allocation:
  id:                    int
  resource_provider_id:  int        # FK to ResourceProvider
  consumer_id:           UUID       # FK to Consumer.uuid
  resource_class_id:     int        # FK to ResourceClass
  used:                  int        # amount consumed
  created_at:            timestamp
  updated_at:            timestamp
```

**Constraints:**
- Allocation must satisfy: `min_unit <= used <= max_unit`
- Allocation must satisfy: `used % step_size == 0`
- Sum of allocations must not exceed capacity
- All allocations for a consumer replaced atomically

### Consumer

Entity that consumes resources (e.g., VM instance, volume).

```
Consumer:
  id:                    int
  uuid:                  UUID       # external identifier (often matches Nova instance UUID)
  project_id:            int        # FK to Project
  user_id:               int        # FK to User
  consumer_type_id:      int|null   # FK to ConsumerType
  generation:            int        # optimistic concurrency version
  created_at:            timestamp
  updated_at:            timestamp
```

**Rules:**
- Created automatically when allocations are made
- Deleted automatically when all allocations removed
- Generation incremented on allocation changes

### ResourceClass

Type of quantitative resource (e.g., VCPU, MEMORY_MB).

```
ResourceClass:
  id:                    int        # 0-9999 for standard, 10000+ for custom
  name:                  string     # e.g., "VCPU", "CUSTOM_FPGA"
  created_at:            timestamp
  updated_at:            timestamp
```

**Naming Rules:**
- Standard classes: synced from os-resource-classes library (VCPU, MEMORY_MB, DISK_GB, VGPU, etc.)
- Custom classes: must start with "CUSTOM_" prefix
- Standard classes cannot be modified or deleted
- Custom classes: IDs >= 10000

### Trait

Qualitative characteristic of a resource provider.

```
Trait:
  id:                    int
  name:                  string     # e.g., "HW_CPU_X86_AVX2", "CUSTOM_RAID"
  created_at:            timestamp
  updated_at:            timestamp
```

**Naming Rules:**
- Standard traits: synced from os-traits library
- Custom traits: must start with "CUSTOM_" prefix
- Standard traits cannot be deleted
- Traits are associated with providers, not specific resources

### PlacementAggregate

Grouping mechanism for resource providers.

```
PlacementAggregate:
  id:                    int
  uuid:                  UUID       # external identifier (often matches Nova host aggregate)
```

**Purpose:**
- Logical grouping (availability zones, host aggregates)
- Enables shared resources via `MISC_SHARES_VIA_AGGREGATE` trait
- Filters via `member_of` query parameter

### Project

Keystone project reference.

```
Project:
  id:                    int
  external_id:           string     # Keystone project UUID
  created_at:            timestamp
  updated_at:            timestamp
```

### User

Keystone user reference.

```
User:
  id:                    int
  external_id:           string     # Keystone user UUID
  created_at:            timestamp
  updated_at:            timestamp
```

### ConsumerType

Categorization for consumers.

```
ConsumerType:
  id:                    int
  name:                  string     # e.g., "INSTANCE", "MIGRATION"
  created_at:            timestamp
  updated_at:            timestamp
```

## Association Tables

### ResourceProviderAggregate

Many-to-many relationship between providers and aggregates.

```
ResourceProviderAggregate:
  resource_provider_id:  int        # PK, FK to ResourceProvider
  aggregate_id:          int        # PK, FK to PlacementAggregate
```

### ResourceProviderTrait

Many-to-many relationship between providers and traits.

```
ResourceProviderTrait:
  resource_provider_id:  int        # PK, FK to ResourceProvider
  trait_id:              int        # PK, FK to Trait
```

## API Query Concepts

### Allocation Candidates Query

Complex query to find providers satisfying resource requests.

```
GET /allocation_candidates parameters:
  resources[{suffix}]:     string   # "RC1:N,RC2:M" resource requirements
  required[{suffix}]:      string   # "TRAIT1,!TRAIT2,in:TRAIT3,TRAIT4" trait constraints
  member_of[{suffix}]:     string   # "in:AGG1,AGG2" aggregate membership
  in_tree[{suffix}]:       UUID     # limit to specific provider tree
  limit:                   int      # max candidates to return
  group_policy:            string   # "isolate" | "none"
  root_required:           string   # traits required on root provider
  same_subtree:            string   # groups that must share subtree
```

**Suffix Rules:**
- Empty suffix `""`: unnumbered group
- Numbered suffix `"1"`, `"2"`: granular request groups
- Arbitrary string suffix (microversion 1.33+)

**Trait Expression Syntax:**
- `TRAIT`: required trait
- `!TRAIT`: forbidden trait
- `in:T1,T2`: any of (OR)

**Group Policy:**
- `none`: resources from groups can overlap on same provider
- `isolate`: each numbered group must use different providers

### Request Response Objects

```
AllocationRequest:
  allocations:           dict       # {rp_uuid: {resources: {rc: amount}}}
  mappings:              dict       # {suffix: [rp_uuid, ...]}

ProviderSummary:
  resource_provider:
    uuid:                UUID
    name:                string
    generation:          int
    root_provider_uuid:  UUID
    parent_provider_uuid: UUID|null
  resources:             list       # [{resource_class, capacity, used}]
  traits:                list       # [trait_name, ...]
```

### Usage Query

Computed resource consumption.

```
Usage:
  resource_class:        string     # resource class name
  usage:                 int        # sum of allocations
  consumer_type:         string     # optional: filter by consumer type
  consumer_count:        int        # count of unique consumers
```

## Generation (Optimistic Concurrency)

Both ResourceProvider and Consumer have `generation` fields:

- **Read**: Get current generation
- **Write**: Include generation in request, increment on success
- **Conflict**: If generation changed, raise `ConcurrentUpdateDetected`

Operations that increment generation:
- ResourceProvider: set_inventory, set_traits, set_aggregates
- Consumer: allocations replaced

## Sharing Providers

Special providers that share resources across trees:

1. Mark with trait `MISC_SHARES_VIA_AGGREGATE`
2. Associate with aggregate(s)
3. Other providers in same aggregate can consume shared resources

**Example:** A shared storage pool provider "NFS_SHARE" with 2000 DISK_GB inventory, marked with `MISC_SHARES_VIA_AGGREGATE` and associated with aggregate "AGG_A". Compute node providers "CN_1" through "CN_10" also associated with "AGG_A" can consume DISK_GB from "NFS_SHARE" even though they have no DISK_GB inventory themselves.

## Key API Endpoints

```
Resource Providers:
  GET    /resource_providers                    # list/filter
  POST   /resource_providers                    # create
  GET    /resource_providers/{uuid}             # get one
  PUT    /resource_providers/{uuid}             # update
  DELETE /resource_providers/{uuid}             # delete

Inventories:
  GET    /resource_providers/{uuid}/inventories
  PUT    /resource_providers/{uuid}/inventories # replace all
  POST   /resource_providers/{uuid}/inventories/{rc}
  PUT    /resource_providers/{uuid}/inventories/{rc}
  DELETE /resource_providers/{uuid}/inventories/{rc}

Traits:
  GET    /traits                                # list all
  PUT    /traits/{name}                         # create custom
  GET    /traits/{name}                         # check exists
  DELETE /traits/{name}                         # delete custom
  GET    /resource_providers/{uuid}/traits
  PUT    /resource_providers/{uuid}/traits      # replace all

Aggregates:
  GET    /resource_providers/{uuid}/aggregates
  PUT    /resource_providers/{uuid}/aggregates  # replace all

Allocations:
  GET    /allocations/{consumer_uuid}
  PUT    /allocations/{consumer_uuid}           # replace
  DELETE /allocations/{consumer_uuid}
  POST   /allocations                           # bulk update (reshaper)

Usages:
  GET    /resource_providers/{uuid}/usages
  GET    /usages?project_id=X                   # project usages

Resource Classes:
  GET    /resource_classes
  POST   /resource_classes                      # create custom
  GET    /resource_classes/{name}
  PUT    /resource_classes/{name}               # update custom
  DELETE /resource_classes/{name}               # delete custom

Allocation Candidates:
  GET    /allocation_candidates?resources=...   # query candidates
```

## Database Schema Summary

```sql
-- Core tables
resource_providers (id, uuid, name, generation, root_provider_id, parent_provider_id)
inventories (id, resource_provider_id, resource_class_id, total, reserved, ...)
allocations (id, resource_provider_id, consumer_id, resource_class_id, used)
consumers (id, uuid, project_id, user_id, generation, consumer_type_id)
resource_classes (id, name)
traits (id, name)

-- Reference tables
projects (id, external_id)
users (id, external_id)
consumer_types (id, name)

-- Association tables
placement_aggregates (id, uuid)
resource_provider_aggregates (resource_provider_id, aggregate_id)
resource_provider_traits (resource_provider_id, trait_id)

-- Key indexes
resource_providers: uuid (unique), name (unique), root_provider_id, parent_provider_id
inventories: (resource_provider_id, resource_class_id) unique
allocations: consumer_id, (resource_provider_id, resource_class_id, used)
```

## Standard Resource Classes

Complete list of standard resource classes from os-resource-classes library.
All standard resource classes are immutable and cannot be modified or deleted.

### Compute Resources
- `VCPU` - Virtual CPU count (most common)
- `PCPU` - Physical/dedicated CPU count (dedicated physical processor for single guest)
- `MEMORY_MB` - Memory in megabytes
- `MEM_ENCRYPTION_CONTEXT` - Number of guests a compute node can host with hardware-level memory encryption (AMD SEV)

### Storage Resources
- `DISK_GB` - Disk storage in gigabytes

### Network Resources
- `SRIOV_NET_VF` - SR-IOV virtual function
- `NET_BW_EGR_KILOBIT_PER_SEC` - Network bandwidth egress in kilobits per second
- `NET_BW_IGR_KILOBIT_PER_SEC` - Network bandwidth ingress in kilobits per second
- `NET_PACKET_RATE_KILOPACKET_PER_SEC` - Network packet rate (directionless) in kilopackets per second
- `NET_PACKET_RATE_EGR_KILOPACKET_PER_SEC` - Network packet rate egress in kilopackets per second
- `NET_PACKET_RATE_IGR_KILOPACKET_PER_SEC` - Network packet rate ingress in kilopackets per second
- `IPV4_ADDRESS` - IPv4 address

### GPU Resources
- `VGPU` - Virtual GPU count
- `VGPU_DISPLAY_HEAD` - Virtual GPU display head
- `PGPU` - Physical GPU for compute offload

### NUMA Resources
- `NUMA_SOCKET` - NUMA socket
- `NUMA_CORE` - NUMA core
- `NUMA_THREAD` - NUMA thread
- `NUMA_MEMORY_MB` - NUMA memory in megabytes

### Accelerator Resources
- `FPGA` - FPGA accelerator (VF that can be attached to guest)
- `PCI_DEVICE` - PCI device

### Custom Resource Classes
- `CUSTOM_*` - User-defined resource classes (must start with "CUSTOM_" prefix, IDs >= 10000)

## Standard Traits

Complete list of standard traits from os-traits library, organized by namespace.
All standard traits are immutable and cannot be deleted. Traits are associated with
resource providers, not specific resources.

### COMPUTE_* Traits (Compute Capabilities)

#### Architecture
- `COMPUTE_ARCH_AARCH64` - ARM 64-bit architecture
- `COMPUTE_ARCH_PPC64LE` - PowerPC 64-bit little-endian
- `COMPUTE_ARCH_MIPSEL` - MIPS little-endian
- `COMPUTE_ARCH_S390X` - IBM System z
- `COMPUTE_ARCH_RISCV64` - RISC-V 64-bit
- `COMPUTE_ARCH_X86_64` - x86-64 architecture

#### General Compute Features
- `COMPUTE_DEVICE_TAGGING` - Virt driver supports associating tag with device at boot time
- `COMPUTE_NODE` - Provider is a compute node (distinct from compute host/hypervisor)
- `COMPUTE_TRUSTED_CERTS` - Virt driver supports trusted image certificate validation
- `COMPUTE_SAME_HOST_COLD_MIGRATE` - Supports cold migrating to same compute service host
- `COMPUTE_RESCUE_BFV` - Supports rescuing boot from volume instances
- `COMPUTE_ACCELERATORS` - Compute manager supports handling accelerator requests
- `COMPUTE_SOCKET_PCI_NUMA_AFFINITY` - Supports socket value for hw_pci_numa_affinity_policy
- `COMPUTE_REMOTE_MANAGED_PORTS` - Supports remote_managed PCI devices (SmartNIC DPUs)
- `COMPUTE_MEM_BACKING_FILE` - Configured to support file-backed memory
- `COMPUTE_MANAGED_PCI_DEVICE` - RP has inventories of PCI device(s) managed by nova-compute
- `COMPUTE_ADDRESS_SPACE_PASSTHROUGH` - Supports pass-through mode for guest physical address bits
- `COMPUTE_ADDRESS_SPACE_EMULATED` - Supports emulated mode for guest physical address bits
- `COMPUTE_SHARE_LOCAL_FS` - Supports sharing local filesystem via virtiofs

#### Config Drive
- `COMPUTE_CONFIG_DRIVE_REGENERATION` - Config drive regeneration support

#### Ephemeral Storage Encryption
- `COMPUTE_EPHEMERAL_ENCRYPTION` - Ephemeral storage encryption support
- `COMPUTE_EPHEMERAL_ENCRYPTION_PLAIN` - Plain ephemeral encryption
- `COMPUTE_EPHEMERAL_ENCRYPTION_LUKS` - LUKS ephemeral encryption
- `COMPUTE_EPHEMERAL_ENCRYPTION_LUKSV2` - LUKS v2 ephemeral encryption

#### Firmware
- `COMPUTE_FIRMWARE_BIOS` - Supports BIOS instances
- `COMPUTE_FIRMWARE_UEFI` - Supports UEFI instances

#### Graphics/Video Models
- `COMPUTE_GRAPHICS_MODEL_BOCHS` - Bochs video model
- `COMPUTE_GRAPHICS_MODEL_CIRRUS` - Cirrus video model
- `COMPUTE_GRAPHICS_MODEL_GOP` - GOP video model
- `COMPUTE_GRAPHICS_MODEL_NONE` - No video model
- `COMPUTE_GRAPHICS_MODEL_QXL` - QXL video model
- `COMPUTE_GRAPHICS_MODEL_VGA` - VGA video model
- `COMPUTE_GRAPHICS_MODEL_VIRTIO` - Virtio video model
- `COMPUTE_GRAPHICS_MODEL_VMVGA` - VMware VGA video model
- `COMPUTE_GRAPHICS_MODEL_XEN` - Xen video model

#### Image Formats
- `COMPUTE_IMAGE_TYPE_AKI` - Amazon kernel image
- `COMPUTE_IMAGE_TYPE_AMI` - Amazon machine image
- `COMPUTE_IMAGE_TYPE_ARI` - Amazon ramdisk image
- `COMPUTE_IMAGE_TYPE_ISO` - ISO optical media
- `COMPUTE_IMAGE_TYPE_QCOW2` - QEMU native format
- `COMPUTE_IMAGE_TYPE_RAW` - Raw byte-for-byte disk image
- `COMPUTE_IMAGE_TYPE_VDI` - VirtualBox native format
- `COMPUTE_IMAGE_TYPE_VHD` - VHD disk format
- `COMPUTE_IMAGE_TYPE_VHDX` - VHDX disk format
- `COMPUTE_IMAGE_TYPE_VMDK` - VMware native format
- `COMPUTE_IMAGE_TYPE_PLOOP` - Virtuozzo native format

#### Migration
- `COMPUTE_MIGRATE_AUTO_CONVERGE` - Auto-converge migration support
- `COMPUTE_MIGRATE_POST_COPY` - Post-copy migration support

#### Network/VIF Models
- `COMPUTE_NET_ATTACH_INTERFACE` - Supports attaching network interface after boot
- `COMPUTE_NET_ATTACH_INTERFACE_WITH_TAG` - Supports attaching network interface with device tag
- `COMPUTE_NET_VIRTIO_PACKED` - Supports Packed virtqueue format
- `COMPUTE_NET_VIF_MODEL_E1000` - E1000 VIF model
- `COMPUTE_NET_VIF_MODEL_E1000E` - E1000E VIF model
- `COMPUTE_NET_VIF_MODEL_LAN9118` - LAN9118 VIF model
- `COMPUTE_NET_VIF_MODEL_NETFRONT` - Netfront VIF model
- `COMPUTE_NET_VIF_MODEL_NE2K_PCI` - NE2K PCI VIF model
- `COMPUTE_NET_VIF_MODEL_PCNET` - PCnet VIF model
- `COMPUTE_NET_VIF_MODEL_RTL8139` - RTL8139 VIF model
- `COMPUTE_NET_VIF_MODEL_SPAPR_VLAN` - SPAPR VLAN VIF model
- `COMPUTE_NET_VIF_MODEL_SRIOV` - SR-IOV VIF model
- `COMPUTE_NET_VIF_MODEL_VIRTIO` - Virtio VIF model
- `COMPUTE_NET_VIF_MODEL_VMXNET` - VMXnet VIF model
- `COMPUTE_NET_VIF_MODEL_VMXNET3` - VMXnet3 VIF model
- `COMPUTE_NET_VIF_MODEL_IGB` - IGB VIF model

#### Security
- `COMPUTE_SECURITY_TPM_1_2` - TPM 1.2 support
- `COMPUTE_SECURITY_TPM_2_0` - TPM 2.0 support
- `COMPUTE_SECURITY_TPM_TIS` - TPM with TIS interface
- `COMPUTE_SECURITY_TPM_CRB` - TPM with CRB interface
- `COMPUTE_SECURITY_TPM_SECRET_SECURITY_USER` - User vTPM secret policy
- `COMPUTE_SECURITY_TPM_SECRET_SECURITY_HOST` - Host vTPM secret policy
- `COMPUTE_SECURITY_TPM_SECRET_SECURITY_DEPLOYMENT` - Deployment vTPM secret policy
- `COMPUTE_SECURITY_UEFI_SECURE_BOOT` - UEFI Secure Boot support
- `COMPUTE_SECURITY_STATELESS_FIRMWARE` - Stateless firmware support

#### Sound Models
- `COMPUTE_SOUND_MODEL_SB16` - Sound Blaster 16 model
- `COMPUTE_SOUND_MODEL_ES1370` - ES1370 model
- `COMPUTE_SOUND_MODEL_PCSPK` - PC speaker model
- `COMPUTE_SOUND_MODEL_AC97` - AC97 model
- `COMPUTE_SOUND_MODEL_ICH6` - ICH6 model
- `COMPUTE_SOUND_MODEL_ICH9` - ICH9 model
- `COMPUTE_SOUND_MODEL_USB` - USB sound model
- `COMPUTE_SOUND_MODEL_VIRTIO` - Virtio sound model

#### Status
- `COMPUTE_STATUS_DISABLED` - Compute node resource provider is disabled

#### Storage/Disk Bus
- `COMPUTE_STORAGE_BUS_FDC` - Floppy disk controller bus
- `COMPUTE_STORAGE_BUS_IDE` - IDE bus
- `COMPUTE_STORAGE_BUS_LXC` - LXC bus
- `COMPUTE_STORAGE_BUS_SATA` - SATA bus
- `COMPUTE_STORAGE_BUS_SCSI` - SCSI bus
- `COMPUTE_STORAGE_BUS_USB` - USB bus
- `COMPUTE_STORAGE_BUS_VIRTIO` - Virtio bus
- `COMPUTE_STORAGE_BUS_UML` - UML bus
- `COMPUTE_STORAGE_BUS_XEN` - Xen bus
- `COMPUTE_STORAGE_VIRTIO_FS` - Supports virtio filesystems

#### USB Models
- `COMPUTE_USB_MODEL_QEMU_XHCI` - QEMU XHCI USB model
- `COMPUTE_USB_MODEL_NEC_XHCI` - NEC XHCI USB model

#### Volume Operations
- `COMPUTE_VOLUME_ATTACH` - Supports attaching volume after boot
- `COMPUTE_VOLUME_ATTACH_WITH_TAG` - Supports attaching volume with device tag
- `COMPUTE_VOLUME_EXTEND` - Supports extending volume after boot
- `COMPUTE_VOLUME_MULTI_ATTACH` - Supports volumes attachable to multiple guests

#### vIOMMU Models
- `COMPUTE_VIOMMU_MODEL_INTEL` - Intel vIOMMU model
- `COMPUTE_VIOMMU_MODEL_SMMUV3` - SMMU v3 model
- `COMPUTE_VIOMMU_MODEL_VIRTIO` - Virtio vIOMMU model
- `COMPUTE_VIOMMU_MODEL_AUTO` - Auto vIOMMU model

### HW_* Traits (Hardware Characteristics)

#### Architecture
- `HW_ARCH_ALPHA` - Alpha architecture
- `HW_ARCH_ARMV6` - ARM v6 architecture
- `HW_ARCH_ARMV7` - ARM v7 architecture
- `HW_ARCH_ARMV7B` - ARM v7 big-endian architecture
- `HW_ARCH_AARCH64` - ARM 64-bit architecture
- `HW_ARCH_CRIS` - CRIS architecture
- `HW_ARCH_I686` - Intel i686 architecture
- `HW_ARCH_IA64` - Intel Itanium architecture
- `HW_ARCH_LM32` - LM32 architecture
- `HW_ARCH_M68K` - Motorola 68000 architecture
- `HW_ARCH_MICROBLAZE` - MicroBlaze architecture
- `HW_ARCH_MICROBLAZEEL` - MicroBlaze little-endian architecture
- `HW_ARCH_MIPS` - MIPS architecture
- `HW_ARCH_MIPSEL` - MIPS little-endian architecture
- `HW_ARCH_MIPS64` - MIPS 64-bit architecture
- `HW_ARCH_MIPS64EL` - MIPS 64-bit little-endian architecture
- `HW_ARCH_OPENRISC` - OpenRISC architecture
- `HW_ARCH_PARISC` - PA-RISC architecture
- `HW_ARCH_PARISC64` - PA-RISC 64-bit architecture
- `HW_ARCH_PPC` - PowerPC architecture
- `HW_ARCH_PPCLE` - PowerPC little-endian architecture
- `HW_ARCH_PPC64` - PowerPC 64-bit architecture
- `HW_ARCH_PPC64LE` - PowerPC 64-bit little-endian architecture
- `HW_ARCH_PPCEMB` - PowerPC embedded architecture
- `HW_ARCH_S390` - IBM System z architecture
- `HW_ARCH_S390X` - IBM System z 64-bit architecture
- `HW_ARCH_SH4` - SuperH-4 architecture
- `HW_ARCH_SH4EB` - SuperH-4 big-endian architecture
- `HW_ARCH_SPARC` - SPARC architecture
- `HW_ARCH_SPARC64` - SPARC 64-bit architecture
- `HW_ARCH_UNICORE32` - UniCore32 architecture
- `HW_ARCH_X86_64` - x86-64 architecture
- `HW_ARCH_XTENSA` - Xtensa architecture
- `HW_ARCH_XTENSAEB` - Xtensa big-endian architecture

#### CPU - ARM AArch64
- `HW_CPU_AARCH64_FP` - Floating-point support
- `HW_CPU_AARCH64_ASIMD` - Advanced SIMD support
- `HW_CPU_AARCH64_EVTSTRM` - Event stream support
- `HW_CPU_AARCH64_AES` - AES instructions
- `HW_CPU_AARCH64_PMULL` - Polynomial multiply long instructions
- `HW_CPU_AARCH64_SHA1` - SHA1 instructions
- `HW_CPU_AARCH64_SHA2` - SHA2 instructions
- `HW_CPU_AARCH64_CRC32` - CRC32 instructions
- `HW_CPU_AARCH64_FPHP` - Half-precision floating-point support
- `HW_CPU_AARCH64_ASIMDHP` - Half-precision ASIMD support
- `HW_CPU_AARCH64_ASIMDRDM` - ASIMD rounding double multiply support
- `HW_CPU_AARCH64_ATOMICS` - Atomic instructions
- `HW_CPU_AARCH64_JSCVT` - JavaScript conversion instructions
- `HW_CPU_AARCH64_FCMA` - Floating-point complex number arithmetic
- `HW_CPU_AARCH64_LRCPC` - Load-acquire RCpc instructions
- `HW_CPU_AARCH64_DCPOP` - Data cache clean to point of persistence
- `HW_CPU_AARCH64_SHA3` - SHA3 instructions
- `HW_CPU_AARCH64_SM3` - SM3 instructions
- `HW_CPU_AARCH64_SM4` - SM4 instructions
- `HW_CPU_AARCH64_ASIMDDP` - ASIMD dot product support
- `HW_CPU_AARCH64_SHA512` - SHA512 instructions
- `HW_CPU_AARCH64_SVE` - Scalable Vector Extension
- `HW_CPU_AARCH64_CPUID` - CPU identification register

#### CPU - AMD (x86)
- `HW_CPU_X86_AMD_SEV` - AMD Secure Encrypted Virtualization
- `HW_CPU_X86_AMD_SEV_ES` - AMD SEV Encrypted State
- `HW_CPU_X86_AMD_SVM` - AMD-V virtualization
- `HW_CPU_X86_AMD_IBPB` - Indirect Branch Prediction Barrier
- `HW_CPU_X86_AMD_NO_SSB` - No Speculative Store Bypass
- `HW_CPU_X86_AMD_SSBD` - Speculative Store Bypass Disable
- `HW_CPU_X86_AMD_VIRT_SSBD` - Virtualized SSBD

#### CPU - Intel (x86)
- `HW_CPU_X86_INTEL_MD_CLEAR` - MDS (Microarchitectural Data Sampling) mitigation
- `HW_CPU_X86_INTEL_PCID` - Process Context ID support
- `HW_CPU_X86_INTEL_SPEC_CTRL` - Speculation control
- `HW_CPU_X86_INTEL_SSBD` - Speculative Store Bypass Disable
- `HW_CPU_X86_INTEL_VMX` - Intel VT-x virtualization

#### CPU - x86 Common (Intel and AMD)
- `HW_CPU_X86_AVX` - Advanced Vector Extensions
- `HW_CPU_X86_AVX2` - Advanced Vector Extensions 2
- `HW_CPU_X86_CLMUL` - Carry-less multiplication
- `HW_CPU_X86_FMA3` - Fused multiply-add 3-operand
- `HW_CPU_X86_FMA4` - Fused multiply-add 4-operand
- `HW_CPU_X86_F16C` - Half-precision conversion
- `HW_CPU_X86_MMX` - MMX instructions
- `HW_CPU_X86_SSE` - Streaming SIMD Extensions
- `HW_CPU_X86_SSE2` - SSE2 instructions
- `HW_CPU_X86_SSE3` - SSE3 instructions
- `HW_CPU_X86_SSSE3` - Supplemental SSE3
- `HW_CPU_X86_SSE41` - SSE4.1 instructions
- `HW_CPU_X86_SSE42` - SSE4.2 instructions
- `HW_CPU_X86_SSE4A` - SSE4a instructions (AMD)
- `HW_CPU_X86_XOP` - Extended Operations (AMD)
- `HW_CPU_X86_3DNOW` - 3DNow! instructions (AMD)
- `HW_CPU_X86_AVX512F` - AVX-512 Foundation
- `HW_CPU_X86_AVX512CD` - AVX-512 Conflict Detection
- `HW_CPU_X86_AVX512PF` - AVX-512 Prefetch
- `HW_CPU_X86_AVX512ER` - AVX-512 Exponential and Reciprocal
- `HW_CPU_X86_AVX512VL` - AVX-512 Vector Length Extensions
- `HW_CPU_X86_AVX512BW` - AVX-512 Byte and Word
- `HW_CPU_X86_AVX512DQ` - AVX-512 Doubleword and Quadword
- `HW_CPU_X86_AVX512VNNI` - AVX-512 Vector Neural Network Instructions
- `HW_CPU_X86_AVX512VBMI` - AVX-512 Vector Byte Manipulation Instructions
- `HW_CPU_X86_AVX512IFMA` - AVX-512 Integer Fused Multiply Add
- `HW_CPU_X86_AVX512VBMI2` - AVX-512 Vector Byte Manipulation Instructions 2
- `HW_CPU_X86_AVX512BITALG` - AVX-512 Bit Algorithms
- `HW_CPU_X86_AVX512VAES` - AVX-512 Vector AES Instructions
- `HW_CPU_X86_AVX512GFNI` - AVX-512 Galois Field New Instructions
- `HW_CPU_X86_AVX512VPCLMULQDQ` - AVX-512 Carry-less Multiplication of Quadwords
- `HW_CPU_X86_AVX512VPOPCNTDQ` - AVX-512 Vector Population Count Instruction
- `HW_CPU_X86_ABM` - Advanced Bit Manipulation
- `HW_CPU_X86_BMI` - Bit Manipulation Instructions
- `HW_CPU_X86_BMI2` - Bit Manipulation Instructions 2
- `HW_CPU_X86_TBM` - Trailing Bit Manipulation (AMD)
- `HW_CPU_X86_AESNI` - AES New Instructions
- `HW_CPU_X86_SHA` - Intel SHA extensions
- `HW_CPU_X86_MPX` - Memory Protection Extensions
- `HW_CPU_X86_SGX` - Software Guard Extensions
- `HW_CPU_X86_TSX` - Transactional Synchronization Extensions
- `HW_CPU_X86_ASF` - Advanced Synchronization Facility
- `HW_CPU_X86_PDPE1GB` - 1GB page directory entries (recommended for 1GB pages)
- `HW_CPU_X86_STIBP` - Single Thread Indirect Branch Predictors (Spectre v2 mitigation)

#### CPU - General
- `HW_CPU_HYPERTHREADING` - Hyperthreading enabled on provider

#### GPU - API Support
- `HW_GPU_API_DIRECTX_V10` - DirectX 10 support
- `HW_GPU_API_DIRECTX_V11` - DirectX 11 support
- `HW_GPU_API_DIRECTX_V12` - DirectX 12 support
- `HW_GPU_API_DIRECT2D` - Direct2D support
- `HW_GPU_API_DIRECT3D_V6_0` - Direct3D 6.0 support
- `HW_GPU_API_DIRECT3D_V7_0` - Direct3D 7.0 support
- `HW_GPU_API_DIRECT3D_V8_0` - Direct3D 8.0 support
- `HW_GPU_API_DIRECT3D_V8_1` - Direct3D 8.1 support
- `HW_GPU_API_DIRECT3D_V9_0` - Direct3D 9.0 support
- `HW_GPU_API_DIRECT3D_V9_0B` - Direct3D 9.0b support
- `HW_GPU_API_DIRECT3D_V9_0C` - Direct3D 9.0c support
- `HW_GPU_API_DIRECT3D_V9_0L` - Direct3D 9.0L support
- `HW_GPU_API_DIRECT3D_V10_0` - Direct3D 10.0 support
- `HW_GPU_API_DIRECT3D_V10_1` - Direct3D 10.1 support
- `HW_GPU_API_DIRECT3D_V11_0` - Direct3D 11.0 support
- `HW_GPU_API_DIRECT3D_V11_1` - Direct3D 11.1 support
- `HW_GPU_API_DIRECT3D_V11_2` - Direct3D 11.2 support
- `HW_GPU_API_DIRECT3D_V11_3` - Direct3D 11.3 support
- `HW_GPU_API_DIRECT3D_V12_0` - Direct3D 12.0 support
- `HW_GPU_API_VULKAN` - Vulkan API support
- `HW_GPU_API_DXVA` - DirectX Video Acceleration support
- `HW_GPU_API_OPENCL_V1_0` - OpenCL 1.0 support
- `HW_GPU_API_OPENCL_V1_1` - OpenCL 1.1 support
- `HW_GPU_API_OPENCL_V1_2` - OpenCL 1.2 support
- `HW_GPU_API_OPENCL_V2_0` - OpenCL 2.0 support
- `HW_GPU_API_OPENCL_V2_1` - OpenCL 2.1 support
- `HW_GPU_API_OPENCL_V2_2` - OpenCL 2.2 support
- `HW_GPU_API_OPENGL_V1_1` - OpenGL 1.1 support
- `HW_GPU_API_OPENGL_V1_2` - OpenGL 1.2 support
- `HW_GPU_API_OPENGL_V1_3` - OpenGL 1.3 support
- `HW_GPU_API_OPENGL_V1_4` - OpenGL 1.4 support
- `HW_GPU_API_OPENGL_V1_5` - OpenGL 1.5 support
- `HW_GPU_API_OPENGL_V2_0` - OpenGL 2.0 support
- `HW_GPU_API_OPENGL_V2_1` - OpenGL 2.1 support
- `HW_GPU_API_OPENGL_V3_0` - OpenGL 3.0 support
- `HW_GPU_API_OPENGL_V3_1` - OpenGL 3.1 support
- `HW_GPU_API_OPENGL_V3_2` - OpenGL 3.2 support
- `HW_GPU_API_OPENGL_V3_3` - OpenGL 3.3 support
- `HW_GPU_API_OPENGL_V4_0` - OpenGL 4.0 support
- `HW_GPU_API_OPENGL_V4_1` - OpenGL 4.1 support
- `HW_GPU_API_OPENGL_V4_2` - OpenGL 4.2 support
- `HW_GPU_API_OPENGL_V4_3` - OpenGL 4.3 support
- `HW_GPU_API_OPENGL_V4_4` - OpenGL 4.4 support
- `HW_GPU_API_OPENGL_V4_5` - OpenGL 4.5 support

#### GPU - CUDA Compute Capabilities
- `HW_GPU_CUDA_COMPUTE_CAPABILITY_V1_0` - CUDA compute capability 1.0
- `HW_GPU_CUDA_COMPUTE_CAPABILITY_V1_1` - CUDA compute capability 1.1
- `HW_GPU_CUDA_COMPUTE_CAPABILITY_V1_2` - CUDA compute capability 1.2
- `HW_GPU_CUDA_COMPUTE_CAPABILITY_V1_3` - CUDA compute capability 1.3
- `HW_GPU_CUDA_COMPUTE_CAPABILITY_V2_0` - CUDA compute capability 2.0
- `HW_GPU_CUDA_COMPUTE_CAPABILITY_V2_1` - CUDA compute capability 2.1
- `HW_GPU_CUDA_COMPUTE_CAPABILITY_V3_0` - CUDA compute capability 3.0
- `HW_GPU_CUDA_COMPUTE_CAPABILITY_V3_2` - CUDA compute capability 3.2
- `HW_GPU_CUDA_COMPUTE_CAPABILITY_V3_5` - CUDA compute capability 3.5
- `HW_GPU_CUDA_COMPUTE_CAPABILITY_V3_7` - CUDA compute capability 3.7
- `HW_GPU_CUDA_COMPUTE_CAPABILITY_V5_0` - CUDA compute capability 5.0
- `HW_GPU_CUDA_COMPUTE_CAPABILITY_V5_2` - CUDA compute capability 5.2
- `HW_GPU_CUDA_COMPUTE_CAPABILITY_V5_3` - CUDA compute capability 5.3
- `HW_GPU_CUDA_COMPUTE_CAPABILITY_V6_0` - CUDA compute capability 6.0
- `HW_GPU_CUDA_COMPUTE_CAPABILITY_V6_1` - CUDA compute capability 6.1
- `HW_GPU_CUDA_COMPUTE_CAPABILITY_V6_2` - CUDA compute capability 6.2
- `HW_GPU_CUDA_COMPUTE_CAPABILITY_V7_0` - CUDA compute capability 7.0
- `HW_GPU_CUDA_COMPUTE_CAPABILITY_V7_1` - CUDA compute capability 7.1
- `HW_GPU_CUDA_COMPUTE_CAPABILITY_V7_2` - CUDA compute capability 7.2

#### GPU - CUDA SDK Versions
- `HW_GPU_CUDA_SDK_V6_5` - CUDA SDK 6.5
- `HW_GPU_CUDA_SDK_V7_5` - CUDA SDK 7.5
- `HW_GPU_CUDA_SDK_V8_0` - CUDA SDK 8.0
- `HW_GPU_CUDA_SDK_V9_0` - CUDA SDK 9.0
- `HW_GPU_CUDA_SDK_V9_1` - CUDA SDK 9.1
- `HW_GPU_CUDA_SDK_V9_2` - CUDA SDK 9.2
- `HW_GPU_CUDA_SDK_V10_0` - CUDA SDK 10.0

#### GPU - Display Heads
- `HW_GPU_MAX_DISPLAY_HEAD_1` - Maximum 1 display head
- `HW_GPU_MAX_DISPLAY_HEAD_2` - Maximum 2 display heads
- `HW_GPU_MAX_DISPLAY_HEAD_4` - Maximum 4 display heads
- `HW_GPU_MAX_DISPLAY_HEAD_6` - Maximum 6 display heads
- `HW_GPU_MAX_DISPLAY_HEAD_8` - Maximum 8 display heads

#### GPU - Resolution
- `HW_GPU_RESOLUTION_W320H240` - 320x240 resolution
- `HW_GPU_RESOLUTION_W640H480` - 640x480 resolution
- `HW_GPU_RESOLUTION_W800H600` - 800x600 resolution
- `HW_GPU_RESOLUTION_W1024H600` - 1024x600 resolution
- `HW_GPU_RESOLUTION_W1024H768` - 1024x768 resolution
- `HW_GPU_RESOLUTION_W1152H864` - 1152x864 resolution
- `HW_GPU_RESOLUTION_W1280H720` - 1280x720 resolution
- `HW_GPU_RESOLUTION_W1280H768` - 1280x768 resolution
- `HW_GPU_RESOLUTION_W1280H800` - 1280x800 resolution
- `HW_GPU_RESOLUTION_W1280H1024` - 1280x1024 resolution
- `HW_GPU_RESOLUTION_W1360H768` - 1360x768 resolution
- `HW_GPU_RESOLUTION_W1366H768` - 1366x768 resolution
- `HW_GPU_RESOLUTION_W1440H900` - 1440x900 resolution
- `HW_GPU_RESOLUTION_W1600H900` - 1600x900 resolution
- `HW_GPU_RESOLUTION_W1600H1200` - 1600x1200 resolution
- `HW_GPU_RESOLUTION_W1680H1050` - 1680x1050 resolution
- `HW_GPU_RESOLUTION_W1920H1080` - 1920x1080 resolution
- `HW_GPU_RESOLUTION_W1920H1200` - 1920x1200 resolution
- `HW_GPU_RESOLUTION_W2560H1440` - 2560x1440 resolution
- `HW_GPU_RESOLUTION_W2560H1600` - 2560x1600 resolution
- `HW_GPU_RESOLUTION_W3840H2160` - 3840x2160 resolution
- `HW_GPU_RESOLUTION_W7680H4320` - 7680x4320 resolution

#### NIC - Acceleration
- `HW_NIC_ACCEL_SSL` - SSL crypto acceleration
- `HW_NIC_ACCEL_IPSEC` - IP-Sec crypto acceleration
- `HW_NIC_ACCEL_TLS` - TLS crypto acceleration
- `HW_NIC_ACCEL_DIFFIEH` - Diffie-Hellman crypto acceleration
- `HW_NIC_ACCEL_RSA` - RSA crypto acceleration
- `HW_NIC_ACCEL_ECC` - Elliptic Curve crypto acceleration
- `HW_NIC_ACCEL_LZS` - LZS compression acceleration
- `HW_NIC_ACCEL_DEFLATE` - Deflate compression acceleration

#### NIC - DCB (Data Center Bridging)
- `HW_NIC_DCB_PFC` - IEEE 802.1Qbb Priority-flow control
- `HW_NIC_DCB_ETS` - IEEE 802.1Qaz Enhanced Transmission Selection
- `HW_NIC_DCB_QCN` - IEEE 802.1Qau Quantized Congestion Notification

#### NIC - General
- `HW_NIC_SRIOV` - NIC supports partitioning via SR-IOV
- `HW_NIC_MULTIQUEUE` - Multiple receive and transmit queues
- `HW_NIC_VMDQ` - Virtual machine device queues
- `HW_NIC_PROGRAMMABLE_PIPELINE` - Programmable processing pipelines via FPGAs

#### NIC - Offload
- `HW_NIC_OFFLOAD_TSO` - TCP segmentation offload
- `HW_NIC_OFFLOAD_GRO` - Generic receive offload
- `HW_NIC_OFFLOAD_GSO` - Generic segmentation offload
- `HW_NIC_OFFLOAD_UFO` - UDP fragmentation offload
- `HW_NIC_OFFLOAD_LRO` - Large receive offload
- `HW_NIC_OFFLOAD_LSO` - Large send offload
- `HW_NIC_OFFLOAD_TCS` - TCP checksum offload
- `HW_NIC_OFFLOAD_UCS` - UDP checksum offload
- `HW_NIC_OFFLOAD_SCS` - SCTP checksum offload
- `HW_NIC_OFFLOAD_L2CRC` - Layer-2 CRC offload
- `HW_NIC_OFFLOAD_FDF` - Intel Flow-Director Filter
- `HW_NIC_OFFLOAD_RXVLAN` - VLAN receive tunnel segmentation
- `HW_NIC_OFFLOAD_TXVLAN` - VLAN transmit tunnel segmentation
- `HW_NIC_OFFLOAD_VXLAN` - VxLAN tunneling offload
- `HW_NIC_OFFLOAD_GRE` - GRE tunneling offload
- `HW_NIC_OFFLOAD_GENEVE` - Geneve tunneling offload
- `HW_NIC_OFFLOAD_TXUDP` - UDP transmit tunnel segmentation
- `HW_NIC_OFFLOAD_QINQ` - QinQ specification support
- `HW_NIC_OFFLOAD_RDMA` - Remote direct memory access
- `HW_NIC_OFFLOAD_RXHASH` - Receive hashing
- `HW_NIC_OFFLOAD_RX` - RX checksumming
- `HW_NIC_OFFLOAD_TX` - TX checksumming
- `HW_NIC_OFFLOAD_SG` - Scatter-gather
- `HW_NIC_OFFLOAD_SWITCHDEV` - Offload datapath rules

#### NIC - SR-IOV
- `HW_NIC_SRIOV_QOS_TX` - VF can restrict transmit rates
- `HW_NIC_SRIOV_QOS_RX` - VF can restrict receive rates
- `HW_NIC_SRIOV_MULTIQUEUE` - VF supports multiple receive/transmit queues
- `HW_NIC_SRIOV_TRUSTED` - VF/PF marked as trusted

#### NUMA
- `HW_NUMA_ROOT` - Provider represents subtree root of NUMA node (for NUMA affinity requests)

#### PCI
- `HW_PCI_LIVE_MIGRATABLE` - PCI device can be live-migrated between compute nodes
- `HW_PCI_ONE_TIME_USE` - PCI device lifecycle managed as "one time use"

### STORAGE_* Traits (Storage Characteristics)
- `STORAGE_DISK_HDD` - Spinning disk (hard disk drive)
- `STORAGE_DISK_SSD` - Solid-state disk

### MISC_* Traits (Miscellaneous)
- `MISC_SHARES_VIA_AGGREGATE` - Provider shares resources via aggregate association (e.g., shared storage pool)

### OWNER_* Traits (Resource Provider Owner)
- `OWNER_CYBORG` - Resource provider owner is Cyborg
- `OWNER_NOVA` - Resource provider owner is Nova

### Custom Traits
- `CUSTOM_*` - User-defined traits (must start with "CUSTOM_" prefix)
