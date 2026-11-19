from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ECUSimulation'))
import run_mpi_headless
from components.base.bus.parallel import mpi_can_runtime


class MPILauncherTests(unittest.TestCase):
    def test_legacy_normal_exit_does_not_skip_worker_error_check(self):
        comm = Mock()
        comm.Get_size.return_value = 2
        comm.Get_rank.return_value = 0
        runtime = Mock(errors=['worker rejected a transmission'])
        fake_mpi = SimpleNamespace(MPI=SimpleNamespace(COMM_WORLD=comm))
        with patch.dict(sys.modules, {'mpi4py': fake_mpi}), \
                patch.dict(run_mpi_headless.os.environ), \
                patch.object(mpi_can_runtime, 'MPICANRuntime', return_value=runtime), \
                patch.object(run_mpi_headless.runpy, 'run_path', side_effect=SystemExit(None)):
            with self.assertRaisesRegex(RuntimeError, 'worker rejected a transmission'):
                run_mpi_headless.main()
        runtime.close.assert_called_once()
        self.assertIsNone(mpi_can_runtime._runtime)


if __name__ == '__main__':
    unittest.main()
