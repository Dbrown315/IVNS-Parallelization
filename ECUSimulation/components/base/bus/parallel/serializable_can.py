"""Generator-free CAN timing state. No IVNS objects or MPI handles live here."""
from dataclasses import dataclass
import math

from SerializableSimpy.core import Environment


@dataclass(frozen=True)
class Transmission:
    started_at: float
    delay: float
    identifier: int
    length_bits: float


class SerializableCAN:
    """One independently checkpointable bus, owned by one worker rank.

    Only arbitration descriptors and transmission metadata cross the boundary;
    rank 0 retains payloads, ECU references, routing and monitoring.
    """

    def __init__(self):
        self.env = Environment()
        self.in_flight = None
        self.completed_at = None
        self.transmissions = 0

    @staticmethod
    def arbitrate(identifiers):
        # Python min preserves input order for equal identifiers, as StdCANBus does.
        return min(range(len(identifiers)), key=identifiers.__getitem__) if identifiers else None

    def begin(self, transmission):
        if self.in_flight is not None:
            raise ValueError("CAN bus already transmitting")
        start, delay = transmission.started_at, transmission.delay
        if not math.isfinite(start) or not math.isfinite(delay) or delay <= 0:
            raise ValueError("CAN start and positive delay must be finite")
        if start < self.env.now or not math.isfinite(start + delay):
            raise ValueError("CAN transmission would move time backwards or overflow")
        self.env.run(until=start)
        self.in_flight = transmission
        self.completed_at = None
        self.env.timeout(delay, self._complete, ())

    def _complete(self):
        self.completed_at = self.env.now
        self.in_flight = None
        self.transmissions += 1

    def finish(self):
        if self.in_flight is None:
            raise ValueError("CAN bus has no pending transmission")
        end = self.in_flight.started_at + self.in_flight.delay
        # SerializableSimpy 0.0.3 excludes callbacks exactly at run(until).
        # Step to the next representable float, then retain the actual event time.
        self.env.run(until=math.nextafter(end, math.inf))
        self.env.set_now(self.completed_at)
        return self.completed_at

    def transmit(self, transmission):
        self.begin(transmission)
        return self.finish()
