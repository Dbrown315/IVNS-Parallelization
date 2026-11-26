"""Builders for independent TESLA/TLS bus cohorts, sharing the MPI CAN runtime.

Keep each protocol cohort on one bus/rank: the original implementations use
process-wide stores and caches to coordinate peers. Cross-rank gateway sessions
are deliberately not represented as working distributed protocol sessions.
"""
import argparse
import logging
import math
import os
from pathlib import Path
import sys

from main_lwa_param import FIRST_STREAM_ID, MAX_ECUS, ROOT, finite_number


def parse_args(protocol, argv=None):
    parser = argparse.ArgumentParser(description=f'Headless {protocol.upper()} ECU/CAN benchmark with bus-local rings.')
    parser.add_argument('--ecus', type=int, default=6, help='total protocol ECUs (default: 6)')
    parser.add_argument('--buses', type=int, default=3, help='independent CAN buses, at least two ECUs each (default: 3)')
    parser.add_argument('--duration', type=finite_number, default=500.0, help='simulated seconds (default: 500)')
    parser.add_argument('--start', type=finite_number, default=260.0 if protocol == 'tesla' else 20.0,
                        help='first send time, matching the TESLA stream start (default: 260 TESLA / 20 TLS)')
    parser.add_argument('--interval', type=finite_number, default=0.1 if protocol == 'tesla' else 0.5,
                        help='per-ECU send interval (default: 0.1 TESLA / 0.5 TLS)')
    parser.add_argument('--payload-bytes', type=int, default=50 if protocol == 'tesla' else 20)
    parser.add_argument('--seed', type=int, default=1729)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'TestSimulation/logs' / f'{protocol}-param')
    if protocol == 'tesla':
        parser.add_argument('--key-chain-length', type=int, default=10000)
        parser.add_argument('--disclosure-delay', type=int, default=1, help='TESLA key disclosure delay in send intervals')
    args = parser.parse_args(argv)
    if not 2 <= args.ecus <= MAX_ECUS or not 1 <= args.buses <= args.ecus // 2:
        parser.error(f'require 2 <= --ecus <= {MAX_ECUS} and 1 <= --buses <= --ecus/2')
    if args.duration <= 0 or args.interval <= 0 or not 0 <= args.start < args.duration:
        parser.error('require positive duration/interval and 0 <= start < duration')
    if args.payload_bytes <= 0:
        parser.error('--payload-bytes must be positive')
    if protocol == 'tesla':
        minimum = math.ceil(args.duration / args.interval) + args.disclosure_delay + 2
        if args.disclosure_delay < 1 or args.key_chain_length < minimum:
            parser.error(f'positive disclosure delay and --key-chain-length >= {minimum} required for this duration/interval')
    args.protocol = protocol
    args.gateway_delay = 1.0  # No gateway links; the runtime uses a single run-to-horizon window.
    args.sync_window = None
    return args


def topology(args):
    members = {f'CAN_{bus}': [f'ECU_{i}' for i in range(bus, args.ecus, args.buses)] for bus in range(args.buses)}
    streams = []
    for group in members.values():
        for index, sender in enumerate(group):
            streams.append(dict(sender=sender, receiver=group[(index + 1) % len(group)],
                                message_id=FIRST_STREAM_ID + int(sender[4:])))
    return dict(protocol=args.protocol, traffic='bus-local-ring', regular_ecus=args.ecus,
                can_buses=args.buses, bus_members=members, streams=streams, gateway_links=[],
                security_module=None, payload_bytes=args.payload_bytes)


def build_scenario(args):
    import api.ecu_sim_api as api
    from api.core.api_core import TimingFunctionSet
    from api.core.component_specs import RegularECUSpec, TLSECUSpec, SimpleBusSpec
    from components.base.bus.impl_bus_can_mpi import MPICANBus
    from components.security.communication.stream import MessageStream
    from config.specification_set import GeneralSpecPreset, TeslaSpecPresets, TlsSpecPresets
    from config.timing_db_admin import TimingDBMap
    from enums.sec_cfg_enum import SymAuthMechEnum, AuKeyLengthEnum
    from io_processing.surveillance import Monitor
    from io_processing.result_reader import ResultReader
    from io_processing.result_interpreter.abst_result_interpreter import InterpreterOptions as Options
    from io_processing.result_interpreter.buffer_interpreter import BufferInterpreter
    from io_processing.result_interpreter.can_bus_interpreter import CanBusInterpreter
    from io_processing.result_interpreter.eventline_interpreter import EventlineInterpreter

    plan = topology(args)
    GeneralSpecPreset().enable()
    GeneralSpecPreset().bus = MPICANBus
    TimingDBMap().enable_fallback_message = True
    api.show_logging(logging.WARNING, str(args.output_dir / 'api.log'), True)
    env = api.create_environment(args.duration)
    if args.protocol == 'tesla':
        from components.security.ecu.types.impl_ecu_tesla import StdTeslaECUTimingFunctions
        preset = TeslaSpecPresets()
        preset.setup_spec = [0, 999999, args.key_chain_length]
        preset.key_exchange_spec = [SymAuthMechEnum.AES, AuKeyLengthEnum.bit_128, SymAuthMechEnum.CBC, 100]
        spec_class, ecu_type = RegularECUSpec, 'TeslaECU'
        timings = StdTeslaECUTimingFunctions(main_library_tag='CyaSSL')
        plan.update(key_chain_length=args.key_chain_length, disclosure_delay=args.disclosure_delay)
    else:
        from components.security.ecu.types.impl_ecu_tls import StdTLSECUTimingFunctions
        preset = TlsSpecPresets()
        from enums.tls_enums import CompressionMethod
        # Match main_tls_preset.py rather than the older class-default MD5 MAC.
        preset.record_layer_spec = [CompressionMethod.NULL, SymAuthMechEnum.AES,
                                    AuKeyLengthEnum.bit_128, SymAuthMechEnum.AES,
                                    AuKeyLengthEnum.bit_128, SymAuthMechEnum.CBC]
        spec_class, ecu_type = TLSECUSpec, 'TLSECU'
        timings = StdTLSECUTimingFunctions(main_library_tag='CyaSSL')
    ecus = {}
    timing = TimingFunctionSet()
    for stream in sorted(plan['streams'], key=lambda stream: stream['message_id']):
        spec = spec_class([stream['sender']], 20000, 20000)
        preset.apply_spec(spec)
        spec.set_apply_jitter(0.0000001 if args.protocol == 'tesla' else 0.0001)
        spec.add_sending_actions(args.start, args.interval, stream['message_id'], 'PARAMETRIC DATA', args.payload_bytes)
        ecu = api.set_ecus(env, 1, ecu_type, spec)[0]
        if ecu is None:
            raise RuntimeError(f'Failed to create {ecu_type} {stream["sender"]}')
        ecus[ecu.ecu_id] = ecu
        timing.set_mapping_from_function_set(ecu.ecu_id, timings)
        api.apply_timing_functions_set(env, ecu.ecu_id, timing)
    buses = api.set_busses(env, args.buses, 'MPICANBus', SimpleBusSpec(list(plan['bus_members'])))
    if any(bus is None or type(bus).__name__ != 'MPICANBus' for bus in buses):
        raise RuntimeError('All buses must use MPICANBus')
    for bus_id, members in plan['bus_members'].items():
        api.connect_bus_by_obj(env, bus_id, [ecus[ecu_id] for ecu_id in members])
    for stream in plan['streams']:
        options = dict(start_time=args.start, sending_interval=args.interval,
                       disclosure_delay=args.disclosure_delay) if args.protocol == 'tesla' else {}
        api.set_stream(env, MessageStream(stream['sender'], [stream['receiver']], stream['message_id'], **options))
    monitor = Monitor()
    monitor.show_monitor_time(False)
    monitor.set_sample_time(0.48)
    api.connect_monitor(env, monitor, 0.5)
    reader = ResultReader()
    reader.enable_handler(BufferInterpreter, [Options.CSV_FILE], str(args.output_dir / 'buffer.csv'))
    reader.enable_handler(EventlineInterpreter, [Options.CSV_FILE], str(args.output_dir / 'checkpoints.csv'))
    reader.enable_handler(CanBusInterpreter, [Options.CSV_MSG_FILE, Options.CSV_DR_FILE], str(args.output_dir / 'can_bus.csv'))
    api.connect_result_reader(env, monitor, reader)
    api.build_simulation(env)
    return env, plan


def main(protocol, argv=None):
    args = parse_args(protocol, argv)
    os.environ['IVNS_HEADLESS'] = '1'
    sys.path.insert(0, str(ROOT / 'ECUSimulation'))
    from components.base.bus.parallel.partitioned import run_partitioned
    run_partitioned(args, builder=build_scenario)
