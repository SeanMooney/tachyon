---
title: Trait-Based Constraints
description: Required, forbidden, preferred, and avoided trait filtering
keywords: [required-trait, forbidden-trait, preferred-trait, avoided-trait, any-of]
related:
  - 01-schema/nodes/trait.md
  - 01-schema/relationships/membership.md
  - 04-queries/weighers/trait-affinity-weigher.md
implements:
  - "Qualitative scheduling via traits"
section: constraints
---

# Trait-Based Constraints

## Constraint Types

| Constraint | Type | Syntax | Behavior |
|------------|------|--------|----------|
| Required | Hard | `trait:X=required` | Provider MUST have trait |
| Forbidden | Hard | `trait:X=forbidden` | Provider MUST NOT have trait |
| Preferred | Soft | `trait:X=preferred` | Prefer providers WITH trait |
| Avoided | Soft | `trait:X=avoided` | Prefer providers WITHOUT trait |

## Required Traits

Ensure resource provider has specific trait(s).

```cypher
// Single required trait
MATCH (rp:ResourceProvider)-[:HAS_TRAIT]->(:Trait {name: 'HW_CPU_X86_AVX2'})

// Multiple required traits (AND)
MATCH (rp:ResourceProvider)
WHERE ALL(trait_name IN ['HW_CPU_X86_AVX2', 'COMPUTE_VOLUME_MULTI_ATTACH']
      WHERE (rp)-[:HAS_TRAIT]->(:Trait {name: trait_name}))

// Required traits from parameter list
MATCH (rp:ResourceProvider)
WITH rp, $required_traits AS required
WHERE ALL(t IN required WHERE (rp)-[:HAS_TRAIT]->(:Trait {name: t}))
RETURN rp
```

## Forbidden Traits

Exclude resource providers with specific trait(s).

```cypher
// Single forbidden trait
MATCH (rp:ResourceProvider)
WHERE NOT (rp)-[:HAS_TRAIT]->(:Trait {name: 'COMPUTE_STATUS_DISABLED'})

// Multiple forbidden traits (none of them)
MATCH (rp:ResourceProvider)
WHERE NONE(trait_name IN ['COMPUTE_STATUS_DISABLED', 'CUSTOM_MAINTENANCE']
      WHERE (rp)-[:HAS_TRAIT]->(:Trait {name: trait_name}))

// Forbidden traits from parameter list
MATCH (rp:ResourceProvider)
WITH rp, $forbidden_traits AS forbidden
WHERE NONE(t IN forbidden WHERE (rp)-[:HAS_TRAIT]->(:Trait {name: t}))
RETURN rp
```

## Any-Of Traits (OR)

At least one trait from a set must be present.

```cypher
// Any of these traits (OR)
MATCH (rp:ResourceProvider)
WHERE ANY(trait_name IN ['HW_CPU_X86_AVX', 'HW_CPU_X86_AVX2', 'HW_CPU_X86_AVX512F']
      WHERE (rp)-[:HAS_TRAIT]->(:Trait {name: trait_name}))

// Using EXISTS
MATCH (rp:ResourceProvider)
WHERE EXISTS {
  MATCH (rp)-[:HAS_TRAIT]->(t:Trait)
  WHERE t.name IN ['HW_CPU_X86_AVX', 'HW_CPU_X86_AVX2', 'HW_CPU_X86_AVX512F']
}
RETURN rp
```

## Preferred Traits (Soft Affinity)

Prefer providers with specific traits without requiring them.

```cypher
// Calculate preferred trait score for each host
MATCH (rp:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(rp)

WITH rp, $preferred_traits AS preferred
WITH rp,
     reduce(score = 0.0, p IN preferred |
       score + CASE WHEN (rp)-[:HAS_TRAIT]->(:Trait {name: p.name}) THEN p.weight ELSE 0.0 END
     ) AS preferred_score

RETURN rp, preferred_score
ORDER BY preferred_score DESC
```

## Avoided Traits (Soft Anti-Affinity)

Avoid providers with specific traits without excluding them.

```cypher
// Calculate avoided trait penalty for each host
MATCH (rp:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(rp)

WITH rp, $avoided_traits AS avoided
WITH rp,
     reduce(penalty = 0.0, a IN avoided |
       penalty + CASE WHEN (rp)-[:HAS_TRAIT]->(:Trait {name: a.name}) THEN a.weight ELSE 0.0 END
     ) AS avoided_penalty

RETURN rp, -1 * avoided_penalty AS avoided_score
ORDER BY avoided_score DESC
```

## Combined Hard and Soft Constraints

```cypher
// Apply hard constraints (filter), then soft constraints (weigh)
MATCH (rp:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(rp)
  // Hard constraints
  AND ALL(t IN $required_traits WHERE (rp)-[:HAS_TRAIT]->(:Trait {name: t}))
  AND NONE(t IN $forbidden_traits WHERE (rp)-[:HAS_TRAIT]->(:Trait {name: t}))

// Soft constraints
WITH rp,
     reduce(s = 0.0, p IN $preferred_traits |
       s + CASE WHEN (rp)-[:HAS_TRAIT]->(:Trait {name: p.name}) THEN p.weight ELSE 0 END) -
     reduce(s = 0.0, a IN $avoided_traits |
       s + CASE WHEN (rp)-[:HAS_TRAIT]->(:Trait {name: a.name}) THEN a.weight ELSE 0 END)
     AS trait_affinity_score

RETURN rp, trait_affinity_score
ORDER BY trait_affinity_score DESC
```

## Root Provider Trait Check

For nested providers, check traits on root:

```cypher
// Find root and check its traits
MATCH (rp:ResourceProvider {uuid: $uuid})
MATCH path = (root:ResourceProvider)-[:PARENT_OF*0..]->(rp)
WHERE NOT ()-[:PARENT_OF]->(root)
  AND ALL(t IN $required_traits WHERE (root)-[:HAS_TRAIT]->(:Trait {name: t}))
RETURN root
```
