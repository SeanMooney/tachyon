---
title: Consumer, Project, User Nodes
description: Entities that consume resources and their ownership
keywords: [consumer, project, user, instance, allocation, ownership]
related:
  - 01-schema/nodes/inventory.md
  - 01-schema/relationships/consumption.md
implements:
  - "Resource consumption tracking"
  - "Tenant and user ownership"
section: schema/nodes
---

# Consumer, Project, User Nodes

## Consumer

Entity that consumes resources (e.g., VM instance, volume, migration).

```
:Consumer
  uuid:        String!    # External identifier (often matches Nova instance UUID)
  generation:  Integer!   # Optimistic concurrency version
  created_at:  DateTime!
  updated_at:  DateTime!
```

### Lifecycle Rules

- Created implicitly when allocations are made
- Deleted when all allocations (CONSUMES relationships) are removed
- `generation` incremented on allocation changes

### Example

```cypher
CREATE (c:Consumer {
  uuid: 'a1b2c3d4-e5f6-7890-abcd-ef1234567890',
  generation: 1,
  created_at: datetime(),
  updated_at: datetime()
})
```

### Relationships

| Relationship | Direction | Target | Description |
|--------------|-----------|--------|-------------|
| `CONSUMES` | outgoing | Inventory | Resources consumed |
| `OWNED_BY` | outgoing | Project | Owning project |
| `CREATED_BY` | outgoing | User | Creating user |
| `OF_TYPE` | outgoing | ConsumerType | Consumer category |
| `SCHEDULED_ON` | outgoing | ResourceProvider | Hosting provider |

---

## Project

Keystone project reference.

```
:Project
  external_id: String!   # Keystone project UUID
  created_at:  DateTime!
  updated_at:  DateTime!
```

---

## User

Keystone user reference.

```
:User
  external_id: String!   # Keystone user UUID
  created_at:  DateTime!
  updated_at:  DateTime!
```

---

## ConsumerType

Categorization for consumers.

```
:ConsumerType
  name:       String!    # e.g., "INSTANCE", "MIGRATION", "VOLUME"
  created_at: DateTime!
  updated_at: DateTime!
```

### Standard Consumer Types

| Name | Description |
|------|-------------|
| `INSTANCE` | VM instance |
| `MIGRATION` | Migration operation |
| `VOLUME` | Cinder volume |
| `SNAPSHOT` | Volume or instance snapshot |

---

## Ownership Pattern

```cypher
// Create consumer with ownership
MERGE (consumer:Consumer {uuid: $consumer_uuid})
ON CREATE SET
  consumer.generation = 0,
  consumer.created_at = datetime(),
  consumer.updated_at = datetime()

MERGE (project:Project {external_id: $project_id})
MERGE (user:User {external_id: $user_id})
MERGE (consumer)-[:OWNED_BY]->(project)
MERGE (consumer)-[:CREATED_BY]->(user)
```
