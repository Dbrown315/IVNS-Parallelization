# Parameterized TESLA and TLS presets

`main_tesla_param.py` and `main_tls_param.py` are new headless launchers based on
`TestSimulation/main_tesla_preset.py` and `TestSimulation/main_tls_preset.py`.
They retain those protocol models and timing-library choices, while generating
the ECU counts, bus counts, streams, monitoring, and MPI ownership at launch.
The original GUI-oriented presets remain unchanged.

For Windows setup, use the [MS-MPI/Python preflight](windows-benchmarking.md).

```powershell
mpiexec -n 4 .\.venv\Scripts\python.exe main_tesla_param.py --ecus 12 --buses 4
mpiexec -n 4 .\.venv\Scripts\python.exe main_tls_param.py --ecus 12 --buses 4
```

## Workload and parallelism

ECUs are assigned round-robin to independent CAN buses. Each bus has a local
sender/receiver ring: its last ECU sends to its first. One rank owns a bus and
all the protocol peers attached to it. `min(ranks, buses)` ranks compute;
rank 0 participates, and surplus ranks are idle. Every bus uses `MPICANBus`
with a local SerializableSimpy kernel.

Unlike the LWA scenario, these scenarios contain **no central security module
and no gateways**. TESLA and TLS currently coordinate peers using process-wide
stores/caches in the legacy models. Keeping peers in one bus cohort preserves
that coordination instead of pretending it is distributed messaging. Remote
gateway sessions would require separate protocol-state/notification changes.
The bus-local layout is explicit in `summary.json` as `traffic=bus-local-ring`.

Independent bus cohorts have no remote effects during the simulation, so they
run concurrently to the horizon without intermediate gateway exchanges. Results
are still exported per rank and merged by rank 0. More buses can create more
independent work, but more ranks than buses add no computation parallelism.

The generated rings differ from the originals' fixed multicast groups and
asymmetric senders. Compare a generated workload to its own one-rank execution,
not to the original preset or to LWA's cross-bus workload.

## Parameters

| Option | TESLA default | TLS default | Meaning |
| --- | ---: | ---: | --- |
| `--ecus` | 6 | 6 | Total protocol ECUs |
| `--buses` | 3 | 3 | Independent buses, with at least two ECUs each |
| `--duration` | 500 | 500 | Simulated seconds |
| `--start` | 260 | 20 | First application send attempt |
| `--interval` | 0.1 | 0.5 | Send interval per ECU |
| `--payload-bytes` | 50 | 20 | Simulated payload size |
| `--seed` | 1729 | 1729 | Setup and per-ECU interval-jitter seed |
| `--output-dir` | `TestSimulation/logs/tesla-param` | `TestSimulation/logs/tls-param` | Result directory |
| `--key-chain-length` | 10000 | N/A | TESLA key-chain size |
| `--disclosure-delay` | 1 | N/A | TESLA delayed key disclosure, in send intervals |

Require `2 <= ecus <= 1792` and `1 <= buses <= floor(ecus/2)`. Thus every
bus has at least two real protocol peers. Application stream IDs start at
`0x100`, one per sender. Times must be finite, duration/interval positive,
and `0 <= start < duration`.

TESLA's stream start and interval exactly match the sending action. The launcher
checks that the key chain covers at least
`ceil(duration/interval) + disclosure_delay + 2` entries. The presets' dummy
PRFs, key reuse, and abstract timing mechanisms are retained; these are IVNS
protocol-model benchmarks, not measurements of a production cryptographic stack.
TLS explicitly uses the AES record-layer settings from `main_tls_preset.py`,
instead of the older preset class's default MAC setting.

Short test runs can use:

```powershell
mpiexec -n 2 .\.venv\Scripts\python.exe main_tesla_param.py --ecus 6 --buses 2 --duration 30 --start 10 --interval 0.5 --key-chain-length 128
mpiexec -n 2 .\.venv\Scripts\python.exe main_tls_param.py --ecus 6 --buses 2 --duration 30 --start 10 --interval 0.5
```

## Results and correctness checks

The output directory contains merged `buffer.csv`, `can_bus.csv`,
`checkpoints.csv`, `summary.json`, and rank-local subdirectories. Summaries name
the protocol, traffic layout, actual bus/ECU ownership, scheduled transmissions,
and timing data. TESLA also records key-chain/disclosure settings.

For TESLA, `CP_RETURNED_AUTHENTICATED_SIMPLE_MESSAGE` indicates authenticated
application reception. For TLS, check `CP_RECEIVE_SIMPLE_MESSAGE` and handshake
tags `CP_CLIENT_AUTHENTICATED` / `CP_SERVER_AUTHENTICATED`. Reaching the horizon
alone does not establish successful protocol traffic.

```powershell
.\.venv\Scripts\python.exe tests/protocol_param_smoke.py
```

The smoke test requires application reception at every ECU and equal semantic
event digests for the same six-ECU/two-bus model on 1, 2, and 3 ranks. It also
exercises Unicode/spaced output paths and surplus-rank handling. Opaque key/nonce
values are excluded from the digest, as in the LWA checks.

The common [benchmark driver](../benchmarks/benchmark_protocols.py) accepts
`--protocol lwa`, `--protocol tesla`, and `--protocol tls`. It verifies reception
before recording a timing and rejects semantic trace differences across ranks.
The gateway-delay factor applies only to LWA and is omitted for TESLA/TLS.
