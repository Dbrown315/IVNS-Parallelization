[![GitHub license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

# IVNS: parallel ECU and CAN simulation

The In-Vehicle Network Simulator (IVNS) models automotive network timing and
security protocols, including LWA/LASAN, TESLA, and TLS. This branch adds a
parameterized headless LWA, TESLA, and TLS scenarios that run **ECU protocol processing and CAN
bus events concurrently across MPI ranks**, using mpi4py and local SerializableSimpy
CAN kernels.

The parallel entry points are [`main_lwa_param.py`](main_lwa_param.py),
[`main_tesla_param.py`](main_tesla_param.py), and [`main_tls_param.py`](main_tls_param.py).
The original fixed preset and the earlier CAN-only RPC backend remain available
for comparison; they use different execution arrangements described below.

## Quick start

For Windows benchmarking, install **64-bit Python 3.11** and the **Microsoft
MS-MPI runtime**. Use the same interpreter and MPI installation for every run.
The following commands use PowerShell and call the virtual environment directly,
so activation is unnecessary:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-mpi.txt
$env:PYTHONUTF8 = '1'
mpiexec -n 4 .\.venv\Scripts\python.exe main_lwa_param.py --ecus 24 --buses 4 --duration 200
```

Run the new TESLA/TLS versions of `TestSimulation/main_tesla_preset.py` and
`TestSimulation/main_tls_preset.py` with:

```powershell
mpiexec -n 4 .\.venv\Scripts\python.exe main_tesla_param.py --ecus 12 --buses 4
mpiexec -n 4 .\.venv\Scripts\python.exe main_tls_param.py --ecus 12 --buses 4
```

TESLA/TLS use **independent bus-local rings**, with at least two ECUs per bus,
and no central security module or gateways. Their original protocol models rely
on process-wide peer coordination; every peer in a session therefore stays with
its bus on one rank. LWA retains its cross-bus ring and gateway chain. See the
[protocol parameters and workload differences](docs/protocol-scenarios.md).

For LWA, `--ecus` counts regular secure ECUs. The scenario adds one security module and
one gateway between each adjacent pair of buses. ECUs are spread round-robin
across a chain of buses; each ECU sends to the next ECU in a ring. Every regular
ECU authenticates through the LWA protocol.

The default run uses 6 ECUs, 3 buses, and 200 simulated seconds. Change send
interval, start time, gateway delay, seed, and output directory at launch:

```powershell
.\.venv\Scripts\python.exe main_lwa_param.py --help
mpiexec -n 4 .\.venv\Scripts\python.exe main_lwa_param.py --ecus 12 --buses 4 --interval 0.25 --output-dir "benchmark-results\LWA example"
```

LWA requires `2 <= ecus <= 1792` and `1 <= buses <= ecus`; TESLA/TLS require
at least two ECUs per bus (`buses <= floor(ecus/2)`). The identifier bound is
not a validated model-capacity claim. See the [parameter and architecture guide](docs/lwa-param.md)
for defaults, constraints, and authentication warmup considerations.

## What runs in parallel

Each active rank owns one or more buses **and the ECU processes attached to them**.
Rank 0 also computes and, for LWA, owns the security module on `CAN_0`. The number of
active ranks is `min(MPI ranks, buses)`; excess ranks do not join simulation exchanges.

```mermaid
flowchart LR
    A[Rank 0: local ECUs + owned CAN buses + LWA security]
    B[Rank 1: local ECUs + owned CAN buses]
    C[Other active ranks: local ECUs + owned CAN buses]
    A <-->|Timestamped gateway frame batches| B
    B <-->|Timestamped gateway frame batches| C
```

- ECU application, authentication, authorization, and communication-layer
  generators execute locally on their owner rank. They are not sent through MPI.
- Each owned `MPICANBus` calls a local `CANService` and SerializableSimpy kernel
  for arbitration and transmission timing. There are no per-frame CAN RPC round trips.
- Gateway filters select forwarding directions. Detached frame/payload snapshots
  cross ranks with absolute arrival times and enter the target gateway port's
  data-link transmit buffer, where they still contend for the destination bus.
- Ranks process safe time windows concurrently, then exchange gateway batches.
  Positive gateway delay supplies lookahead; the default window is half that
  delay, and `--sync-window` must be positive and no greater than the delay.
  Arrival times are preserved rather than rounded to window boundaries.
- TESLA/TLS have no cross-bus links, so their owned protocol cohorts run to the
  horizon concurrently without intermediate gateway exchanges.

Configuration and PKI setup are currently replicated on active ranks, but only
owned ECU/bus processes are activated. Rank-local CSVs and logs are written under
`TestSimulation/logs/param/rank-0000` for LWA, or the corresponding
`tesla-param` / `tls-param` directory; rank 0 merges CSVs and writes
`summary.json` at the output root. Use separate output directories for concurrent jobs.

See [ECU/CAN implementation and mode comparison](docs/canbus-mpi.md) and the
[detailed ownership, synchronization, and output guide](docs/lwa-param.md).

## Choose an execution mode

| Entry point | ECU and CAN execution | Purpose |
| --- | --- | --- |
| `main_lwa_param.py` (default `--execution partitioned`) | Owned ECU processes and local CAN kernels on every active rank | Concurrent parameterized LWA simulation; supports a one-rank baseline |
| `main_tesla_param.py`, `main_tls_param.py` | Independent bus-local TESLA/TLS peer cohorts on their owner ranks, using local CAN kernels | Parameterized versions of the original presets; supports one-rank baselines |
| `main_lwa_param.py --execution rpc` | All ECU processes on rank 0; blocking CAN requests to other ranks | Legacy CAN-only migration/comparison mode; needs at least two ranks |
| `run_mpi_headless.py` | Fixed original LWA preset using CAN-only RPC | Earlier fixed-topology MPI scenario; needs at least two ranks |
| `run_headless.py` | Original fixed preset in a single SimPy process | Historical serial scenario; needs only `requirements.txt` |

A one-rank run of the **same generated workload** is the appropriate baseline
for partitioned speedup measurements:

```powershell
mpiexec -n 1 .\.venv\Scripts\python.exe main_lwa_param.py --ecus 24 --buses 4 --duration 200 --output-dir benchmark-results/one-rank
```

The fixed preset has different topology/traffic details and is not an equivalent
baseline for that command. To run it independently:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run_headless.py
```

## Scaling and current limits

Measured full-launcher speedups on four ranks included **1.84x** for a 12-ECU,
four-bus workload and **2.22x** with denser application traffic, relative to
each workload's own one-rank run. These are medians of three launches on a shared
cloud host, not guaranteed gains. See [measurements, raw samples, and caveats](docs/partitioned-scaling.md).

More ranks help only while there are enough buses, CPU capacity, and balanced
work. More ECUs add useful work but also authentication, congestion, and traffic.
More buses create partitions but add gateways and forwarding hops. Shorter
gateway delays/windows require more synchronization; a single bus cannot gain
partition concurrency from extra ranks. Longer runs can amortize startup, while
larger exports increase serial output costs.

Replicated configuration setup, the central security module, collective waiting,
and final merging/digest generation limit scaling. ECU generators remain
nonserializable, so whole-simulation checkpoint/restart is unavailable; the CAN
kernel can be serialized independently. Zero-delay gateways require RPC mode.
The scripts and benchmark driver use portable paths, UTF-8 CSVs, and subprocess
argument lists for Windows. Use the [Windows preflight](docs/windows-benchmarking.md)
and [Windows CI job](.github/workflows/windows-benchmark-smoke.yml) to validate the
actual Python/MS-MPI combination before timing runs. Historical cloud timings are
not Windows benchmark results. Multi-node performance remains unverified. Existing
`p_sec_mod_cert_size` configuration messages remain in the legacy model.

[Native Windows/MS-MPI CI passed](https://github.com/Dbrown315/IVNS-Parallelization/actions/runs/45886778328),
including TESLA/TLS traffic checks and smoke benchmarks for all three protocols.
The [Windows guide](docs/windows-benchmarking.md) records the validated code and scope.

## Verification and documentation

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_windows.ps1
.\.venv\Scripts\python.exe benchmarks/benchmark_protocols.py --protocol lwa --suite factors --repeats 3 --output benchmark-results/lwa.json
.\.venv\Scripts\python.exe benchmarks/benchmark_protocols.py --protocol tesla --suite strong --repeats 3 --output benchmark-results/tesla.json
.\.venv\Scripts\python.exe benchmarks/benchmark_protocols.py --protocol tls --suite strong --repeats 3 --output benchmark-results/tls.json
```

The MPI tests check real ECU authentication and application reception, and compare
semantic event traces across rank counts, safe windows, and a monolithic reference
using the same snapshot communication model. They do not establish full-state
equivalence to legacy shared-object gateways. Benchmark sampling and limitations
are documented alongside the measurements.

- [ECU/CAN architecture and execution-mode comparison](docs/canbus-mpi.md)
- [Launch parameters, synchronization, results, and scaling factors](docs/lwa-param.md)
- [Measured scaling and reproducible benchmarks](docs/partitioned-scaling.md)
- [TESLA/TLS parameterized scenarios](docs/protocol-scenarios.md)
- [Windows installation, preflight, and benchmarking](docs/windows-benchmarking.md)
- [Historical serial baseline evidence](docs/baseline-evidence.md)

## Repository and model background

| Path | Contents |
| --- | --- |
| `ECUSimulation/` | ECU layers, security protocols, CAN buses, gateways, configuration, and simulation API |
| `ECUInteraction/` | Original GUI and visualization plugins |
| `TestSimulation/` | Original scenario examples and generated logs |
| `main_lwa_param.py` | Parameterized ECU/CAN parallel launcher |
| `main_tesla_param.py`, `main_tls_param.py` | Parameterized bus-local protocol benchmarks |
| `tests/`, `benchmarks/`, `docs/` | Correctness checks, performance driver, and documentation |

IVNS uses measured cryptographic latencies from
`ECUSimulation/config/data/measurements.db`, together with configuration in
`project.ini`, `timings.ini`, and `can_ids.ini`. ECU layers and protocol models
can be extended through the simulation API. The original project targeted Python
2.7 and a PyQt4 GUI; this branch's headless execution uses Python 3.11 and a
synchronous signal adapter. The original GUI has not been revalidated.

## Attribution and support

Original IVNS design and implementation: **Artur Mrowca**. Upstream source:
[PhilippMundhenk/IVNS](https://github.com/PhilippMundhenk/IVNS). Original history
and [MIT license](LICENSE) are preserved.

The original work was created at TUM CREATE with financial support from the
Singapore National Research Foundation through its Campus for Research
Excellence and Technological Enterprise (CREATE) programme.

Original tutorials: [IVNS wiki](https://github.com/arturmrowca/IVNS/wiki).
