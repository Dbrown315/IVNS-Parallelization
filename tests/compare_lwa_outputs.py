"""Compare two LWA output directories, ignoring only Python object addresses."""
from pathlib import Path
import re
import sys

if len(sys.argv) != 3:
    raise SystemExit('Usage: python tests/compare_lwa_outputs.py SERIAL_DIR MPI_DIR')
for name in ('buffer.csv', 'can_bus.csv', 'checkpoints.csv'):
    def records(directory):
        return [re.sub(r'0x[0-9a-f]+', '<address>', line)
                for line in (Path(directory) / name).read_text().splitlines() if line]
    serial, mpi = records(sys.argv[1]), records(sys.argv[2])
    if not serial or serial != mpi:
        raise SystemExit('%s differs: serial=%s records, MPI=%s records' % (name, len(serial), len(mpi)))
    print('%s: %s matching records' % (name, len(serial)))
