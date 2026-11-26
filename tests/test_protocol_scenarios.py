from contextlib import redirect_stderr
import io
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from protocol_scenarios import parse_args, topology


class ProtocolScenariosTests(unittest.TestCase):
    def test_each_stream_stays_in_its_bus_cohort(self):
        for protocol in ('tesla', 'tls'):
            args = parse_args(protocol, ['--ecus', '7', '--buses', '3'])
            plan = topology(args)
            owner = {ecu: bus for bus, ecus in plan['bus_members'].items() for ecu in ecus}
            self.assertEqual(plan['gateway_links'], [])
            self.assertIsNone(plan['security_module'])
            self.assertEqual(len(plan['streams']), 7)
            for stream in plan['streams']:
                self.assertEqual(owner[stream['sender']], owner[stream['receiver']])
                self.assertNotEqual(stream['sender'], stream['receiver'])

    def test_reject_empty_cohort_and_exhausted_key_chain(self):
        for protocol, argv in [('tls', ['--ecus', '3', '--buses', '2']),
                               ('tesla', ['--key-chain-length', '2']),
                               ('tesla', ['--disclosure-delay', '0']),
                               ('tls', ['--payload-bytes', '0']),
                               ('tls', ['--duration', 'nan'])]:
            with self.subTest(protocol=protocol, argv=argv), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as exc:
                    parse_args(protocol, argv)
                self.assertEqual(exc.exception.code, 2)
