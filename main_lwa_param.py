"""Parameterized headless LWA scenario using SerializableSimpy CAN workers.

Example: mpiexec -n 4 python main_lwa_param.py --ecus 12 --buses 3
"""
import argparse
import json
import logging
import math
import os
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parent
FIRST_STREAM_ID = 0x100
MAX_ECUS = 0x800 - FIRST_STREAM_ID


def finite_number(value):
    number = float(value)
    if not math.isfinite(number):
        raise argparse.ArgumentTypeError('must be finite')
    return number


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ecus', type=int, default=6,
                        help='total regular ECUs, excluding security module and gateways (default: 6)')
    parser.add_argument('--buses', type=int, default=3, help='CAN buses (default: 3)')
    parser.add_argument('--duration', type=finite_number, default=200.0,
                        help='simulated seconds (default: 200)')
    parser.add_argument('--start', type=finite_number, default=10.0,
                        help='first application send time in simulated seconds (default: 10)')
    parser.add_argument('--interval', type=finite_number, default=0.5,
                        help='send interval per ECU in simulated seconds (default: 0.5)')
    parser.add_argument('--gateway-delay', type=finite_number, default=2.0,
                        help='forwarding delay per gateway in simulated seconds (default: 2)')
    parser.add_argument('--seed', type=int, default=1729, help='random jitter seed (default: 1729)')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'TestSimulation/logs/param',
                        help='CSV, api.log and summary.json directory (overwritten on rerun)')
    args = parser.parse_args(argv)
    if not 2 <= args.ecus <= MAX_ECUS:
        parser.error('--ecus must be between 2 and %s (one unique 11-bit CAN stream per ECU)' % MAX_ECUS)
    if not 1 <= args.buses <= args.ecus:
        parser.error('--buses must be between 1 and --ecus so every bus has a regular ECU')
    if args.duration <= 0 or args.interval <= 0:
        parser.error('--duration and --interval must be positive')
    if not 0 <= args.start < args.duration:
        parser.error('--start must be nonnegative and less than --duration')
    if args.gateway_delay < 0:
        parser.error('--gateway-delay must be nonnegative')
    return args


def topology(ecus, buses):
    """Round-robin ECU placement and a chain of buses, without simulator imports."""
    members = [[f'ECU_{i}' for i in range(bus, ecus, buses)] for bus in range(buses)]
    return {
        'regular_ecus': ecus,
        'can_buses': buses,
        'security_module': {'id': 'SEC_0', 'bus': 'CAN_0'},
        'bus_members': {f'CAN_{i}': group for i, group in enumerate(members)},
        'gateway_links': [[f'CAN_{i}', f'CAN_{i + 1}'] for i in range(buses - 1)],
        'streams': [{'sender': f'ECU_{i}', 'receiver': f'ECU_{(i + 1) % ecus}',
                     'message_id': FIRST_STREAM_ID + i} for i in range(ecus)],
    }


def build_scenario(args):
    """Build the complete LWA model on rank 0 after installing the MPI runtime."""
    import api.ecu_sim_api as api
    from api.core.api_core import TimingFunctionSet
    from api.core.component_specs import RegularECUSpec, SimpleECUSpec, SimpleBusCouplerSpec, SimpleBusSpec
    from components.base.bus.impl_bus_can_mpi import MPICANBus
    from components.security.communication.stream import MessageStream
    from components.security.ecu.types.impl_ecu_secure import StdSecurECUTimingFunctions
    from components.security.ecu.types.impl_sec_mod_lwa import StdSecurLwSecModTimingFunctions
    from config.specification_set import GeneralSpecPreset, LWASpecPresets
    from config.timing_db_admin import TimingDBMap
    from config import can_registration
    from enums.sec_cfg_enum import CAEnum, SymAuthMechEnum
    from io_processing.surveillance import Monitor
    from io_processing.result_reader import ResultReader
    from io_processing.result_interpreter.abst_result_interpreter import InterpreterOptions as Options
    from io_processing.result_interpreter.buffer_interpreter import BufferInterpreter
    from io_processing.result_interpreter.can_bus_interpreter import CanBusInterpreter
    from io_processing.result_interpreter.eventline_interpreter import EventlineInterpreter

    plan = topology(args.ecus, args.buses)
    if set(range(FIRST_STREAM_ID, FIRST_STREAM_ID + args.ecus)) & set(can_registration.AUTH_MESSAGES):
        raise ValueError('Application stream IDs overlap configured authentication CAN IDs')
    preset = LWASpecPresets()
    preset.preset_ecu = preset.preset_sec_mod = 'Crypto_Lib_HW'
    preset.trigger_spec = [0, 99999999]
    preset.ecu_key_info[2] = preset.session_key_info[2] = SymAuthMechEnum.ECB
    GeneralSpecPreset().enable()
    GeneralSpecPreset().bus = MPICANBus
    TimingDBMap().enable_fallback_message = True
    api.show_logging(logging.WARNING, str(args.output_dir / 'api.log'), True)
    env = api.create_environment(args.duration)

    ecus = []
    for stream in plan['streams']:
        spec = RegularECUSpec([stream['sender']], 20000, 20000)
        spec.set_apply_jitter(0.0001)
        preset.apply_spec(spec, 'ecu')
        # Authentication remains active. Repeated attempts after --start let
        # application traffic begin once authentication/authorization completes.
        spec.add_sending_actions(args.start, args.interval, stream['message_id'], 'LWA PARAM', 50)
        group = api.set_ecus(env, 1, 'RegularSecureECU', spec)
        if len(group) != 1 or group[0] is None:
            raise RuntimeError('Failed to create ' + stream['sender'])
        ecus.extend(group)
    sec_spec = SimpleECUSpec(['SEC_0'], 200000, 200000)
    sec_spec.set_apply_jitter(0.0001)
    preset.apply_spec(sec_spec, 'sec_mod')
    security = api.set_ecus(env, 1, 'SecLwAuthSecurityModule', sec_spec)[0]
    if security is None:
        raise RuntimeError('Failed to create security module')
    gateway_spec = SimpleBusCouplerSpec([])
    gateway_spec.set_ecu_setting('t_transition_process', args.gateway_delay)
    gateways = api.set_ecus(env, args.buses - 1, 'CANGateway', gateway_spec) if args.buses > 1 else []
    bus_ids = list(plan['bus_members'])
    buses = api.set_busses(env, args.buses, 'MPICANBus', SimpleBusSpec(bus_ids))
    if len(buses) != args.buses or any(bus is None or type(bus).__name__ != 'MPICANBus' for bus in buses):
        raise RuntimeError('All requested buses must use MPICANBus')
    if len(gateways) != args.buses - 1 or any(gateway is None for gateway in gateways):
        raise RuntimeError('Failed to create gateway chain')
    for index, bus_id in enumerate(bus_ids):
        attached = ecus[index::args.buses]
        if index == 0:
            attached = attached + [security]
        if index > 0:
            attached = attached + [gateways[index - 1]]
        if index < len(gateways):
            attached = attached + [gateways[index]]
        api.connect_bus_by_obj(env, bus_id, attached)

    api.register_ecu_groups_to_secmod(env, security.ecu_id, [ecus])
    certificates = api.create_cert_manager()
    ecu_ids = [ecu.ecu_id for ecu in ecus]
    for ecu_id in ecu_ids:
        api.generate_valid_ecu_cert_cfg(certificates, ecu_id, CAEnum.CA_L313, security.ecu_id, 0, float('inf'))
    api.generate_valid_sec_mod_cert_cfg(certificates, security.ecu_id, CAEnum.CA_L313, ecu_ids, 0, float('inf'))
    api.apply_certification(env, certificates)
    for stream in plan['streams']:
        api.add_allowed_stream(env, security.ecu_id, MessageStream(
            stream['sender'], [stream['receiver']], stream['message_id'], float('inf'), 0, float('inf')))
    api.autoset_gateway_filters(env, security.ecu_id)
    timing = TimingFunctionSet()
    timing.set_mapping_from_function_set(security.ecu_id, StdSecurLwSecModTimingFunctions(
        main_library_tag=preset.preset_sec_mod))
    api.apply_timing_functions_set(env, security.ecu_id, timing)
    ecu_timing = StdSecurECUTimingFunctions(main_library_tag=preset.preset_ecu)
    for ecu_id in ecu_ids:
        timing.set_mapping_from_function_set(ecu_id, ecu_timing)
        api.apply_timing_functions_set(env, ecu_id, timing)

    monitor = Monitor()
    monitor.show_monitor_time(False)
    monitor.set_sample_time(0.48)
    api.connect_monitor(env, monitor, 0.5)
    reader = ResultReader()
    reader.enable_handler(BufferInterpreter, [Options.CONNECTION, Options.CSV_FILE],
                          str(args.output_dir / 'buffer.csv'))
    reader.enable_handler(EventlineInterpreter, [Options.CSV_FILE], str(args.output_dir / 'checkpoints.csv'))
    reader.enable_handler(CanBusInterpreter, [Options.CSV_MSG_FILE, Options.CSV_DR_FILE],
                          str(args.output_dir / 'can_bus.csv'))
    api.connect_result_reader(env, monitor, reader)
    api.build_simulation(env)
    if len(env.sim_param.buses) != args.buses:
        raise RuntimeError('Built topology has the wrong number of CAN buses')
    return env, plan


def main(argv=None):
    args = parse_args(argv)  # --help and invalid arguments work without MPI installed.
    sys.path.insert(0, str(ROOT / 'ECUSimulation'))
    os.environ['IVNS_HEADLESS'] = '1'
    from mpi4py import MPI
    from components.base.bus.parallel.mpi_can_runtime import MPICANRuntime, install_runtime, serve

    comm = MPI.COMM_WORLD
    if comm.Get_size() < 2:
        raise SystemExit('Use mpiexec -n 2 python main_lwa_param.py --ecus 6 --buses 3 (or more ranks)')
    if comm.Get_rank() != 0:
        serve(comm)
        return
    runtime = MPICANRuntime(comm)
    install_runtime(runtime)
    try:
        started = time.perf_counter()
        args.output_dir = args.output_dir.resolve()
        args.output_dir.mkdir(parents=True, exist_ok=True)
        # Remove a previous success summary before starting a new run.
        (args.output_dir / 'summary.json').unlink(missing_ok=True)
        random.seed(args.seed)
        try:
            env, plan = build_scenario(args)
        except SystemExit as exc:
            raise RuntimeError('IVNS exited during scenario setup') from exc
        simpy_env = env.get_env()
        built = time.perf_counter()
        import api.ecu_sim_api as api
        try:
            api.run_simulation(env)
        except SystemExit as exc:
            # APICore ends even a successful run with SystemExit(None).
            # Retain failure codes, then verify the actual simulated horizon.
            if exc.code not in (None, 0):
                raise
        finished = time.perf_counter()
        if runtime.errors:
            raise RuntimeError('MPI CAN run failed: ' + '; '.join(runtime.errors))
        if simpy_env.now != args.duration:
            raise RuntimeError('IVNS stopped early at %s, expected %s' % (simpy_env.now, args.duration))
        summary = dict(plan, backend='MPICANBus / SerializableSimpy / mpi4py',
                       mpi_ranks=comm.Get_size(), workers_used=len(set(runtime.owners.values())),
                       worker_assignments=runtime.owners, simulated_until=simpy_env.now,
                       seed=args.seed, interval=args.interval, start=args.start,
                       gateway_delay=args.gateway_delay, build_seconds=built - started,
                       run_and_export_seconds=finished - built, total_seconds=finished - started)
        (args.output_dir / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        print('Completed: %s regular ECUs, %s CAN buses, %s gateways, 1 security module; '
              '%s MPI workers used. Results: %s' % (
                  args.ecus, args.buses, args.buses - 1, summary['workers_used'], args.output_dir))
    finally:
        install_runtime(None)
        runtime.close()


if __name__ == '__main__':
    main()
