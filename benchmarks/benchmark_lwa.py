"""Repeat fixed-work MPI scaling runs; never substitute synthetic CPU work.

python benchmarks/benchmark_lwa.py --suite factors --repeats 3 --output work/scaling.json
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=('strong', 'factors'), default='strong')
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--output', type=Path, default=ROOT / 'work/scaling.json')
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    cases = [('base', 12, 4, 60, 0.25, 2, (1, 2, 4))]
    if args.suite == 'factors':
        cases.extend([
            ('more_ecus', 24, 4, 60, 0.25, 2, (1, 4)),
            ('one_bus', 12, 1, 60, 0.25, 2, (1, 4)),
            ('more_traffic', 12, 4, 60, 0.05, 2, (1, 4)),
            ('short_lookahead', 12, 4, 60, 0.25, 0.02, (1, 4)),
            ('longer_run', 12, 4, 120, 0.25, 2, (1, 4)),
        ])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    results = dict(python=platform.python_version(), platform=platform.platform(),
                   cpu_affinity=len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None,
                   packages={name: importlib.metadata.version(name) for name in
                             ('simpy', 'serializable-simpy', 'mpi4py', 'numpy', 'scipy')},
                   repeats=args.repeats, cases=[])
    quota = Path('/sys/fs/cgroup/cpu.max')
    results['cpu_quota'] = quota.read_text().strip() if quota.exists() else None
    results['source_sha256'] = hashlib.sha256(b''.join((ROOT / path).read_bytes() for path in
        ('main_lwa_param.py', 'ECUSimulation/components/base/bus/parallel/partitioned.py'))).hexdigest()
    for name, ecus, buses, duration, interval, delay, rank_counts in cases:
        reference = None
        for ranks in rank_counts:
            samples = []
            for repetition in range(args.repeats):
                with tempfile.TemporaryDirectory(dir=args.output.parent, prefix='lwa-bench-') as tmp:
                    command = ['mpiexec', '-n', str(ranks), sys.executable, str(ROOT / 'main_lwa_param.py'),
                               '--ecus', str(ecus), '--buses', str(buses), '--duration', str(duration),
                               '--interval', str(interval), '--gateway-delay', str(delay), '--output-dir', tmp]
                    started = time.perf_counter()
                    run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
                    wall = time.perf_counter() - started
                    if run.returncode != 0:
                        raise RuntimeError(run.stdout + run.stderr)
                    summary = json.loads((Path(tmp) / 'summary.json').read_text())
                    digest = summary['semantic_digest']
                    if reference is None:
                        reference = digest
                    if digest != reference:
                        raise RuntimeError(f'Semantic trace mismatch: {name}, {ranks} ranks')
                    samples.append(dict(wall_seconds=wall, model_seconds=summary['total_seconds'],
                                        run_seconds=max(rank['run_seconds'] for rank in summary['ranks']),
                                        compute_seconds=[rank['compute_seconds'] for rank in summary['ranks']],
                                        exchange_seconds=[rank['exchange_wait_seconds'] for rank in summary['ranks']],
                                        windows=summary['ranks'][0]['windows']))
                    print(f'{name}, ranks={ranks}, repeat={repetition + 1}: {wall:.3f}s', flush=True)
            row = dict(name=name, ecus=ecus, buses=buses, duration=duration, interval=interval,
                       gateway_delay=delay, ranks=ranks, active_ranks=min(ranks, buses),
                       semantic_digest=reference, samples=samples,
                       wall_median=statistics.median(sample['wall_seconds'] for sample in samples),
                       run_median=statistics.median(sample['run_seconds'] for sample in samples))
            results['cases'].append(row)
            baseline = next(item for item in results['cases'] if item['name'] == name and item['ranks'] == 1)
            row['wall_speedup'] = baseline['wall_median'] / row['wall_median']
            row['run_speedup'] = baseline['run_median'] / row['run_median']
            args.output.write_text(json.dumps(results, indent=2) + '\n')
    print('Saved: ' + str(args.output), flush=True)


if __name__ == '__main__':
    main()
