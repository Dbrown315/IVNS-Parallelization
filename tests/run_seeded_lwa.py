"""Repeatable full-preset check; UUIDs here are test identifiers only.

Run with `python tests/run_seeded_lwa.py serial` or
`mpiexec -n 4 python tests/run_seeded_lwa.py mpi`.
"""
import itertools
from pathlib import Path
import random
import runpy
import sys
import uuid

random.seed(1729)
counter = itertools.count(1)
uuid.uuid4 = lambda: uuid.UUID(int=next(counter))
root = Path(__file__).resolve().parents[1]
if sys.argv[1:] == ['serial']:
    runner = 'run_headless.py'
elif sys.argv[1:] == ['mpi']:
    runner = 'run_mpi_headless.py'
else:
    raise SystemExit('Expected serial or mpi')
runpy.run_path(str(root / runner), run_name='__main__')
