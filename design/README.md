# Tachyon Design Documentation

Tachyon is a Neo4j-backed scheduling and resource management system designed to replace OpenStack Nova's scheduler and Placement API.

## Quick Navigation

| Section | Description |
|---------|-------------|
| [00-overview/](00-overview/) | Introduction, design principles, technology stack, glossary |
| [01-schema/](01-schema/) | Node types and relationship definitions |
| [02-patterns/](02-patterns/) | Implementation patterns (NUMA, PCI, vGPU, etc.) |
| [03-constraints/](03-constraints/) | Constraint modeling (traits, aggregates, server groups) |
| [04-queries/](04-queries/) | Cypher query implementations (filters, weighers) |
| [05-operations/](05-operations/) | Runtime operations (claiming, indexes, telemetry) |
| [06-migration/](06-migration/) | Placement API migration mapping |
| [07-watcher-integration/](07-watcher-integration/) | Watcher decision engine integration |
| [08-testing/](08-testing/) | Testing architecture and PTI compliance |
| [reference/](reference/) | OpenStack Nova/Placement reference material |
| [appendix/](appendix/) | Use case traceability matrix |

## For LLMs

Start with `_manifest.yaml` to discover relevant files by keywords. Each file contains YAML frontmatter with:
- `title`: Document title
- `description`: One-line summary
- `keywords`: Searchable terms for retrieval
- `related`: Links to related documents
- `implements`: Use cases this document addresses

## For Humans

Read sections in order (00 → 08) for progressive understanding. Each section has a README.md as its entry point.

## Key Concepts

- **ResourceProvider**: Source of resources, forms hierarchical trees
- **Inventory**: Quantitative resources (VCPU, MEMORY_MB, DISK_GB)
- **Trait**: Qualitative capabilities (HW_CPU_X86_AVX2, CUSTOM_*)
- **Consumer**: Entity consuming resources (VM instance)
- **Aggregate**: Logical grouping for scheduling policies

## Technology Stack

See [00-overview/technology-stack.md](00-overview/technology-stack.md) for details.

| Component | Technology |
|-----------|------------|
| Database | Neo4j (graph database) |
| REST API | Flask |
| Packaging | pbr (OpenStack standard) |
| Testing | stestr + Gabbi + testcontainers |

## Document Version

- **Version**: 1.0
- **Last Updated**: 2025-12-06
- **Target Audience**: Developers, operators, LLMs implementing Tachyon

