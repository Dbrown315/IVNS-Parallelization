import os
from pathlib import Path
import pickle
import sys
from types import SimpleNamespace
import unittest

os.environ['IVNS_HEADLESS'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ECUSimulation'))
import simpy
from components.base.bus.parallel.partitioned import Frame, GatewayExchange, encode_message


class PartitionTests(unittest.TestCase):
    def test_snapshot_detaches_environment_and_mutable_payload(self):
        env = simpy.Environment()
        message = SimpleNamespace(sim_env=env, data=['before'], gw_id=['gw'])
        payload = encode_message(message)
        message.data.append('after')
        message.gw_id.append('next')
        decoded = pickle.loads(payload)
        self.assertIsNone(decoded.sim_env)
        self.assertEqual(decoded.data, ['before'])
        self.assertEqual(decoded.gw_id, ['gw'])
        self.assertIs(message.sim_env, env)

    def test_late_or_misrouted_frames_fail(self):
        env = simpy.Environment(initial_time=2)
        exchange = GatewayExchange(env, {'CAN_0': 0, 'CAN_1': 1}, 0, 2)
        for arrival, target in [(1, 'CAN_0'), (2, 'CAN_1')]:
            with self.subTest(arrival=arrival, target=target):
                with self.assertRaises(RuntimeError):
                    exchange.inject([Frame(arrival, 'CAN_1', target, None, 0, b'')])

    def test_gateway_snapshot_and_exact_boundary_delivery(self):
        env = simpy.Environment()
        observed = []

        class Port:
            def put_msg(self, message):
                observed.append((env.now, message.data))
                if False:
                    yield

        port = Port()
        gateway = SimpleNamespace(ecu_id='gateway', connected_bus=[SimpleNamespace(comp_id='CAN_1')],
                                  _datalink_layer=[port], GW_TRANSITION_PROCESS=1, _jitter=1)
        exchange = GatewayExchange(env, {'CAN_0': 0, 'CAN_1': 0}, 0, 1, lookahead=1)
        exchange.attach(gateway)
        message = SimpleNamespace(sim_env=env, data=['original'], current_bus='CAN_0')
        env.process(gateway.put_delayed_message(port, message))
        env.run(until=1)
        batches = exchange.drain()
        self.assertEqual(batches[0][0].arrival, 1)
        message.data.append('mutated')
        exchange.inject(batches[0])
        env.run(until=2)
        self.assertEqual(observed, [(1, ['original'])])

    def test_gateway_arrival_precedes_same_time_local_event(self):
        env = simpy.Environment()
        observed = []

        class Port:
            def put_msg(self, message):
                observed.append('gateway')
                if False:
                    yield

        def local():
            yield env.timeout(1)
            observed.append('local')

        env.process(local())
        env.run(until=0.5)
        exchange = GatewayExchange(env, {'CAN_0': 0}, 0, 1)
        exchange.ports['gw', 'CAN_0'] = Port()
        exchange.inject([Frame(1, 'CAN_1', 'CAN_0', 'gw', 0,
                               encode_message(SimpleNamespace(sim_env=None)))])
        env.run(until=2)
        self.assertEqual(observed, ['gateway', 'local'])


if __name__ == '__main__':
    unittest.main()
