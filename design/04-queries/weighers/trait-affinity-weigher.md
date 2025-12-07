---
title: Trait Affinity Weigher
description: Preferred/avoided trait scoring for soft constraints
keywords: [trait-weigher, soft-affinity, preferred-score, avoided-penalty]
related:
  - 02-patterns/soft-constraints.md
  - 03-constraints/trait-constraints.md
implements:
  - "TraitAffinityWeigher"
  - "Preferred traits"
  - "Avoided traits"
section: queries/weighers
---

# Trait Affinity Weigher

Weight hosts based on preferred/avoided traits. This is the soft constraint equivalent of required/forbidden trait filtering.

## Configuration Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `$preferred_traits` | List | `[{name, weight}]` for preferred traits |
| `$avoided_traits` | List | `[{name, weight}]` for avoided traits |
| `$trait_weight_multiplier` | Float | Overall multiplier for trait-based scoring |

## Full TraitAffinityWeigher

```cypher
// TraitAffinityWeigher - Score hosts based on preferred/avoided traits
// Preferred traits give positive scores, avoided traits give negative scores

MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// Calculate score for preferred traits (bonus for having them)
WITH host,
     reduce(preferred = 0.0, p IN $preferred_traits |
       preferred + CASE WHEN (host)-[:HAS_TRAIT]->(:Trait {name: p.name}) 
                        THEN COALESCE(p.weight, 1.0) 
                        ELSE 0.0 END
     ) AS preferred_score

// Calculate penalty for avoided traits (penalty for having them)
WITH host, preferred_score,
     reduce(avoided = 0.0, a IN $avoided_traits |
       avoided + CASE WHEN (host)-[:HAS_TRAIT]->(:Trait {name: a.name}) 
                      THEN COALESCE(a.weight, 1.0) 
                      ELSE 0.0 END
     ) AS avoided_penalty

// Combined score: preferred bonus minus avoided penalty
WITH host, preferred_score, avoided_penalty,
     (preferred_score - avoided_penalty) AS raw_trait_score

// Normalize across all hosts for fair weighing
WITH collect({host: host, raw_score: raw_trait_score, 
              preferred: preferred_score, avoided: avoided_penalty}) AS all_hosts
WITH all_hosts,
     reduce(min_s = all_hosts[0].raw_score, h IN all_hosts | 
            CASE WHEN h.raw_score < min_s THEN h.raw_score ELSE min_s END) AS min_score,
     reduce(max_s = all_hosts[0].raw_score, h IN all_hosts | 
            CASE WHEN h.raw_score > max_s THEN h.raw_score ELSE max_s END) AS max_score

UNWIND all_hosts AS h
WITH h.host AS host, h.raw_score AS raw_score, 
     h.preferred AS preferred_score, h.avoided AS avoided_penalty,
     CASE WHEN max_score = min_score THEN 0.5
          ELSE toFloat(h.raw_score - min_score) / (max_score - min_score)
     END AS normalized_score

RETURN host, preferred_score, avoided_penalty, raw_score,
       normalized_score * $trait_weight_multiplier AS trait_affinity_weight
ORDER BY trait_affinity_weight DESC
```

## Simple Version (Without Normalization)

```cypher
// Simple trait affinity weigher - direct score calculation
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// Count matching traits with weights
WITH host,
     size([p IN $preferred_traits WHERE (host)-[:HAS_TRAIT]->(:Trait {name: p.name})]) AS preferred_count,
     size([a IN $avoided_traits WHERE (host)-[:HAS_TRAIT]->(:Trait {name: a.name})]) AS avoided_count

// Simple scoring: +1 per preferred, -1 per avoided
RETURN host, preferred_count, avoided_count,
       (preferred_count - avoided_count) * $trait_weight_multiplier AS trait_weight
ORDER BY trait_weight DESC
```

## Per-Aggregate Weight Multipliers

```cypher
// Support per-aggregate trait_weight_multiplier override
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

// Get aggregate-level multiplier override
OPTIONAL MATCH (host)-[:MEMBER_OF]->(agg:Aggregate)
WHERE agg.trait_weight_multiplier IS NOT NULL
WITH host, collect(agg.trait_weight_multiplier) AS agg_multipliers

// Use minimum aggregate multiplier, fall back to global
WITH host, 
     CASE WHEN size(agg_multipliers) > 0 
          THEN reduce(m = agg_multipliers[0], x IN agg_multipliers | 
                      CASE WHEN x < m THEN x ELSE m END)
          ELSE $trait_weight_multiplier 
     END AS effective_multiplier

// Calculate trait scores
WITH host, effective_multiplier,
     reduce(score = 0.0, p IN $preferred_traits |
       score + CASE WHEN (host)-[:HAS_TRAIT]->(:Trait {name: p.name}) THEN p.weight ELSE 0 END
     ) - reduce(penalty = 0.0, a IN $avoided_traits |
       penalty + CASE WHEN (host)-[:HAS_TRAIT]->(:Trait {name: a.name}) THEN a.weight ELSE 0 END
     ) AS raw_trait_score

RETURN host, raw_trait_score * effective_multiplier AS trait_affinity_weight
ORDER BY trait_affinity_weight DESC
```

## Flavor-Based Trait Affinity

Extract soft trait constraints from flavor and apply weighing.

```cypher
// Extract soft trait constraints from flavor
MATCH (flavor:Flavor {uuid: $flavor_uuid})
OPTIONAL MATCH (flavor)-[req:REQUIRES_TRAIT]->(trait:Trait)
WHERE req.constraint IN ['preferred', 'avoided']

WITH collect({
  name: trait.name, 
  constraint: req.constraint, 
  weight: COALESCE(req.weight, 1.0)
}) AS soft_traits

WITH [t IN soft_traits WHERE t.constraint = 'preferred'] AS preferred,
     [t IN soft_traits WHERE t.constraint = 'avoided'] AS avoided

// Apply to candidate hosts
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

WITH host, preferred, avoided,
     reduce(score = 0.0, p IN preferred |
       score + CASE WHEN (host)-[:HAS_TRAIT]->(:Trait {name: p.name}) THEN p.weight ELSE 0 END
     ) AS preferred_score,
     reduce(penalty = 0.0, a IN avoided |
       penalty + CASE WHEN (host)-[:HAS_TRAIT]->(:Trait {name: a.name}) THEN a.weight ELSE 0 END
     ) AS avoided_penalty

RETURN host, preferred_score, avoided_penalty,
       (preferred_score - avoided_penalty) * $trait_weight_multiplier AS trait_affinity_weight
ORDER BY trait_affinity_weight DESC
```

## Use Cases

| Trait Configuration | Use Case |
|---------------------|----------|
| `trait:STORAGE_DISK_SSD=preferred:2.0` | Prefer SSD storage for I/O-intensive workloads |
| `trait:CUSTOM_MAINTENANCE=avoided:5.0` | Avoid hosts in maintenance window |
| `trait:HW_CPU_X86_AVX512F=preferred:1.0` | Prefer newer hardware features |
| `trait:CUSTOM_HIGH_LOAD=avoided:3.0` | Avoid heavily loaded hosts |

