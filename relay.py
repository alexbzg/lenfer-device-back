import gc
from machine import Pin
import machine

import uasyncio

from timers import Timer
from lenfer_controller import LenferController

class RelaysController(LenferController):

    def __init__(self, device, conf):
        LenferController.__init__(self, device)
        self.pin = Pin(conf['pin'], Pin.OUT)
        self.pin.off()
        self._conf = conf
        self._active = {'timer': False, 'manual': False}

        self.timers = []
        for timer_conf in conf['timers']:
            self.timers.append(self.create_timer(timer_conf))

        self.button = Pin(conf['button'], Pin.IN) if conf["button"] else None

        if self.button:
            self.button.irq(self.button_irq_hndlr)

    def init_timers(self, conf):
        self.timers = []
        self._conf['timers'] = conf
        for timer_conf in conf:
            self.timers.append(self.create_timer(timer_conf))

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

    def button_irq_hndlr(self, pin):
        self.on(value=not self.button.value(), source='manual')
        gc.collect()

    def create_timer(self, conf):
        return Timer(conf, self)

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
            time = time_tuple[4]*3600 + time_tuple[5]*60
            for timer in self.timers:
                timer.check(time)
            gc.collect()
            await uasyncio.sleep(60)

    def get_updates_props(self):
        return {'timers': self._conf['timers']}

    def set_updates_props(self, data):
        if 'timers' in data:
            while self.timers:                
                self.delete_timer(0)
            self.init_timers(data['timers'])