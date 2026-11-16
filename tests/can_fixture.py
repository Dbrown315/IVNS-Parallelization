"""Deterministic fixture exercising the real CAN bus with recording receivers."""
import os
os.environ['IVNS_HEADLESS'] = '1'

from types import SimpleNamespace
from uuid import UUID
import simpy
from components.base.message.impl_bus_message_can import CANSegMessage
from components.base.message.abst_bus_message import SegData
from tools.general import General


def exercise(bus_class, *, filtered=False, delay=0.0002):
    env = simpy.Environment()
    bus = bus_class(env, 'CAN_TEST', 1_000_000)
    bus.SCB_GATHER_MSGS = 0.00001
    bus.SCB_GRAB_PRIO_MSG = 0
    bus.SCB_PROPAGATION_DELAY = 0
    bus.SCB_SENDING_TIME = delay
    bus.SCB_WRITE_TO_TRANSCEIVER_BUFFER = 0
    received = []
    gateway = UUID(int=7)
    ids = ['sender_a', 'sender_b', 'receiver', gateway]
    for ecu_id in ids:
        def receive(message, ecu_id=ecu_id):
            received.append((env.now, ecu_id, message.message_identifier,
                             message.sender_id, message.current_bus))
        bus.connect_ecu(SimpleNamespace(ecu_id=ecu_id, ecuHW=SimpleNamespace(
            transceiver=SimpleNamespace(get=receive))))
    general = General()
    old_filter, old_map = general.send_only_to_receivers, general.sender_receiver_map
    general.send_only_to_receivers = filtered
    general.sender_receiver_map = {s: {101: ['receiver'], 102: ['receiver']} for s in ids}
    winners = []

    def send(identifier, sender, at, gw_id=None):
        yield env.timeout(at)
        msg = CANSegMessage(env, identifier, SegData('data', 4), env.now, sender)
        msg.gw_id = gw_id
        ok = yield env.process(bus.put_message(msg))
        winners.append((sender, ok, env.now))
        if ok:
            yield bus.sync_send.get()

    env.process(bus.process())
    env.process(send(102, 'sender_a', 0))
    env.process(send(101, 'sender_b', 0))
    env.process(send(101, gateway, 0.001, [gateway]))
    try:
        env.run(until=0.002)
        return winners, received, bus.current_message, len(bus.sync_send.items)
    finally:
        general.send_only_to_receivers, general.sender_receiver_map = old_filter, old_map
