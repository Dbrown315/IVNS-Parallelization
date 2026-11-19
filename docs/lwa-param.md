# Launch a configurable LWA scenario

`main_lwa_param.py` is a headless, MPI entry point on the
`codex/canbus-serializable-mpi` branch. It always constructs `MPICANBus` objects,
using the existing SerializableSimpy CAN worker implementation. It does not
select the original `StdCANBus` backend.

From the repository root, using Python 3.11 and an installed MPI runtime:

```sh
python -m pip install -r requirements-mpi.txt
mpiexec -n 4 python main_lwa_param.py --ecus 12 --buses 3
```

For a separate result directory and a longer authentication warmup:

```sh
mpiexec -n 3 python main_lwa_param.py --ecus 24 --buses 6 --duration 300 --start 60 --interval 0.5 --output-dir TestSimulation/logs/24-ecus
```

`python main_lwa_param.py --help` lists the options without requiring MPI
initialization. Actual simulation needs at least two ranks: rank 0 runs IVNS;
the remaining ranks serve CAN requests. The rank count is independent of the
number of buses. One worker can own multiple buses, and surplus workers can
remain idle.

## Parameters and topology

| Option | Default | Meaning |
| --- | ---: | --- |
| `--ecus` | 6 | Total regular secure ECUs, excluding security module and gateways |
| `--buses` | 3 | Total CAN buses |
| `--duration` | 200 | Simulation duration, in simulated seconds |
| `--start` | 10 | First send attempt by each ECU, in simulated seconds |
| `--interval` | 0.5 | Send interval per ECU, in simulated seconds |
| `--gateway-delay` | 2 | Forwarding delay per gateway, in simulated seconds |
| `--seed` | 1729 | Python random seed for jitter; UUIDs still vary |
| `--output-dir` | `TestSimulation/logs/param` | Result directory; reruns overwrite its results |

ECUs are assigned round-robin to buses, so bus populations differ by at most
one. Buses form a chain, with one gateway between each adjacent pair. One
security module sits on `CAN_0`. For `E` regular ECUs and `B` buses, the scenario
contains `E + 1 + (B - 1) = E + B` ECU-like objects, counting the security module
and gateways. With one bus there are no gateways.

Every regular ECU authenticates through the LWA protocol. Each sends a 50-byte
application payload to the next ECU in a ring; the last sends to `ECU_0`.
Streams have unique CAN identifiers starting at `0x100`. Certificates,
authorized streams, database timing functions, and gateway filters are
generated from the requested topology. This is a new generated workload; its
defaults do not reproduce `main_lwa_preset.py`'s asymmetric sending actions or
its pre-authenticated sender.

Inputs require `2 <= E <= 1792` and `1 <= B <= E`. This keeps every bus populated
and reserves one unique standard 11-bit CAN identifier per sender. Configured
authentication identifiers must not overlap that range. The maximum is an
identifier bound, not a claim that such a large model has been validated.
Times must be finite, duration and interval positive, gateway delay nonnegative,
and start within the simulation horizon.

## Results and checking a run

Only rank 0 writes `api.log`, `buffer.csv`, `can_bus.csv`, `checkpoints.csv`,
and `summary.json` to the chosen directory. Use a different directory for
concurrent runs. The summary includes the requested topology, stream map,
actual bus-to-worker assignments, worker count used, final simulated time,
and build/run wall times. The run time includes export; it excludes MPI job
startup and final worker shutdown, so also use an external timer for end-to-end
benchmarks.

The runner checks that all requested buses are `MPICANBus`, that the built bus
count matches, that no worker reported an error, and that simulation time
reached the requested duration. A stale success summary is removed before
setup. IVNS's normal `SystemExit(None)` is handled explicitly; setup exits and
early simulation termination fail the new runner. Worker shutdown runs in a
`finally` block.

Reaching the requested duration does not prove every ECU authenticated or
received data. Inspect checkpoint tags `CP_ECU_DECRYPTED_CONF_MESSAGE` and
`CP_ECU_DECRYPTED_SIMPLE_MESSAGE` by component ID. Authentication and stream
authorization take simulated time, and send attempts can be dropped before
they finish. For larger chains or larger ECU counts, increase `--duration`
and/or `--start`; shorten `--gateway-delay` only when that change fits the model
you want to simulate. Monitoring is sampled, so the last CSV timestamp need
not equal the final simulation time.

## Potential speedup and limitations

**The current MPI backend does not execute CAN requests concurrently.** Rank 0
sends a blocking request, waits for the reply, then continues its SimPy event
loop. SerializableSimpy workers own arbitration and callback-based bus timing
state, while ECU/security generators, payloads, gateway routing, delivery,
and monitoring all remain on rank 0. Assigning buses to different workers
therefore provides state separation, not concurrent computation.

For the present design, a useful approximation is:

`T_MPI ≈ T_serial + number_of_requests × RPC_overhead + MPI_startup`.

The approximation assumes equivalent computational work in the two backends;
serialization, scheduling, and Python implementation differences also matter.
Adding ranks alone offers no computational speedup and will usually slow this
cheap CAN workload. An earlier observation for the original fixed preset was
about 2.02 s serial versus 2.84 s on four ranks (roughly 0.71x speedup, or 40%
more elapsed time). That was a single observation for a different workload,
not a benchmark of this parameterized scenario.

A future design could place each bus and its local ECU callback processes on
one worker and exchange timestamped gateway messages. With concurrent work,
the ideal Amdahl bound is `S(P) <= 1 / ((1-f) + f/P)`, where `f` is the measured
parallelizable fraction and `P` the number of workers. If only 20% of runtime
is parallelizable, four workers can ideally reach only about 1.18x before
communication costs. If 80% becomes parallelizable, the corresponding ideal
bound is 2.5x. Neither percentage has been measured for IVNS here.

Useful scaling would require migrating the generator-based ECU protocol
state to callbacks, supporting asynchronous communication, and enforcing
causality across gateway messages. Partition count is then also bounded by
the number of useful bus/ECU partitions. Load imbalance, the central security
module, cross-bus traffic, and zero-delay paths can reduce that scaling.
The ring's final-to-first stream spans the entire chain, making synchronization
and gateway costs particularly relevant.

Increasing bus count changes network congestion and simulated delivery
latency; that is distinct from reducing wall time for the simulator. Increasing
ECU count here also adds senders and authentication work, so a sweep is a
growing-workload experiment, not a fixed-work strong-scaling benchmark. For
rank-scaling comparisons, hold ECU count, topology, duration, interval,
gateway delay, monitoring, and seed fixed and repeat runs. A serial comparison
must use the same generated workload; the old preset is not that baseline.

Other limits remain: finite buffers can drop traffic under load; the original
timing cache/global-rate semantics remain; only bus-kernel state is
checkpointable; MPI process loss and transport hangs have no recovery protocol.
The existing preset's crypto configuration is retained for timing experiments.

## Validation

```sh
python -m unittest discover -s tests -v
python tests/param_lwa_smoke.py
```

The MPI smoke test launches four real scenarios for 60 simulated seconds each:

| Regular ECUs | CAN buses | MPI ranks | Covered case |
| ---: | ---: | ---: | --- |
| 2 | 1 | 2 | Single bus, no gateways |
| 7 | 3 | 4 | Uneven ECU distribution |
| 8 | 4 | 2 | Multiple buses per worker |
| 2 | 2 | 4 | More workers than buses |

All four completed with every regular ECU authenticated and receiving
application data, correct worker assignments, and no traceback. Existing
`p_sec_mod_cert_size` configuration errors still appear in IVNS's logs.
An additional 12-ECU, three-bus, four-rank run completed 200 simulated seconds,
with all 12 ECUs authenticated and receiving application data.
The tests also cover invalid parameters, topology construction, and the MPI
launcher's legacy-exit/error-handling regression. Validation used Linux,
CPython 3.11.18, Open MPI 5.0.7, and the pinned dependencies; Windows and
multi-node execution remain unverified.
