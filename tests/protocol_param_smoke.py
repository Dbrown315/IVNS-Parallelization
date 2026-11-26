"""Portable MPI traffic/semantic regression checks for TESLA and TLS."""
import argparse
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mpiexec', default=shutil.which('mpiexec') or 'mpiexec')
    args = parser.parse_args()
    (ROOT / 'work').mkdir(exist_ok=True)
    for protocol, tag in [('tesla', 'CP_RETURNED_AUTHENTICATED_SIMPLE_MESSAGE'),
                          ('tls', 'CP_RECEIVE_SIMPLE_MESSAGE')]:
        reference = None
        for ranks in (1, 2, 3):
            with tempfile.TemporaryDirectory(dir=ROOT / 'work', prefix='protocol spaces ü-') as folder:
                command = [args.mpiexec, '-n', str(ranks), sys.executable,
                           str(ROOT / f'main_{protocol}_param.py'), '--ecus', '6', '--buses', '2',
                           '--duration', '30', '--start', '10', '--interval', '0.5', '--output-dir', folder]
                if protocol == 'tesla':
                    command += ['--key-chain-length', '128']
                result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
                                        env=dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8'), timeout=90)
                assert result.returncode == 0, (result.stdout, result.stderr)
                assert 'Traceback' not in result.stderr, result.stderr
                summary = json.loads((Path(folder) / 'summary.json').read_text(encoding='utf-8'))
                assert summary['protocol'] == protocol
                assert summary['workers_used'] == min(ranks, 2)
                assert all(rank['windows'] == 1 for rank in summary['ranks'])
                if reference is None:
                    reference = summary['semantic_digest']
                assert reference == summary['semantic_digest'], (protocol, ranks)
                with (Path(folder) / 'checkpoints.csv').open(encoding='utf-8', newline='') as handle:
                    rows = list(csv.DictReader(handle, delimiter=';'))
                received = {row['Component ID'] for row in rows if row['Monitor Tag'] == 'MonitorTags.' + tag}
                assert received == {f'ECU_{i}' for i in range(6)}, (protocol, ranks, received)
                print(f'Passed {protocol}, ranks={ranks}: every ECU receives data, matching semantic trace', flush=True)


if __name__ == '__main__':
    main()
