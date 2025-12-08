---
title: Glossary
description: Term definitions and quick reference
keywords: [glossary, terms, definitions, reference]
related:
  - 00-overview/introduction.md
  - reference/quick-reference.md
implements: []
section: overview
---

# Glossary

## Core Entities

| Term | Definition |
|------|------------|
| **ResourceProvider** | Source of resources; forms hierarchical trees (e.g., compute host) |
| **Inventory** | Quantitative resources on a provider (total, reserved, allocation_ratio) |
| **Consumer** | Entity consuming resources (e.g., VM instance) |
| **ResourceClass** | Type of resource (VCPU, MEMORY_MB, DISK_GB, CUSTOM_*) |
| **Trait** | Qualitative capability (HW_CPU_X86_AVX2, COMPUTE_STATUS_DISABLED) |
| **Aggregate** | Logical grouping of providers (host aggregates, AZs) |

## Scheduling Concepts

| Term | Definition |
|------|------------|
| **Allocation** | Record of resources consumed by a consumer (CONSUMES relationship) |
| **Capacity** | `(total - reserved) * allocation_ratio` |
| **Generation** | Optimistic concurrency version number |
| **Root Provider** | Provider with no parent (top of tree) |
| **Sharing Provider** | Provider that shares resources with other trees |

## Constraint Types

| Term | Definition |
|------|------------|
| **Required Trait** | Provider MUST have this trait (hard constraint) |
| **Forbidden Trait** | Provider MUST NOT have this trait (hard constraint) |
| **Preferred Trait** | Favor providers WITH this trait (soft constraint, weigher) |
| **Avoided Trait** | Favor providers WITHOUT this trait (soft constraint, weigher) |

## Hardware Topology

| Term | Definition |
|------|------------|
| **NUMA Node** | Non-Uniform Memory Access node; nested provider |
| **PCI PF** | Physical Function; SR-IOV parent device |
| **PCI VF** | Virtual Function; SR-IOV child device |
| **vGPU** | Virtual GPU; child of physical GPU provider |
| **Physnet** | Physical network; represented as trait on PCI device |

## Relationship Types

| Relationship | Meaning |
|--------------|---------|
| `PARENT_OF` | Hierarchical tree structure |
| `HAS_INVENTORY` | Provider owns inventory |
| `OF_CLASS` | Inventory is of resource class |
| `CONSUMES` | Consumer uses inventory (with `used` amount) |
| `HAS_TRAIT` | Provider has capability |
| `MEMBER_OF` | Provider belongs to aggregate |
| `SHARES_RESOURCES` | Provider shares with another tree |
