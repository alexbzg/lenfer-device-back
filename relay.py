import gc
from machine import Pin

import uasyncio

class Relay:

    def __init__(self, pin_no):
        self.pin = Pin(pin_no, Pin.OUT)
        self._active = {'timer': False, 'manual': False}
        gc.collect()

    def on(self, value=True, source='timer'):
        if self._active[source] != value:
            self._active[source] = value
            for state in self._active.values():
                if state:
                    self.pin.on()
                    gc.collect()
                    return
            self.pin.off()
            gc.collect()

    def off(self, source='timer'):
        self.on(False, source)
