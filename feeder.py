import gc
import machine
from machine import Pin
import lib.uasyncio as uasyncio
import utime
import logging

from gate_controller import GateController
from relay_switch import RelaySwitchController
from timers import Timer, time_tuple_to_seconds

from utils import manage_memory

LOG = logging.getLogger("Feeder")

class FeederTimer(Timer):

    def _on_off(self):
        uasyncio.get_event_loop().create_task(self.relay.run_for(self.duration))

class FeederController(GateController):

    def __init__(self, device, conf):
        GateController.__init__(self, device, conf)
        self._active = {}

    def on(self, value=True, source='manual', manual=False):
        if manual:
            source = 'manual'
        if value:            
            self._active[source] = True
        else:
            if source in self._active:
                del self._active[source]
        if self.state != bool(self._active):
            if self.state:
                self.reverse = False
            self.device.busy = self._active
            RelaySwitchController.on(self, self._active, source == 'manual')            
        if 'manual' in self._active and len(self._active) == 1 and self._power_monitor:
            uasyncio.get_event_loop().create_task(self.check_current())
        LOG.debug('Feeder state: %s' % self.state)
        manage_memory()

    def log_relay_switch(self, operation, source):
        RelaySwitchController.log_relay_switch(self, operation, source)

    def off(self, source='manual'):
        self.on(False, source)

    async def check_timers(self):
        off = None
        while True:
            time = time_tuple_to_seconds(machine.RTC().now())
            if time == 0:
                self.init_timers()
            for timer in self.timers:
                if timer.time_on <= time < timer.time_on + timer.duration:
                    start = utime.time()
                    now = start
                    prev_time = start
                    expired = time - timer.time_on
                    retries = 0
                    self.on(source=timer)

                    def continue_flag():
                        nonlocal retries, expired
                        if retries >= 3:
                            return False
                        if self._expired_limit and expired > self._expired_limit:
                            return False    
                        if timer.duration > 0 and expired > timer.duration:
                            return False
                        if self.flag_pins:
                            flag_pin = self.flag_pins[1 if self.reverse else 0]
                            if flag_pin.value():
                                self.device.append_log_entries("%s task success" % self._timers_param)
                                return False
                        return True

                    while continue_flag():
                        await uasyncio.sleep(1)
                        now = utime.time()
                        current = self._power_monitor.current() if self._power_monitor else None
                        if current:
                            self.log_current(current)
                        expired += now - prev_time
                        prev_time = now
                        if current and current > self._reverse_threshold:
                            await self.engine_reverse(True)
                            await uasyncio.sleep(self._reverse_duration)
                            expired -= self._reverse_duration + 2 * self._reverse_delay
                            retries += 1
                            await self.engine_reverse(False)
                    self.off(source=timer)
                if timer.time_on > time:
                    break
            manage_memory()
            await uasyncio.sleep(60 - machine.RTC().now()[6])

    def create_timer(self, conf):
        return FeederTimer(conf, self)

    def delete_timer(self, timer_idx, change_settings=True):
        self.off(source=self.timers[timer_idx])
        GateController.delete_timer(self, timer_idx, change_settings)

