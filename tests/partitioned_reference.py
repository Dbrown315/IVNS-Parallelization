"""Test-only monolithic reference: gateway snapshots are scheduled immediately.

No epoch buffering, with a single run-to-horizon on one rank. The communication
model is the new snapshot gateway model, not the old shared-object gateway.
"""
from pathlib import Path
import os
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
os.environ['IVNS_HEADLESS'] = '1'
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'ECUSimulation'))
from mpi4py import MPI
from main_lwa_param import parse_args
from components.base.bus.parallel import partitioned


class ImmediateExchange(partitioned.GatewayExchange):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lookahead = 0
        exchange = self

        class ImmediateInbox:
            def append(self, frame):
                exchange.inject([frame])

        self.outgoing = [ImmediateInbox()]

    def drain(self):
        return [[]]


if __name__ == '__main__':
    if MPI.COMM_WORLD.Get_size() != 1:
        raise SystemExit('Reference requires one rank')
    args = parse_args()
    args.sync_window = args.duration
    with patch.object(partitioned, 'GatewayExchange', ImmediateExchange):
        partitioned.run_partitioned(args)
