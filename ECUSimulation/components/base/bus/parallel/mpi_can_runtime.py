"""Explicit MPI lifecycle; importing a bus never imports/initializes MPI."""
from components.base.bus.parallel.serializable_can import SerializableCAN

_runtime = None
_REQUEST = 4101
_REPLY = 4102


def get_runtime():
    if _runtime is None:
        raise RuntimeError("MPICANBus requires run_mpi_headless.py on at least two MPI ranks")
    return _runtime


def install_runtime(runtime):
    global _runtime
    if _runtime is not None and runtime is not None:
        raise RuntimeError("A CAN runtime is already installed")
    _runtime = runtime


class CANService:
    """Shared dispatch for local tests and MPI workers."""

    def __init__(self):
        self.buses = {}

    def execute(self, bus_id, operation, argument):
        if bus_id not in self.buses:
            self.buses[bus_id] = SerializableCAN()
        bus = self.buses[bus_id]
        if operation == 'arbitrate':
            return bus.arbitrate(argument)
        if operation == 'transmit':
            return bus.transmit(argument)
        raise ValueError("Unknown CAN operation: %s" % operation)


class MPICANRuntime:
    """Rank 0 coordinator with deterministic bus-to-worker affinity.

    Requests are synchronous: the host cannot pass an unresolved CAN completion.
    This preserves causality without a speculative delta or rollback protocol.
    It is a migration backend, not a speedup of the current ECU workload.
    """

    def __init__(self, comm):
        if comm.Get_rank() != 0 or comm.Get_size() < 2:
            raise ValueError("CAN coordinator requires rank 0 and at least two ranks")
        self.comm = comm
        self.owners = {}
        self.closed = False
        self.errors = []

    def execute(self, bus_id, operation, argument):
        if self.closed:
            raise RuntimeError("CAN runtime is closed")
        if bus_id not in self.owners:
            self.owners[bus_id] = 1 + len(self.owners) % (self.comm.Get_size() - 1)
        worker = self.owners[bus_id]
        self.comm.send((bus_id, operation, argument), dest=worker, tag=_REQUEST)
        ok, result = self.comm.recv(source=worker, tag=_REPLY)
        if not ok:
            error = "CAN worker %s: %s" % (worker, result)
            self.errors.append(error)
            raise RuntimeError(error)
        return result

    def close(self):
        if not self.closed:
            for rank in range(1, self.comm.Get_size()):
                self.comm.send(None, dest=rank, tag=_REQUEST)
            self.closed = True


def serve(comm):
    if comm.Get_rank() == 0:
        raise ValueError("Rank 0 cannot serve CAN worker requests")
    service = CANService()
    while True:
        request = comm.recv(source=0, tag=_REQUEST)
        if request is None:
            return
        try:
            reply = (True, service.execute(*request))
        except Exception as exc:
            reply = (False, '%s: %s' % (type(exc).__name__, exc))
        comm.send(reply, dest=0, tag=_REPLY)
