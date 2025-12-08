---
title: Compute and Image Filters
description: ComputeFilter, ImagePropertiesFilter implementations
keywords: [compute-filter, image-properties, disabled, hypervisor-type]
related:
  - 04-queries/allocation-candidates.md
  - 01-schema/nodes/resource-provider.md
implements:
  - "ComputeFilter"
  - "ImagePropertiesFilter"
section: queries/filters
---

# Compute and Image Filters

## ComputeFilter

Filter out disabled or down compute nodes.

```cypher
// Equivalent to ComputeFilter
MATCH (rp:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(rp)  // Root providers only
  AND COALESCE(rp.disabled, false) = false
  AND NOT (rp)-[:HAS_TRAIT]->(:Trait {name: 'COMPUTE_STATUS_DISABLED'})
RETURN rp
```

## ImagePropertiesFilter

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

## Compute Capabilities Filter

Match flavor extra specs against compute node properties.

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

## Image Type Support Prefilter

```cypher
// Exclude hosts that don't support image disk format
// $disk_format: 'qcow2'

MATCH (rp:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(rp)
  AND (rp)-[:HAS_TRAIT]->(:Trait {name: 'COMPUTE_IMAGE_TYPE_' + toUpper($disk_format)})
RETURN rp
```

## Cell Scheduling Filter

```cypher
// Only schedule to enabled cells
MATCH (rp:ResourceProvider)-[:LOCATED_IN]->(cell:Cell)
WHERE cell.disabled = false
RETURN rp
```

## Disabled Compute Exclusion (Mandatory Prefilter)

```cypher
// Always applied - exclude disabled computes
MATCH (rp:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(rp)
  AND NOT (rp)-[:HAS_TRAIT]->(:Trait {name: 'COMPUTE_STATUS_DISABLED'})
  AND COALESCE(rp.disabled, false) = false
RETURN rp
```

## Combined Compute/Image Filter

```cypher
MATCH (rp:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(rp)

  // ComputeFilter: not disabled
  AND COALESCE(rp.disabled, false) = false
  AND NOT (rp)-[:HAS_TRAIT]->(:Trait {name: 'COMPUTE_STATUS_DISABLED'})

  // ImagePropertiesFilter: architecture
  AND ($hw_architecture IS NULL OR
       (rp)-[:HAS_TRAIT]->(:Trait {name: 'HW_ARCH_' + toUpper($hw_architecture)}))

  // ImagePropertiesFilter: hypervisor type
  AND ($img_hv_type IS NULL OR toLower(rp.hypervisor_type) = toLower($img_hv_type))

  // ImagePropertiesFilter: VM mode
  AND ($hw_vm_mode IS NULL OR
       (rp)-[:HAS_TRAIT]->(:Trait {name: 'COMPUTE_VM_MODE_' + toUpper($hw_vm_mode)}))

  // Image type support
  AND ($disk_format IS NULL OR
       (rp)-[:HAS_TRAIT]->(:Trait {name: 'COMPUTE_IMAGE_TYPE_' + toUpper($disk_format)}))

  // Cell enabled
  AND (NOT EXISTS {MATCH (rp)-[:LOCATED_IN]->(cell:Cell) WHERE cell.disabled = true})

RETURN rp
```
