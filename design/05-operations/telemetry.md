---
title: Telemetry Integration
description: Prometheus/Aetos hooks for real-time metrics
keywords: [telemetry, prometheus, metrics, utilization, power-aware]
related:
  - 01-schema/nodes/resource-provider.md
  - 04-queries/weighers/resource-weighers.md
implements:
  - "Real-time telemetry"
  - "Power-aware scheduling"
section: operations
---

# Telemetry Integration

Interfaces for external telemetry systems (Prometheus/Aetos) to inform scheduling decisions.

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Prometheus  │────►│   Tachyon    │────►│    Neo4j     │
│   Server     │     │  Scheduler   │     │  (Graph)     │
└──────────────┘     └──────────────┘     └──────────────┘
       │                    │
       │                    │
       ▼                    ▼
┌──────────────┐     ┌──────────────┐
│ node_exporter│     │  Telemetry   │
│  (per host)  │     │   Plugin     │
└──────────────┘     └──────────────┘
```

## MetricEndpoint Node

```
:MetricEndpoint
  uuid:         String!     # Unique identifier
  name:         String!     # Human-readable name
  endpoint_url: String!     # Prometheus/metrics endpoint URL
  type:         String!     # 'prometheus', 'pushgateway', 'aetos'
  scrape_interval: Integer  # Scrape interval in seconds
  enabled:      Boolean!    # Whether endpoint is active
  created_at:   DateTime!
  updated_at:   DateTime!
```

```cypher
CREATE (me:MetricEndpoint {
  uuid: randomUUID(),
  name: 'prometheus-main',
  endpoint_url: 'http://prometheus:9090',
  type: 'prometheus',
  scrape_interval: 15,
  enabled: true,
  created_at: datetime(),
  updated_at: datetime()
})
```

## Link Provider to Metrics

```cypher
// Link compute node to Prometheus endpoint
MATCH (rp:ResourceProvider {name: 'compute-001'})
MATCH (me:MetricEndpoint {name: 'prometheus-main'})
CREATE (rp)-[:HAS_METRIC_SOURCE {
  labels: {instance: 'compute-001:9100', job: 'node'},
  job: 'node'
}]->(me)
```

## Utilization-Based Weigher

```cypher
// Weight hosts by current resource utilization
// Assumes telemetry plugin has enriched hosts with _cpu_utilization, _memory_utilization

MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)
  AND host.disabled <> true

WITH host,
     COALESCE(host._cpu_utilization, 50.0) AS cpu_util,
     COALESCE(host._memory_utilization, 50.0) AS mem_util

// Prefer hosts with lower utilization
WITH host, (100 - cpu_util) * 0.5 + (100 - mem_util) * 0.5 AS available_capacity

RETURN host, cpu_util, mem_util, available_capacity
ORDER BY available_capacity DESC
```

## Threshold-Based Filtering

```cypher
// Filter out overloaded hosts
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)
  AND host.disabled <> true
  AND COALESCE(host._cpu_utilization, 0) < $cpu_threshold
  AND COALESCE(host._memory_utilization, 0) < $memory_threshold

RETURN host
```

## Power-Aware Scheduling

```cypher
// Prefer hosts with lower power consumption
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)

WITH host,
     COALESCE(host._power_consumption, 0) AS power_watts,
     COALESCE(host._temperature, 25) AS temp_celsius

// Penalize high power consumption and temperature
WITH host, power_watts, temp_celsius,
     CASE
       WHEN temp_celsius > 80 THEN -1000  // Critical temperature
       WHEN temp_celsius > 70 THEN -100   // High temperature
       ELSE 0
     END AS temp_penalty,
     -1 * (power_watts / 1000.0) AS power_penalty

RETURN host, power_watts, temp_celsius,
       (temp_penalty + power_penalty) * $power_weight_multiplier AS power_weight
ORDER BY power_weight DESC
```

## Threshold Alerts

```cypher
// Create threshold alert
CREATE (alert:ThresholdAlert {
  uuid: randomUUID(),
  provider_uuid: $provider_uuid,
  metric: 'cpu_utilization',
  threshold: 90.0,
  current_value: 95.5,
  severity: 'critical',
  acknowledged: false,
  created_at: datetime()
})

// Link to provider
MATCH (rp:ResourceProvider {uuid: $provider_uuid})
CREATE (rp)-[:HAS_ALERT]->(alert)
```

## Query with Active Alerts

```cypher
// Exclude hosts with unacknowledged critical alerts
MATCH (host:ResourceProvider)
WHERE NOT ()-[:PARENT_OF]->(host)
  AND NOT EXISTS {
    MATCH (host)-[:HAS_ALERT]->(alert:ThresholdAlert)
    WHERE alert.severity = 'critical'
      AND alert.acknowledged = false
  }

RETURN host
```

## Standard Metrics

| Metric | Description | Unit |
|--------|-------------|------|
| `node_cpu_seconds_total` | CPU time | seconds |
| `node_memory_MemAvailable_bytes` | Available memory | bytes |
| `node_memory_MemTotal_bytes` | Total memory | bytes |
| `node_disk_io_time_seconds_total` | Disk I/O time | seconds |
| `node_network_receive_bytes_total` | Network RX | bytes |
| `node_network_transmit_bytes_total` | Network TX | bytes |
| `node_load1` | 1-minute load average | - |
| `node_hwmon_temp_celsius` | Hardware temperature | Celsius |
| `node_power_supply_power_watt` | Power consumption | Watts |

## Telemetry Plugin Interface

```python
class TelemetryPlugin(abc.ABC):
    """Abstract interface for telemetry data providers."""
    
    @abc.abstractmethod
    def query_metrics(
        self,
        provider_uuids: List[str],
        metric_names: List[str],
        time_range: Optional[Tuple[datetime, datetime]] = None
    ) -> Dict[str, Dict[str, float]]:
        """Query metrics for providers."""
        pass
    
    @abc.abstractmethod
    def get_utilization(self, provider_uuid: str) -> Dict[str, float]:
        """Get current utilization metrics for a provider."""
        pass
    
    @abc.abstractmethod
    def register_callback(
        self,
        event_type: str,
        handler: Callable[[str, Dict], None]
    ) -> str:
        """Register callback for telemetry events."""
        pass
```

