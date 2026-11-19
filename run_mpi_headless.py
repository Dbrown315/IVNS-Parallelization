"""Run the existing LWA preset with SerializableSimpy CAN workers."""
import os
from pathlib import Path
import runpy
import sys


def main():
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root / 'ECUSimulation'))
    os.environ['IVNS_HEADLESS'] = '1'
    from mpi4py import MPI
    from components.base.bus.parallel.mpi_can_runtime import MPICANRuntime, install_runtime, serve

    comm = MPI.COMM_WORLD
    if comm.Get_size() < 2:
        raise SystemExit('Use mpiexec -n 2 python run_mpi_headless.py (or more ranks)')
    if comm.Get_rank() != 0:
        serve(comm)
        return
    runtime = MPICANRuntime(comm)
    install_runtime(runtime)
    try:
        os.environ['IVNS_CAN_BACKEND'] = 'mpi'
        (root / 'TestSimulation/logs').mkdir(exist_ok=True)
        try:
            runpy.run_path(str(root / 'TestSimulation/main_lwa_preset.py'), run_name='__main__')
        except SystemExit as exc:
            # APICore signals normal completion with SystemExit(None).
            if exc.code not in (None, 0):
                raise
        # Legacy IVNS catches simulation exceptions; still fail the launcher if
        # any worker reported an error instead of silently accepting partial CSVs.
        if runtime.errors:
            raise RuntimeError('MPI CAN run failed: ' + '; '.join(runtime.errors))
    finally:
        install_runtime(None)
        runtime.close()


if __name__ == '__main__':
    main()
