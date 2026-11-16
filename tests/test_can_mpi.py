import os
from pathlib import Path
import pickle
import sys
import unittest

os.environ['IVNS_HEADLESS'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ECUSimulation'))
from components.base.bus.parallel.serializable_can import SerializableCAN, Transmission
from components.base.bus.parallel.mpi_can_runtime import CANService, install_runtime
from components.base.bus.impl_bus_can import StdCANBus
from components.base.bus.impl_bus_can_mpi import MPICANBus
from can_fixture import exercise


class SerializableCANTests(unittest.TestCase):
    def test_arbitration_empty_and_stable_ties(self):
        self.assertIsNone(SerializableCAN.arbitrate([]))
        self.assertEqual(SerializableCAN.arbitrate([102, 101, 101]), 1)

    def test_checkpoint_pending_callback_and_resume(self):
        bus = SerializableCAN()
        bus.begin(Transmission(2, 0.25, 101, 74))
        restored = pickle.loads(pickle.dumps(bus))
        self.assertEqual(restored.finish(), 2.25)
        self.assertEqual(restored.transmissions, 1)
        self.assertIsNone(restored.in_flight)
        self.assertEqual(restored.transmit(Transmission(2.25, 0.25, 102, 74)), 2.5)
        self.assertEqual(bus.transmissions, 0)

    def test_invalid_times_and_overlapping_transmissions(self):
        for start, delay in [(0, 0), (0, -1), (float('nan'), 1), (0, float('inf'))]:
            with self.assertRaises(ValueError):
                SerializableCAN().begin(Transmission(start, delay, 101, 74))
        bus = SerializableCAN()
        bus.begin(Transmission(0, 1, 101, 74))
        with self.assertRaises(ValueError):
            bus.begin(Transmission(0.5, 1, 102, 74))
        bus.finish()
        with self.assertRaises(ValueError):
            bus.begin(Transmission(0.5, 1, 102, 74))

    def test_independent_bus_clocks(self):
        service = CANService()
        self.assertEqual(service.execute('a', 'transmit', Transmission(10, 1, 101, 74)), 11)
        self.assertEqual(service.execute('b', 'transmit', Transmission(0, 1, 101, 74)), 1)

    def test_serial_adapter_parity(self):
        install_runtime(CANService())
        try:
            for filtered in (False, True):
                for delay in (0, 0.0002):
                    # Each fixture starts fresh simulated time and needs fresh worker state.
                    install_runtime(None)
                    install_runtime(CANService())
                    with self.subTest(filtered=filtered, delay=delay):
                        expected = exercise(StdCANBus, filtered=filtered, delay=delay)
                        actual = exercise(MPICANBus, filtered=filtered, delay=delay)
                        self.assertEqual(actual, expected)
                        self.assertEqual([w[1] for w in actual[0]], [False, True, True])
                        self.assertTrue(actual[1])
                        self.assertIsNone(actual[2])
                        self.assertEqual(actual[3], 0)
        finally:
            install_runtime(None)


if __name__ == '__main__':
    unittest.main()
