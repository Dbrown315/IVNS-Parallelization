"""Repeat fixed-work MPI scaling runs; never substitute synthetic CPU work.

python benchmarks/benchmark_lwa.py --suite factors --repeats 3 --output work/scaling.json
"""
import argparse
import csv
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import statistics
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=('strong', 'factors'), default='strong')
    parser.add_argument('--protocol', choices=('lwa', 'tesla', 'tls'), default='lwa')
    parser.add_argument('--mpiexec', default=shutil.which('mpiexec') or 'mpiexec',
                        help='MPI launcher executable, including a Windows path with spaces')
    parser.add_argument('--start', type=float, default=10.0, help='first send time for the benchmark scenarios')
    parser.add_argument('--key-chain-length', type=int, default=10000, help='TESLA only')
    parser.add_argument('--smoke', action='store_true', help='small correctness/preflight workload on 1 and 2 ranks')
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
    if args.smoke:
        cases = [('smoke', 4, 2, 30, 0.5, 2, (1, 2))]
    if args.protocol != 'lwa':
        cases = [case for case in cases if case[0] != 'short_lookahead']
    args.output.parent.mkdir(parents=True, exist_ok=True)
    results = dict(protocol=args.protocol, python=platform.python_version(), platform=platform.platform(),
                   system=platform.system(), machine=platform.machine(), cpu_count=os.cpu_count(),
                   mpi_launcher=args.mpiexec, interpreter=sys.executable,
                   packages={name: importlib.metadata.version(name) for name in
                             ('simpy', 'serializable-simpy', 'mpi4py', 'numpy', 'scipy')},
                   repeats=args.repeats, cases=[])
    launcher = f'main_{args.protocol}_param.py'
    results['source_sha256'] = hashlib.sha256(b''.join((ROOT / path).read_bytes() for path in
        (launcher, 'main_lwa_param.py', 'protocol_scenarios.py',
         'ECUSimulation/components/base/bus/parallel/partitioned.py'))).hexdigest()
    for name, ecus, buses, duration, interval, delay, rank_counts in cases:
        reference = None
        for ranks in rank_counts:
            samples = []
            for repetition in range(args.repeats):
                with tempfile.TemporaryDirectory(dir=args.output.parent, prefix='lwa-bench-') as tmp:
                    command = [args.mpiexec, '-n', str(ranks), sys.executable, str(ROOT / launcher),
                               '--ecus', str(ecus), '--buses', str(buses), '--duration', str(duration),
                               '--interval', str(interval), '--start', str(args.start), '--output-dir', tmp]
                    if args.protocol == 'lwa':
                        command.extend(['--gateway-delay', str(delay)])
                    elif args.protocol == 'tesla':
                        command.extend(['--key-chain-length', str(args.key_chain_length)])
                    child_env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
                    started = time.perf_counter()
                    run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                         encoding='utf-8', env=child_env, timeout=180)
                    wall = time.perf_counter() - started
                    if run.returncode != 0 or 'Traceback' in run.stdout or 'Traceback' in run.stderr:
                        raise RuntimeError(run.stdout + run.stderr)
                    summary = json.loads((Path(tmp) / 'summary.json').read_text(encoding='utf-8'))
                    tag = {'lwa': 'CP_ECU_DECRYPTED_SIMPLE_MESSAGE',
                           'tesla': 'CP_RETURNED_AUTHENTICATED_SIMPLE_MESSAGE',
                           'tls': 'CP_RECEIVE_SIMPLE_MESSAGE'}[args.protocol]
                    with (Path(tmp) / 'checkpoints.csv').open(encoding='utf-8', newline='') as handle:
                        delivered = {row['Component ID'] for row in csv.DictReader(handle, delimiter=';')
                                     if row['Monitor Tag'] == 'MonitorTags.' + tag}
                    if delivered != {f'ECU_{i}' for i in range(ecus)}:
                        raise RuntimeError(f'{args.protocol} application reception incomplete: {sorted(delivered)}')
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
                       gateway_delay=delay if args.protocol == 'lwa' else None,
                       start=args.start, traffic='cross-bus-ring' if args.protocol == 'lwa' else 'bus-local-ring',
                       payload_bytes=summary.get('payload_bytes', 50),
                       key_chain_length=summary.get('key_chain_length'),
                       disclosure_delay=summary.get('disclosure_delay'),
                       ranks=ranks, active_ranks=min(ranks, buses),
                       semantic_digest=reference, samples=samples,
                       wall_median=statistics.median(sample['wall_seconds'] for sample in samples),
                       run_median=statistics.median(sample['run_seconds'] for sample in samples))
            results['cases'].append(row)
            baseline = next(item for item in results['cases'] if item['name'] == name and item['ranks'] == 1)
            row['wall_speedup'] = baseline['wall_median'] / row['wall_median']
            row['run_speedup'] = baseline['run_median'] / row['run_median']
            args.output.write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
    print('Saved: ' + str(args.output), flush=True)


if __name__ == '__main__':
    main()
