# ECU and CAN parallel implementation

The default `main_lwa_param.py` mode distributes **ECU protocol processing together
with CAN bus execution**. This guide covers the current design and distinguishes
it from the retained synchronous CAN-only RPC backend.

The new `main_tesla_param.py` and `main_tls_param.py` launch independent bus-local
protocol cohorts with the same local CAN kernels. Their process-wide peer state
stays within its owner rank; they do not claim cross-rank gateway sessions.
See [protocol scenarios](protocol-scenarios.md) and the
[Windows benchmarking guide](windows-benchmarking.md).

```sh
mpiexec -n 4 python main_lwa_param.py --ecus 24 --buses 4
```

Install `requirements-mpi.txt` in Python 3.11 and use a compatible MPI runtime.
The [launch and synchronization guide](lwa-param.md) contains every CLI option.

## Default: concurrent ECU/CAN partitions

A bus and its attached regular ECUs are assigned to one active MPI rank.
`active_ranks = min(bus_count, MPI_rank_count)`, and bus ownership follows
`bus_index % active_ranks`. Rank 0 participates in computation and owns the
security module on `CAN_0`; there is no dedicated coordinator rank.

| Component | Location and execution |
| --- | --- |
| Regular ECU application and protocol stacks | Existing SimPy generators run on the rank owning their bus |
| Security module | Runs on the owner of `CAN_0`, currently rank 0 |
| `MPICANBus` | Runs with its local ECU processes, retaining CAN arbitration, timing, buffering, and completion interfaces |
| `CANService` / `SerializableCAN` | Local callback-based SerializableSimpy kernel; no per-frame MPI RPC |
| Gateway forwarding | Filtered frame/payload snapshots, with timestamps, cross the partition boundary |
| Monitoring | Owned components export rank-local CSVs; rank 0 merges outputs and writes the summary |

Every active rank currently builds a complete configuration/PKI replica so the
legacy key registries, certificates, stream filters, and security registration
agree. Only owned ECU and bus processes are activated. ECU generators remain
local and nonserializable; they do not need to cross MPI for parallel execution.
This preserves the existing ECU stacks while avoiding a complete callback rewrite.

The generated workload places ECUs round-robin on a chain of buses. Each ECU
authenticates, then sends application data to the next ECU in a ring. Increasing
`--ecus` changes both protocol work and offered traffic, not just a topology label.

## Timestamped gateway exchange

Gateway filters retain their forwarding decisions. An accepted frame is
snapshotted without its SimPy environment and assigned an absolute arrival time:

`arrival = source_bus_receive_time + gateway_delay`.

The destination rank inserts it into the target gateway port's existing
data-link transmit buffer at that time. The frame still arbitrates for the
target bus and passes through its normal controller/transceiver path.

Ranks advance concurrently through half-open windows and exchange batches with
MPI `alltoall` at each boundary. Positive gateway delay provides conservative
lookahead: the window cannot exceed that delay. The default is delay/2.
Delivery timestamps are preserved; events are not rounded to window boundaries.
Colocated gateway edges use the same snapshot path, keeping semantics independent
of rank placement. Stable batch ordering and explicit arrival priority define
equal-time behavior; late or misrouted frames fail the run.

The new snapshot model intentionally removes mutable in-flight object aliasing.
Exact-tie behavior and shared-object mutation therefore need not reproduce the
legacy gateway bit for bit. See [causality and validation details](lwa-param.md)
for assumptions and reference-trace checks.

## Shared CAN implementation

`MPICANBus` retains `StdCANBus` gathering/arbitration delays, monitoring, receiver
filters, gateway-loop suppression, local delivery, and `sync_send` completion.
`_transmission_delay()` shares the legacy cache and timing calculation between
the adapters, including the minimum one-microsecond delay for nonpositive totals.
The legacy global data-rate and cache-by-frame-length semantics remain.

`SerializableCAN` owns a SerializableSimpy environment, pending transmission,
completion time, and transmission counter. Pending callbacks can be pickled
independently of MPI handles. SerializableSimpy 0.0.3 excludes callbacks exactly
at `run(until)`, so the kernel steps to the next representable float and retains
the actual callback timestamp. It uses `SerializableSimpy.core.Environment`,
rather than treating `MPIGlobalEnv` as a replacement for IVNS's generator model.

Serializing this kernel is not a checkpoint of the surrounding ECU generators,
SimPy stores, transceiver buffers, or complete distributed simulation.

## Legacy: synchronous CAN-only RPC

The earlier mode is retained explicitly:

```sh
mpiexec -n 4 python main_lwa_param.py --execution rpc --ecus 24 --buses 4
```

In **RPC mode only**, all ECU/security processes, gateway routing, payloads and
monitoring stay on rank 0. Other ranks service ordered identifier lists and
transmission metadata through `MPICANRuntime`. Rank 0 blocks for each reply
and maps results back to local messages. Requests are serialized, so this mode
does not provide concurrent ECU processing or overlapping CAN computation.

`run_mpi_headless.py` also retains RPC mode for the original fixed 200-second,
three-bus preset. It is distinct from the parameterized generated ring:

```sh
mpiexec -n 4 python run_mpi_headless.py
```

RPC mode requires at least two ranks and can retain zero-delay gateway behavior.
Its service setup installs `MPICANRuntime` on rank 0 and `serve` on the workers.
Default partitioned execution instead installs a local `CANService` on each
active rank; `MPICANBus` uses that service without remote arbitration calls.
Do not substitute this bus for `RapidCANBus`, which has a different data-link interface.

The old fixed-preset RPC validation compared serial and MPI CSV outputs after
normalizing object addresses. That evidence concerns the legacy mode, not the
new partitioned communication semantics or its speedup baseline.

## Scaling, validation, and remaining work

Useful concurrency is bounded by bus count, active ranks, available CPUs, and
partition balance. More ECUs can amortize exchange overhead, but add security
work and congestion. More buses create partitions while adding gateway hops.
Shorter lookahead requires more exchanges. Configuration replication, centralized
security, collective waits, and output merging/digest generation limit speedup.

The [scaling report](partitioned-scaling.md) includes measured full-launcher and
loop speedups, raw samples, and noisy cases. The [detailed guide](lwa-param.md)
explains how to compare each workload against its own one-rank baseline.

```sh
python -m unittest discover -s tests -v
python tests/param_lwa_smoke.py
python tests/partitioned_mpi_smoke.py
```

Topology tests require every ECU to authenticate and receive application data.
Reference tests compare semantic event times, component IDs, tags, sizes and
stream/CAN IDs across rank counts and synchronization windows, excluding opaque
identifiers. They use an immediate-message reference of the snapshot model.

Whole-partition checkpoint/restart, rank-loss recovery, dynamic topology changes,
and zero-delay distributed lookahead are not implemented. Validation targets the
generated static protocol scenarios. Windows benchmark machines should run the
provided PowerShell preflight before timing. Partition-aware setup and
neighbor-only exchanges remain opportunities beyond the current replicated
configuration and batched all-to-all design.
