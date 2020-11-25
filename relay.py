import gc
from machine import Pin
import machine

import uasyncio

from timers import Timer
from lenfer_controller import LenferController

class Relay:

    def __init__(self, pin_no):
        self.pin = Pin(pin_no, Pin.OUT)
        self._active = {'timer': False, 'manual': False}

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

class RelaysController(LenferController):

    def __init__(self, conf):
        LenferController.__init__(self)
        self.relays = [Relay(pin_no) for pin_no in conf["relays"]]
        self._conf = conf

        self.timers = []
        for timer_conf in conf['timers']:
            self.timers.append(self.create_timer(timer_conf))

        self.buttons = [Pin(pin_no, Pin.IN) for pin_no in conf["buttons"]]

        for idx in range(len(self.buttons)):
            self.set_relay_button_irq(idx)

    def create_timer(self, conf):
        return Timer(conf, self.relays[0])

    def set_relay_button_irq(self, idx):

        def handler(pin):
            self.relays[idx].on(value=not self.buttons[idx].value(), source='manual')
            gc.collect()

        self.buttons[idx].irq(handler)

    def add_timer(self, timer_conf):
        self.timers.append(self.create_timer(timer_conf))
        self._conf['timers'].append(timer_conf)

    def update_timer(self, timer_idx, timer_conf):
        self.timers[timer_idx].off()
        self._conf['timers'][timer_idx] = timer_conf
        self.timers[timer_idx] = self.create_timer(timer_conf)
    
    def delete_timer(self, timer_idx):
        self.timers[timer_idx].off()
        del self._conf['timers'][timer_idx]
        del self.timers[timer_idx]

    async def check_timers(self):
        while True:
            time_tuple = machine.RTC().datetime()
            time = time_tuple[4]*60 + time_tuple[5]
            for timer in self.timers:
                timer.check(time)
            gc.collect()
            await uasyncio.sleep(60)
