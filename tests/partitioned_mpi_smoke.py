"""Verify identical semantic event traces across rank counts and safe windows."""
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    (ROOT / 'work').mkdir(exist_ok=True)
    expected = None
    for ranks, window in ((1, None), (1, 1), (2, 1), (3, 1), (4, 1), (2, 0.5), (2, 2)):
        with tempfile.TemporaryDirectory(dir=ROOT / 'work', prefix='partition-smoke-') as directory:
            result = subprocess.run(
                ['mpiexec', '-n', str(ranks), sys.executable,
                 'tests/partitioned_reference.py' if window is None else 'main_lwa_param.py',
                 '--ecus', '7', '--buses', '3', '--duration', '60',
                 '--output-dir', directory] + ([] if window is None else ['--sync-window', str(window)]),
                cwd=ROOT, capture_output=True, text=True, timeout=60)
            assert result.returncode == 0, (result.stdout, result.stderr)
            assert 'Traceback' not in result.stderr, result.stderr
            summary = json.loads((Path(directory) / 'summary.json').read_text())
            digest = summary['semantic_digest']
            if expected is None:
                expected = digest
            assert digest == expected, (ranks, window, digest, expected)
            assert len(summary['ranks']) == min(ranks, 3)
            for rank in summary['ranks']:
                assert rank['transmissions'] > 0 and rank['compute_seconds'] > 0
                assert rank['ecus'] and rank['buses']
            with (Path(directory) / 'checkpoints.csv').open() as handle:
                rows = list(csv.DictReader(handle, delimiter=';'))
            for tag in ('CP_ECU_DECRYPTED_CONF_MESSAGE', 'CP_ECU_DECRYPTED_SIMPLE_MESSAGE'):
                observed = {row['Component ID'] for row in rows if row['Monitor Tag'] == 'MonitorTags.' + tag}
                assert observed == {f'ECU_{i}' for i in range(7)}, (tag, observed)
            print(f'Passed: ranks={ranks}, window={window}, identical semantic event digest', flush=True)


if __name__ == '__main__':
    main()
