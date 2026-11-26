"""Launch real MPI scenarios and verify authentication and ring traffic.

Run with the MPI-enabled Python: python tests/param_lwa_smoke.py
"""
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    (ROOT / 'work').mkdir(exist_ok=True)
    # Covers no gateways, uneven placement, more buses than workers, and idle workers.
    for ranks, ecus, buses in ((2, 2, 1), (4, 7, 3), (2, 8, 4), (4, 2, 2)):
        with tempfile.TemporaryDirectory(dir=ROOT / 'work', prefix='lwa-smoke-') as directory:
            command = ['mpiexec', '-n', str(ranks), sys.executable, str(ROOT / 'main_lwa_param.py'),
                       '--ecus', str(ecus), '--buses', str(buses), '--duration', '60',
                       '--output-dir', directory]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
            assert result.returncode == 0, (command, result.stdout, result.stderr)
            assert 'Traceback' not in result.stderr, result.stderr
            folder = Path(directory)
            summary = json.loads((folder / 'summary.json').read_text())
            assert summary['regular_ecus'] == ecus
            assert summary['can_buses'] == buses
            assert summary['simulated_until'] == 60
            assert summary['workers_used'] == min(buses, ranks)
            assert set(summary['worker_assignments']) == {f'CAN_{i}' for i in range(buses)}
            with (folder / 'checkpoints.csv').open() as handle:
                rows = list(csv.DictReader(handle, delimiter=';'))
            ids = {f'ECU_{i}' for i in range(ecus)}
            for tag in ('CP_ECU_DECRYPTED_CONF_MESSAGE', 'CP_ECU_DECRYPTED_SIMPLE_MESSAGE'):
                observed = {row['Component ID'] for row in rows if row['Monitor Tag'] == 'MonitorTags.' + tag}
                assert observed == ids, (command, tag, observed, ids)
            print(f'Passed: {ecus} ECUs, {buses} buses, {ranks} ranks; all ECUs authenticated and received data')


if __name__ == '__main__':
    main()
