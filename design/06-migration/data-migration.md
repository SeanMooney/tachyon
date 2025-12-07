---
title: Data Migration
description: Scripts and procedures for migrating from Placement
keywords: [migration, import, export, placement, data-transfer]
related:
  - 06-migration/api-mapping.md
  - reference/placement-model.md
implements:
  - "Placement data import"
section: migration
---

# Data Migration

Scripts and procedures for migrating from OpenStack Placement to Tachyon.

## Migration Order

1. Resource Classes (standard + custom)
2. Traits (standard + custom)
3. Resource Providers (sorted by parent to ensure parents created first)
4. Inventories
5. Trait associations
6. Aggregates and memberships
7. Allocations (consumers, projects, users)

## Python Migration Script Outline

```python
def migrate_placement_to_tachyon(placement_client, neo4j_driver):
    """Migrate all Placement data to Tachyon Neo4j."""
    
    # 1. Migrate resource classes
    for rc in placement_client.get_resource_classes():
        with neo4j_driver.session() as session:
            session.run("""
                MERGE (rc:ResourceClass {name: $name})
                SET rc.standard = $standard,
                    rc.created_at = datetime()
            """, name=rc.name, standard=not rc.name.startswith('CUSTOM_'))
    
    # 2. Migrate traits
    for trait in placement_client.get_traits():
        with neo4j_driver.session() as session:
            session.run("""
                MERGE (t:Trait {name: $name})
                SET t.standard = $standard,
                    t.created_at = datetime()
            """, name=trait.name, standard=not trait.name.startswith('CUSTOM_'))
    
    # 3. Migrate resource providers (with hierarchy)
    providers = placement_client.get_resource_providers()
    sorted_providers = topological_sort_by_parent(providers)
    
    for rp in sorted_providers:
        with neo4j_driver.session() as session:
            session.run("""
                CREATE (rp:ResourceProvider {
                    uuid: $uuid,
                    name: $name,
                    generation: $generation,
                    created_at: datetime()
                })
                
                WITH rp
                OPTIONAL MATCH (parent:ResourceProvider {uuid: $parent_uuid})
                FOREACH (_ IN CASE WHEN parent IS NOT NULL THEN [1] ELSE [] END |
                    CREATE (parent)-[:PARENT_OF]->(rp)
                )
            """, uuid=rp.uuid, name=rp.name, generation=rp.generation,
                 parent_uuid=rp.parent_provider_uuid)
    
    # 4. Migrate inventories
    for rp in providers:
        inventories = placement_client.get_inventories(rp.uuid)
        for rc_name, inv in inventories.items():
            with neo4j_driver.session() as session:
                session.run("""
                    MATCH (rp:ResourceProvider {uuid: $rp_uuid})
                    MATCH (rc:ResourceClass {name: $rc_name})
                    CREATE (rp)-[:HAS_INVENTORY]->(inv:Inventory {
                        total: $total,
                        reserved: $reserved,
                        min_unit: $min_unit,
                        max_unit: $max_unit,
                        step_size: $step_size,
                        allocation_ratio: $allocation_ratio,
                        created_at: datetime()
                    })-[:OF_CLASS]->(rc)
                """, rp_uuid=rp.uuid, rc_name=rc_name, **inv)
    
    # 5. Migrate trait associations
    for rp in providers:
        traits = placement_client.get_provider_traits(rp.uuid)
        with neo4j_driver.session() as session:
            session.run("""
                MATCH (rp:ResourceProvider {uuid: $rp_uuid})
                UNWIND $traits AS trait_name
                MATCH (t:Trait {name: trait_name})
                CREATE (rp)-[:HAS_TRAIT]->(t)
            """, rp_uuid=rp.uuid, traits=traits)
    
    # 6. Migrate aggregates
    aggregates = placement_client.get_aggregates()
    for agg_uuid in aggregates:
        members = placement_client.get_aggregate_members(agg_uuid)
        with neo4j_driver.session() as session:
            session.run("""
                MERGE (agg:Aggregate {uuid: $agg_uuid})
                ON CREATE SET agg.created_at = datetime()
                
                WITH agg
                UNWIND $members AS member_uuid
                MATCH (rp:ResourceProvider {uuid: member_uuid})
                CREATE (rp)-[:MEMBER_OF]->(agg)
            """, agg_uuid=agg_uuid, members=members)
    
    # 7. Migrate allocations
    for consumer_uuid in placement_client.get_consumer_uuids():
        alloc_data = placement_client.get_allocations(consumer_uuid)
        with neo4j_driver.session() as session:
            session.run("""
                MERGE (c:Consumer {uuid: $consumer_uuid})
                ON CREATE SET c.generation = $generation,
                              c.created_at = datetime()
                
                MERGE (proj:Project {external_id: $project_id})
                MERGE (user:User {external_id: $user_id})
                MERGE (c)-[:OWNED_BY]->(proj)
                MERGE (c)-[:CREATED_BY]->(user)
                
                WITH c
                UNWIND $allocations AS alloc
                MATCH (rp:ResourceProvider {uuid: alloc.rp_uuid})
                      -[:HAS_INVENTORY]->(inv)
                      -[:OF_CLASS]->(:ResourceClass {name: alloc.rc})
                CREATE (c)-[:CONSUMES {
                    used: alloc.used,
                    created_at: datetime()
                }]->(inv)
            """, consumer_uuid=consumer_uuid, **alloc_data)
```

## Verification Queries

### Count Comparison

```cypher
// Count all major entities
MATCH (rp:ResourceProvider) WITH count(rp) AS providers
MATCH (inv:Inventory) WITH providers, count(inv) AS inventories
MATCH (t:Trait) WITH providers, inventories, count(t) AS traits
MATCH (c:Consumer) WITH providers, inventories, traits, count(c) AS consumers
MATCH ()-[a:CONSUMES]->() WITH providers, inventories, traits, consumers, count(a) AS allocations
RETURN providers, inventories, traits, consumers, allocations
```

### Hierarchy Verification

```cypher
// Verify no orphaned providers
MATCH (rp:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(rp)  // Is root
  AND NOT (rp)-[:PARENT_OF]->()  // Has no children
  AND NOT (rp)-[:HAS_INVENTORY]->()  // Has no inventory
RETURN count(rp) AS orphaned_providers
```

### Generation Consistency

```cypher
// Verify generations match Placement
MATCH (rp:ResourceProvider {uuid: $uuid})
RETURN rp.generation AS tachyon_generation
// Compare with Placement value
```

## Rollback Procedure

```cypher
// Delete all migrated data (use with caution!)
MATCH (n)
WHERE n:ResourceProvider OR n:Inventory OR n:Consumer 
   OR n:Trait OR n:ResourceClass OR n:Aggregate
   OR n:Project OR n:User
DETACH DELETE n
```

