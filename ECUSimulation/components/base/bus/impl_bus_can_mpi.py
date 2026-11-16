"""SimPy-facing adapter for the optional SerializableSimpy CAN service."""
from components.base.bus.impl_bus_can import StdCANBus


class MPICANBus(StdCANBus):
    def __init__(self, sim_env, bus_id, data_rate, avg_ecu_dist=2):
        # Lazy imports keep the standard installation free of MPI dependencies.
        from components.base.bus.parallel.mpi_can_runtime import get_runtime
        self.runtime = get_runtime()
        super().__init__(sim_env, bus_id, data_rate, avg_ecu_dist)

    def _get_highest_priority_msg(self, message_list):
        index = self.runtime.execute(self.comp_id, 'arbitrate',
                                     [m.message_identifier for m in message_list])
        return message_list[index] if index is not None else None

    def _wait_transmission_time_and_buffer(self):
        from components.base.bus.parallel.serializable_can import Transmission
        delay = self._transmission_delay()
        completed_at = self.runtime.execute(self.comp_id, 'transmit', Transmission(
            self.sim_env.now, delay, self.current_message.message_identifier,
            self.current_message_length_bit))
        if completed_at != self.sim_env.now + delay:
            raise RuntimeError("CAN worker returned an inconsistent completion time")
        # Yield the original delay to preserve SimPy's ordering and rounding.
        yield self.sim_env.timeout(delay)
        self._push_to_receivers()
        self.sync_send.put(True)
