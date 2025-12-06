Tachyon: Real-Time Telemetry aware scheduling for OpenStack

Tachyon is a proposal for a real-time telemetry aware resource scheduler
built with Python. It will leverages Neo4j as the data store for
managing dependencies and relationships as a grpah.

Building on the work done in the Placement service, os-trait and os-resouces-classes
before it tachyon will models forests of resouces provider trees as nodes in
a multi graph Enriched with metadata, ownserhsip, allocations, consumers, and usage.

Each resouce provider node has invetories of standard and custom resouce clasees
fully supporting the rich datamodel of the plsamcenet service including the abiltiy
to assocate tratis with resocues provider, group resouce providers into heracice forming
trees and non heriachical strcures know as aggretes.

Tachyon will facilate the schduling of resocues to worklaod based on many factors such
as telemtiery driven utilzation policies, enabling time aware schduign by levgeraging
Promethus via the ateos service

Tachyon will enable the express of schduiling polices as data to allow customaitation
without code change building on neo4j native expression lanaguage.


# Problem description

The Nova scheduler currently lacks a weigher that can make intelligent
scheduling decisions based on the resource provider tree data available
from OpenStack Placement. While the scheduler can filter hosts based on
resource availability and traits, the existing weighers (RAMWeigher,
DiskWeigher, etc.) operate primarily on a single resource based on data
from the HostState object and do not leverage the detailed provider tree
structure that Placement exposes.
This means that we have to implement a weigher for each resource we care
about instead of having a single weigher that can consider multiple
resources and traits.
Scheduling and workload management in OpenStack is split between several
services. Placement is responsible for inventory management and allocation
tracking. Watcher utilizes monitoring data to detect resource contention.
Blazar provides reservation management. Nova is the final arbiter of resource
allocation and scheduling decisions.
External orchestration systems and higher-level tools (such as Watcher and
other third-party controllers) need a current view of resource availability
and topology on each compute node in order to make scheduling and capacity
decisions.
Today there is no single, semi real-time source in Nova that describes the
schedulable resources of a host, including relationships such as NUMA
topology and the mapping between PCI aliases and the underlying devices or
pools. Some of this information is modeled in Placement, but important pieces
such as NUMA and certain PCI or network devices are either not modeled at
all or are only partially represented.
As a result, external systems typically reconstruct their view of the cloud
by periodically polling Placement and other Nova APIs, or by performing host-
level introspection. These patterns can produce bursts of "list everything"
traffic across all hosts and resources and still leave consumers with stale
or incomplete state.


# Use Cases

See [usecases.md](usecases.md) for the complete list of use cases that Tachyon
must support, including:

- Tachyon-specific use cases for telemetry-aware and graph-based scheduling
- Nova scheduling capabilities including resource allocation, traits, aggregates,
  server groups, NUMA topology, CPU management, memory management, PCI passthrough,
  SR-IOV, vGPUs, and network-aware scheduling
- Scheduler prefilters, filters, and weighers
- Instance lifecycle and move operations
- Cells scheduling considerations
- Placement query features
