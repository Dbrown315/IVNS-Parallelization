"""Conservative MPI execution of IVNS bus/ECU partitions.

Generators never cross a rank boundary. SerializableCAN is local to its bus;
only detached frame snapshots cross gateways, batched once per safe window.
"""
from collections import defaultdict
from contextlib import contextmanager
import copy
import csv
from dataclasses import dataclass
from functools import partial
import hashlib
import itertools
import json
import math
import pickle
import random
import time
import types
import uuid


@contextmanager
def setup_identifiers(seed):
    """Identical initial PKI/gateway identities on all ranks, not production keys."""
    original = uuid.uuid4
    counter = itertools.count()
    uuid.uuid4 = lambda: uuid.uuid5(uuid.NAMESPACE_OID, f'ivns-setup:{seed}:{next(counter)}')
    try:
        yield
    finally:
        uuid.uuid4 = original


@dataclass(frozen=True)
class Frame:
    arrival: float
    source: str
    target: str
    gateway: uuid.UUID
    sequence: int
    payload: bytes

    @property
    def order(self):
        return self.arrival, self.source, self.target, self.sequence


def encode_message(message):
    """Detach the environment; snapshot mutable gateway/payload data now."""
    detached = copy.copy(message)
    detached.sim_env = None
    return pickle.dumps(detached, protocol=pickle.HIGHEST_PROTOCOL)


class GatewayExchange:
    def __init__(self, env, owners, rank, size, lookahead=0):
        self.env, self.owners, self.rank = env, owners, rank
        self.lookahead = lookahead
        self.outgoing = [[] for _ in range(size)]
        self.sequences = defaultdict(int)
        self.ports = {}
        self.sent = self.received = self.remote_sent = self.bytes_sent = 0

    def attach(self, gateway):
        for bus, dll in zip(gateway.connected_bus, gateway._datalink_layer):
            self.ports[gateway.ecu_id, bus.comp_id] = dll
        exchange = self

        def forward(gateway, dll, message):
            target = next(bus.comp_id for bus, port in zip(gateway.connected_bus, gateway._datalink_layer)
                          if port is dll)
            source = message.current_bus
            delay = gateway.GW_TRANSITION_PROCESS * gateway._jitter
            if not math.isfinite(delay) or delay <= 0 or delay < exchange.lookahead:
                raise ValueError('Gateway delay must cover the synchronization window')
            edge = source, target
            seq = exchange.sequences[edge]
            exchange.sequences[edge] += 1
            payload = encode_message(message)
            frame = Frame(exchange.env.now + delay, source, target, gateway.ecu_id, seq, payload)
            owner = exchange.owners[target]
            exchange.outgoing[owner].append(frame)
            exchange.sent += 1
            exchange.remote_sent += owner != exchange.rank
            exchange.bytes_sent += len(payload)
            if False:
                yield  # The existing gateway expects a SimPy process interface.

        gateway.put_delayed_message = types.MethodType(forward, gateway)

    def drain(self):
        outgoing = self.outgoing
        self.outgoing = [[] for _ in outgoing]
        return outgoing

    def inject(self, frames):
        from simpy.events import Event
        for frame in sorted(frames, key=lambda frame: frame.order):
            if not math.isfinite(frame.arrival) or frame.arrival < self.env.now:
                raise RuntimeError(f'Late gateway frame at {frame.arrival}, local time {self.env.now}')
            if self.owners[frame.target] != self.rank:
                raise RuntimeError('Gateway frame delivered to wrong partition')
            event = Event(self.env)
            event._ok = True
            event._value = None
            event.callbacks.append(partial(self._deliver, frame))
            # Cross-gateway arrivals precede rank-local events at the same time,
            # regardless of when the batch was exchanged or how buses are placed.
            self.env.schedule(event, priority=-1, delay=frame.arrival - self.env.now)
            self.received += 1

    def _deliver(self, frame, event):
        message = pickle.loads(frame.payload)
        message.sim_env = self.env
        self.env.process(self.ports[frame.gateway, frame.target].put_msg(message))


def _start_partition(spec, owners, rank, seed):
    """Keep full configuration replicas, but activate only owned protocol state."""
    env = spec.get_env()
    local_buses = [bus for bus in spec.sim_param.buses.values() if owners[bus.comp_id] == rank]
    owned = {ecu.ecu_id for bus in local_buses for ecu in bus.connected_ecus
             if not getattr(ecu, '_GATEWAY', False)}
    local_ecus = [ecu for ecu in spec.sim_param.ecus.values() if ecu.ecu_id in owned]
    for ecu in local_ecus:
        if ecu.startup_delay:
            raise ValueError('Partitioned parameterized scenario does not support delayed ECU startup')
        app = ecu.ecuSW.app_lay
        app.random_source = random.Random(f'ivns-app:{seed}:{ecu.ecu_id}')
        env.process(app.main())
        env.process(ecu.ecuSW.comm_mod.datalink_lay.process())
    for bus in local_buses:
        env.process(bus.process())
    monitor = spec.monitor
    monitor.monitored = [obj for obj in monitor.monitored if obj in local_ecus or obj in local_buses]
    monitor.set_monitor_env(env)
    monitor.set_sim_process(env.process(monitor.monitor()))
    env.process(monitor.monitor_publish())
    return local_buses, local_ecus


def merge_exports(output, ranks):
    """Merge already closed exports; preserve schemas and deterministic time order."""
    for name, delimiter, has_header, time_column in (
            ('checkpoints.csv', ';', True, 0), ('can_bus.csv', ',', True, 1),
            ('buffer.csv', ',', False, 0)):
        rows, header = [], None
        for rank in range(ranks):
            path = output / f'rank-{rank:04d}' / name
            with path.open(newline='') as handle:
                source = csv.reader(handle, delimiter=delimiter, **({'quotechar': '|'} if name == 'buffer.csv' else {}))
                if has_header:
                    current = next(source)
                    if header is not None and current != header:
                        raise RuntimeError('Mismatched CSV headers')
                    header = current
                rows.extend(source)
        rows.sort(key=lambda row: (float(row[time_column]), tuple(row)))
        with (output / name).open('w', newline='') as handle:
            writer = csv.writer(handle, delimiter=delimiter, **({'quotechar': '|'} if name == 'buffer.csv' else {}))
            if header is not None:
                writer.writerow(header)
            writer.writerows(rows)


def semantic_digest(output):
    """Ignore object addresses and random IDs; retain event time, identity and stream."""
    with (output / 'checkpoints.csv').open() as handle:
        rows = list(csv.DictReader(handle, delimiter=';'))
    canonical = sorted((row['Time'], row['Component ID'], row['Monitor Tag'], row['Message Size'],
                        row['Stream ID'], row['Message Identifier']) for row in rows)
    return hashlib.sha256(json.dumps(canonical).encode()).hexdigest()


def run_partitioned(args):
    from mpi4py import MPI
    world = MPI.COMM_WORLD
    world_rank, world_size = world.Get_rank(), world.Get_size()
    active_count = min(args.buses, world_size)
    comm = world.Split(0 if world_rank < active_count else MPI.UNDEFINED, world_rank)
    if world_rank >= active_count:
        return
    rank, size = comm.Get_rank(), comm.Get_size()
    output = args.output_dir.resolve()
    started = time.perf_counter()
    window = args.sync_window if args.sync_window is not None else args.gateway_delay / 2
    try:
        # Import IVNS under the same setup identity sequence on every process.
        with setup_identifiers(args.seed):
            from components.base.bus.parallel.mpi_can_runtime import CANService, install_runtime
            from main_lwa_param import build_scenario
            service = CANService()
            install_runtime(service)
            local_args = copy.copy(args)
            local_args.output_dir = output / f'rank-{rank:04d}'
            local_args.output_dir.mkdir(parents=True, exist_ok=True)
            if rank == 0:
                (output / 'summary.json').unlink(missing_ok=True)
            random.seed(args.seed)
            spec, plan = build_scenario(local_args)
        env = spec.get_env()
        owners = {bus: index % size for index, bus in enumerate(plan['bus_members'])}
        exchange = GatewayExchange(env, owners, rank, size, lookahead=window)
        for ecu in spec.sim_param.ecus.values():
            if getattr(ecu, '_GATEWAY', False):
                exchange.attach(ecu)
        local_buses, local_ecus = _start_partition(spec, owners, rank, args.seed)
        built = time.perf_counter()
        comm.Barrier()
        running = time.perf_counter()
        compute = communication = 0.0
        epochs = 0
        # Half-open windows ensure new gateway effects cannot occur inside the
        # window that generated them. Every gateway, including colocated edges,
        # uses the same snapshot/injection order, independent of rank placement.
        for epoch in itertools.count(1):
            boundary = min(epoch * window, args.duration)
            if boundary <= env.now:
                raise ValueError('Synchronization window cannot advance floating-point simulation time')
            phase = time.perf_counter()
            env.run(until=boundary)
            compute += time.perf_counter() - phase
            phase = time.perf_counter()
            incoming = comm.alltoall(exchange.drain())
            exchange.inject([frame for batch in incoming for frame in batch])
            communication += time.perf_counter() - phase
            epochs += 1
            if boundary == args.duration:
                break
        run_seconds = time.perf_counter() - running
        spec.result_reader.on_finish()
        spec.result_reader.close_exports()
        local = dict(rank=rank, buses=[bus.comp_id for bus in local_buses],
                     ecus=[ecu.ecu_id for ecu in local_ecus], compute_seconds=compute,
                     exchange_wait_seconds=communication, build_seconds=built - started,
                     gateway_frames=exchange.sent, remote_gateway_frames=exchange.remote_sent,
                     gateway_bytes=exchange.bytes_sent, windows=epochs,
                     run_seconds=run_seconds,
                     transmissions=sum(bus.transmissions for bus in service.buses.values()),
                     elapsed_seconds=time.perf_counter() - started)
        stats = comm.gather(local, root=0)
        if rank == 0:
            merge_exports(output, size)
            summary = dict(plan, execution='partitioned', backend='MPICANBus / local SerializableCAN / mpi4py',
                           mpi_ranks=world_size, workers_used=size, worker_assignments=owners,
                           sync_window=window, simulated_until=args.duration, seed=args.seed,
                           interval=args.interval, start=args.start, gateway_delay=args.gateway_delay,
                           ranks=stats, semantic_digest=semantic_digest(output),
                           compute_critical_seconds=max(item['compute_seconds'] for item in stats),
                           total_seconds=time.perf_counter() - started)
            (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
            print(f'Completed concurrent LWA: {args.ecus} ECUs, {args.buses} buses, '
                  f'{size} active MPI ranks; results: {output}')
        install_runtime(None)
        comm.Free()
    except BaseException:
        # A rank cannot leave a failed neighbor waiting forever in a collective.
        import traceback
        traceback.print_exc()
        world.Abort(1)
