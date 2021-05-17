import gc
from machine import Pin
import machine

import uasyncio
import ulogging

from utils import manage_memory
from timers import Timer, time_tuple_to_seconds
from lenfer_controller import LenferController

LOG = ulogging.getLogger("Main")

class RelaysController(LenferController):

    def __init__(self, device, conf):
        LenferController.__init__(self, device)
        self.pin = Pin(conf['pin'], Pin.OUT)
        self.pin.off()
        self._conf = conf
        self._active = {'timer': False, 'manual': False}

        self.timers = []
        for timer_conf in device.settings['timers']:
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
        self.device.settings['timers'][timer_idx] = timer_conf
        self.timers[timer_idx] = self.create_timer(timer_conf)
    
    def delete_timer(self, timer_idx, change_settings=True):
        self.timers[timer_idx].off()
        if change_settings:
            del self.device.settings['timers'][timer_idx]
        del self.timers[timer_idx]

    async def check_timers(self):
        off = None
        while True:
            time = time_tuple_to_seconds(machine.RTC().datetime())
            for timer in self.timers:
                if timer.time_on == time:
                    self.on()
                    off = (timer, time + timer.duration)
                    break
                if timer.time_on > time:
                    break
            if off and off[1] - time < 60:
                await uasyncio.sleep(off[1] - time)
                self.off()
                off = None
            manage_memory()
            await uasyncio.sleep(60 - machine.RTC().datetime()[6])

    def update_settings(self):
        if 'timers' in self.device.settings:
            while self.timers:
                self.delete_timer(0, change_settings=False)
            self.init_timers(self.device.settings['timers']) 