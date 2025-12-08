---
title: Soft Constraints
description: Preferred and avoided traits for weighing decisions
keywords: [preferred, avoided, soft-affinity, soft-anti-affinity, weight]
related:
  - 01-schema/nodes/trait.md
  - 01-schema/relationships/scheduling.md
  - 04-queries/weighers/trait-affinity-weigher.md
implements:
  - "Preferred traits"
  - "Avoided traits"
  - "Weighted trait preferences"
section: patterns
---

# Soft Constraints

Soft constraints influence scheduling decisions without hard filtering. Unlike required/forbidden traits which exclude hosts, preferred/avoided traits adjust host scores.

## Constraint Types Comparison

| Constraint | Type | Behavior |
|------------|------|----------|
| `required` | Hard | Provider MUST have trait (filter) |
| `forbidden` | Hard | Provider MUST NOT have trait (filter) |
| `preferred` | Soft | Prefer providers WITH trait (weigher, positive score) |
| `avoided` | Soft | Prefer providers WITHOUT trait (weigher, negative score) |

## Flavor Extra Spec Syntax

```cypher
(:Flavor {
  extra_specs: {
    'trait:HW_CPU_X86_AVX2': 'required',           // Must have AVX2
    'trait:COMPUTE_STATUS_DISABLED': 'forbidden',  // Must not be disabled
    'trait:STORAGE_DISK_SSD': 'preferred:2.0',     // Prefer SSD (weight 2.0)
    'trait:CUSTOM_OVERLOADED': 'avoided:3.0'       // Avoid overloaded (weight 3.0)
  }
})
```

## Modeling in Graph

Using REQUIRES_TRAIT relationship:

```cypher
// Preferred trait with weight
CREATE (f:Flavor)-[:REQUIRES_TRAIT {
  constraint: 'preferred',
  weight: 2.0
}]->(t:Trait {name: 'STORAGE_DISK_SSD'})

// Avoided trait with weight
CREATE (f:Flavor)-[:REQUIRES_TRAIT {
  constraint: 'avoided',
  weight: 1.5
}]->(t:Trait {name: 'CUSTOM_MAINTENANCE_WINDOW'})
```

## Preferred Trait Scoring

```cypher
// Calculate preferred trait score for each host
MATCH (rp:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(rp)

// Calculate weighted score
WITH rp, $preferred_traits AS preferred
WITH rp,
     [p IN preferred WHERE (rp)-[:HAS_TRAIT]->(:Trait {name: p.name}) | p.weight] AS matched_weights

WITH rp,
     reduce(score = 0.0, w IN matched_weights | score + w) AS preferred_score

RETURN rp, preferred_score
ORDER BY preferred_score DESC
```

## Avoided Trait Penalty

```cypher
// Calculate avoided trait penalty for each host
MATCH (rp:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(rp)

// Calculate penalty for having avoided traits
WITH rp, $avoided_traits AS avoided
WITH rp,
     [a IN avoided WHERE (rp)-[:HAS_TRAIT]->(:Trait {name: a.name}) | a.weight] AS matched_penalties

WITH rp,
     reduce(penalty = 0.0, w IN matched_penalties | penalty + w) AS avoided_penalty

// Negative score means penalty
RETURN rp, -1 * avoided_penalty AS avoided_score
ORDER BY avoided_score DESC
```

## Combined Scoring

```cypher
// Combined soft trait scoring
MATCH (rp:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(rp)

// Calculate preferred score
WITH rp,
     reduce(score = 0.0, p IN $preferred_traits |
       score + CASE WHEN (rp)-[:HAS_TRAIT]->(:Trait {name: p.name}) THEN p.weight ELSE 0.0 END
     ) AS preferred_score

// Calculate avoided penalty
WITH rp, preferred_score,
     reduce(penalty = 0.0, a IN $avoided_traits |
       penalty + CASE WHEN (rp)-[:HAS_TRAIT]->(:Trait {name: a.name}) THEN a.weight ELSE 0.0 END
     ) AS avoided_penalty

// Combined score: preferred bonus minus avoided penalty
WITH rp,
     preferred_score,
     avoided_penalty,
     (preferred_score - avoided_penalty) * $trait_weight_multiplier AS trait_affinity_score

RETURN rp, preferred_score, avoided_penalty, trait_affinity_score
ORDER BY trait_affinity_score DESC
```

## Flavor-Driven Soft Trait Resolution

```cypher
// Resolve traits from flavor and apply scoring
MATCH (flavor:Flavor {uuid: $flavor_uuid})
OPTIONAL MATCH (flavor)-[req:REQUIRES_TRAIT]->(trait:Trait)

WITH flavor,
     collect(CASE WHEN req.constraint = 'required' THEN trait.name END) AS required,
     collect(CASE WHEN req.constraint = 'forbidden' THEN trait.name END) AS forbidden,
     collect(CASE WHEN req.constraint = 'preferred'
                  THEN {name: trait.name, weight: COALESCE(req.weight, 1.0)} END) AS preferred,
     collect(CASE WHEN req.constraint = 'avoided'
                  THEN {name: trait.name, weight: COALESCE(req.weight, 1.0)} END) AS avoided

// Filter out nulls
WITH required, forbidden,
     [p IN preferred WHERE p IS NOT NULL] AS preferred_traits,
     [a IN avoided WHERE a IS NOT NULL] AS avoided_traits

// Apply hard constraints first (filter)
MATCH (rp:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(rp)
  AND ALL(t IN required WHERE (rp)-[:HAS_TRAIT]->(:Trait {name: t}))
  AND NONE(t IN forbidden WHERE (rp)-[:HAS_TRAIT]->(:Trait {name: t}))

// Apply soft constraints (weigh)
WITH rp, preferred_traits, avoided_traits,
     reduce(score = 0.0, p IN preferred_traits |
       score + CASE WHEN (rp)-[:HAS_TRAIT]->(:Trait {name: p.name}) THEN p.weight ELSE 0.0 END
     ) AS preferred_score,
     reduce(penalty = 0.0, a IN avoided_traits |
       penalty + CASE WHEN (rp)-[:HAS_TRAIT]->(:Trait {name: a.name}) THEN a.weight ELSE 0.0 END
     ) AS avoided_penalty

RETURN rp, preferred_score - avoided_penalty AS soft_trait_score
ORDER BY soft_trait_score DESC
```

## Use Cases

1. **Prefer SSD storage**: `trait:STORAGE_DISK_SSD=preferred:2.0`
2. **Avoid maintenance hosts**: `trait:CUSTOM_MAINTENANCE=avoided:5.0`
3. **Prefer newer hardware**: `trait:HW_CPU_X86_AVX512F=preferred:1.0`
4. **Avoid overloaded hosts**: `trait:CUSTOM_HIGH_LOAD=avoided:3.0`
