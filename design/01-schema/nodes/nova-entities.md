---
title: Nova-Specific Entities
description: Flavor, Image, ServerGroup, and ExtraSpec nodes
keywords: [flavor, image, server-group, extra-specs, affinity, anti-affinity]
related:
  - 01-schema/nodes/trait.md
  - 01-schema/nodes/resource-class.md
  - 03-constraints/server-group-constraints.md
implements:
  - "Flavor extra specs"
  - "Image properties for scheduling"
  - "Server group policies"
section: schema/nodes
---

# Nova-Specific Entities

## Flavor

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

### Extra Specs Modeling

Extra specs as map property:

```cypher
(:Flavor {
  extra_specs: {
    'hw:cpu_policy': 'dedicated',
    'hw:numa_nodes': '2',
    'trait:HW_CPU_X86_AVX2': 'required'
  }
})
```

Or as relationships for trait constraints:

```cypher
(:Flavor)-[:REQUIRES_TRAIT {constraint: 'required'}]->(:Trait {name: 'HW_CPU_X86_AVX2'})
(:Flavor)-[:REQUIRES_TRAIT {constraint: 'forbidden'}]->(:Trait {name: 'COMPUTE_STATUS_DISABLED'})
(:Flavor)-[:REQUIRES_TRAIT {constraint: 'preferred', weight: 2.0}]->(:Trait {name: 'STORAGE_DISK_SSD'})
```

### Trait Extra Specs Syntax

| Extra Spec Pattern | Constraint Type | Description |
|-------------------|-----------------|-------------|
| `trait:TRAIT_NAME=required` | Hard | Provider must have trait |
| `trait:TRAIT_NAME=forbidden` | Hard | Provider must not have trait |
| `trait:TRAIT_NAME=preferred` | Soft | Prefer providers with trait |
| `trait:TRAIT_NAME=preferred:2.0` | Soft (weighted) | Prefer with weight 2.0 |
| `trait:TRAIT_NAME=avoided` | Soft | Avoid providers with trait |
| `trait:TRAIT_NAME=avoided:1.5` | Soft (weighted) | Avoid with weight 1.5 |

---

## Image

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

### Key Properties for Scheduling

| Property | Values | Description |
|----------|--------|-------------|
| `hw_architecture` | x86_64, aarch64, ppc64le | CPU architecture |
| `img_hv_type` | kvm, qemu, xen, vmware | Hypervisor type |
| `hw_vm_mode` | hvm, xen | VM mode |
| `os_type` | linux, windows | Operating system type |
| `os_distro` | ubuntu, centos, windows | OS distribution |

---

## ServerGroup

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

### Policies

| Policy | Type | Behavior |
|--------|------|----------|
| `affinity` | Hard | All members on same host |
| `anti-affinity` | Hard | All members on different hosts |
| `soft-affinity` | Soft | Prefer same host (weigher) |
| `soft-anti-affinity` | Soft | Prefer different hosts (weigher) |

### Relationships

| Relationship | Direction | Target | Description |
|--------------|-----------|--------|-------------|
| `HAS_MEMBER` | outgoing | Consumer | Group membership |

---

## ExtraSpec (Optional)

For complex extra specs, model as separate nodes:

```
:ExtraSpec
  namespace: String!  # e.g., 'hw', 'trait', 'resources'
  key:       String!  # e.g., 'cpu_policy', 'HW_CPU_X86_AVX2'
  value:     String!  # e.g., 'dedicated', 'required'
```

```cypher
(:Flavor)-[:HAS_EXTRA_SPEC]->(:ExtraSpec {
  namespace: 'hw',
  key: 'cpu_policy',
  value: 'dedicated'
})
```

