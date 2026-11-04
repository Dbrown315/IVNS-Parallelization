"""Synchronous signals for explicitly selected headless execution."""
import os
if os.environ.get('IVNS_HEADLESS') != '1':
    from PyQt4.Qt import QObject
    from PyQt4 import QtCore
else:
    class QObject:
        pass
    class Signal:
        def __init__(self, *args):
            self.name = None
        def __set_name__(self, owner, name):
            self.name = '_signal_' + name
        def __get__(self, obj, owner):
            if obj is None:
                return self
            if self.name not in obj.__dict__:
                obj.__dict__[self.name] = BoundSignal()
            return obj.__dict__[self.name]
    class BoundSignal:
        def __init__(self):
            self.slots = []
        def connect(self, slot):
            self.slots.append(slot)
        def emit(self, *args):
            for slot in self.slots:
                slot(*args)
    class QtCore:
        pyqtSignal = Signal
