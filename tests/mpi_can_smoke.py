"""Run with mpiexec -n 2 (also tested with 4); failures return nonzero."""
import os
from pathlib import Path
import sys
os.environ['IVNS_HEADLESS'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ECUSimulation'))
from mpi4py import MPI
from components.base.bus.parallel.mpi_can_runtime import MPICANRuntime, install_runtime, serve
from components.base.bus.parallel.serializable_can import Transmission
from components.base.bus.impl_bus_can import StdCANBus
from components.base.bus.impl_bus_can_mpi import MPICANBus
from can_fixture import exercise


def main():
    comm = MPI.COMM_WORLD
    if comm.Get_size() < 2:
        raise SystemExit('At least two ranks required')
    if comm.Get_rank() != 0:
        serve(comm)
        return
    runtime = MPICANRuntime(comm)
    install_runtime(runtime)
    try:
        for index, filtered in enumerate((False, True)):
            # Use a new bus id namespace for fixtures starting at time zero.
            class FixtureRuntime:
                def execute(self, bus_id, operation, argument):
                    return runtime.execute((index, bus_id), operation, argument)
            install_runtime(None)
            install_runtime(FixtureRuntime())
            actual = exercise(MPICANBus, filtered=filtered)
            assert actual == exercise(StdCANBus, filtered=filtered), actual
        for i in range(comm.Get_size() + 1):
            assert runtime.execute('bus_%s' % i, 'transmit', Transmission(0, 1, 101, 74)) == 1
        try:
            runtime.execute('error_bus', 'unknown', None)
        except RuntimeError as exc:
            assert 'Unknown CAN operation' in str(exc)
        else:
            raise AssertionError('Worker error was not propagated')
        assert runtime.execute('error_bus', 'arbitrate', [3, 1, 1]) == 1
        assert len(runtime.errors) == 1
        assert len(set(runtime.owners.values())) == comm.Get_size() - 1
        print('MPI CAN parity, worker affinity, error propagation and recovery passed on %s ranks' % comm.Get_size())
    finally:
        install_runtime(None)
        runtime.close()


if __name__ == '__main__':
    main()
