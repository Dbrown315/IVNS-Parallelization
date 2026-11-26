# Measured ECU/CAN partition scaling

These measurements exercise concurrent ECU application/security/communication
processing and local CAN kernels. They concern the default partitioned mode,
rather than the earlier CAN-only RPC backend. The
[implementation overview](canbus-mpi.md) explains the distinction.

Measured November 26, 2026 on one Linux cloud host, CPython 3.11.18, Open MPI
5.0.7, SerializableSimpy 0.0.3 and mpi4py 4.1.1. CPU affinity exposed five logical
CPUs; the cgroup quota allowed four CPUs of aggregate execution. This was a shared
cloud environment, not an isolated performance lab.

Each row is a median of three launches. Speedup compares the same workload to
its own one-rank partitioned baseline. Full-launcher time includes MPI startup,
replicated setup, simulation, exports, merged CSVs, digest generation and MPI
finalization. Loop speedup compares only synchronized simulation-loop time,
including its communication/waiting; it is not end-to-end speedup.

All repetitions/rank counts for each workload matched its semantic event digest.
The [raw samples and source fingerprint](benchmarks/partitioned-scaling.json)
are preserved, including individual rank compute/wait times. Runs were sequential;
no synthetic CPU work was added.

| Workload | ECUs / buses | Duration | Interval | Gateway delay | Ranks | 1-rank launcher (s) | Launcher (s) | Full speedup | Loop speedup |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| base | 12 / 4 | 60 | 0.25 | 2 | 2 | 7.560 | 4.838 | 1.56x | 1.80x |
| base | 12 / 4 | 60 | 0.25 | 2 | 4 | 7.560 | 4.107 | 1.84x | 2.38x |
| more_ecus | 24 / 4 | 60 | 0.25 | 2 | 4 | 15.561 | 4.312 | 3.61x | 4.14x |
| one_bus | 12 / 1 | 60 | 0.25 | 2 | 4 | 2.679 | 2.942 | 0.91x | 0.87x |
| more_traffic | 12 / 4 | 60 | 0.05 | 2 | 4 | 14.715 | 6.613 | 2.22x | 2.57x |
| short_lookahead | 12 / 4 | 60 | 0.25 | 0.02 | 4 | 4.169 | 3.354 | 1.24x | 1.34x |
| longer_run | 12 / 4 | 120 | 0.25 | 2 | 4 | 7.334 | 4.216 | 1.74x | 2.00x |

The default window was half the gateway delay: 1 simulated second normally,
0.01 for `short_lookahead`. The short-lookahead run therefore used 6,000 exchanges
instead of 60. Its gateway delay also changes the physical workload, so this is
not an isolated synchronization-window experiment.

## Interpretation

- The base workload benefits from two ranks and improves further on four, with
  diminishing returns. The measured 1.84x full-launcher gain is lower than the
  2.38x loop gain because setup, merging and verification remain expensive.
- The denser application workload (`more_traffic`) obtained 2.22x end-to-end
  speedup. This is a useful observed gain from concurrent real ECU/CAN execution.
- A single bus activates only one rank. Four launched ranks were slower: there
  is no additional partition parallelism to offset job overhead.
- Short lookahead reduced the measured gain to 1.24x in its own workload.
- Longer duration did not monotonically improve the observed gain. Workload
  phases, centralized security, output costs, and host variability all matter.

**The 24-ECU measurement is especially noisy.** Its one-rank samples ranged from
7.49 to 17.39 seconds, versus 4.10 to 4.49 seconds on four ranks. The tabulated
3.61x is the ratio of medians, not a reliable capacity estimate. Its apparent
4.14x loop gain on four active ranks must not be interpreted as ideal linear or
superlinear scaling; three samples on a shared host cannot establish that.
Even the more stable cases are observations, not guaranteed speedups.

## Repeat

```sh
python benchmarks/benchmark_lwa.py --suite factors --repeats 3 --output work/scaling.json
```

Use `--suite strong` for only the base workload on 1, 2 and 4 ranks. Repeat on
your target hardware with dedicated CPUs and enough trials to characterize
variation. The driver currently runs each case/rank count in blocks; consider
interleaving or randomizing launch order for a formal performance study.
Changing ECU/bus counts changes work, so never divide timings from different
rows to claim parallel speedup. Architecture, causal assumptions and factor
effects are explained in [lwa-param.md](lwa-param.md).
