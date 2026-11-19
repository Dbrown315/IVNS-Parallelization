from contextlib import redirect_stderr
import io
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from main_lwa_param import parse_args, topology


class LWAParamTests(unittest.TestCase):
    def test_reject_invalid_topologies_and_times(self):
        for argv in (['--ecus', '1'], ['--ecus', '1793'], ['--buses', '0'],
                     ['--ecus', '2', '--buses', '3'], ['--duration', '0'],
                     ['--duration', 'nan'], ['--interval', 'inf'], ['--interval', '-1'],
                     ['--start', '-1'], ['--start', '200'], ['--gateway-delay', '-1']):
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as exc:
                    parse_args(argv)
                self.assertEqual(exc.exception.code, 2)

    def test_uneven_topology_has_connected_buses_and_unique_streams(self):
        plan = topology(7, 3)
        self.assertEqual(plan['bus_members'], {'CAN_0': ['ECU_0', 'ECU_3', 'ECU_6'],
                                              'CAN_1': ['ECU_1', 'ECU_4'],
                                              'CAN_2': ['ECU_2', 'ECU_5']})
        self.assertEqual(plan['gateway_links'], [['CAN_0', 'CAN_1'], ['CAN_1', 'CAN_2']])
        self.assertEqual(len({stream['message_id'] for stream in plan['streams']}), 7)
        self.assertEqual(plan['streams'][-1]['receiver'], 'ECU_0')

    def test_single_bus_needs_no_gateway(self):
        plan = topology(2, 1)
        self.assertEqual(plan['gateway_links'], [])
        self.assertEqual(plan['bus_members']['CAN_0'], ['ECU_0', 'ECU_1'])


if __name__ == '__main__':
    unittest.main()
