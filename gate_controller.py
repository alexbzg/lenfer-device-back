import machine
from machine import Pin
import logging
import utime

import lib.uasyncio as uasyncio

from Suntime import Sun

from relay_switch import RelaySwitchController
from utils import manage_memory
from timers import time_tuple_to_seconds, Timer

LOG = logging.getLogger("Relay")

class GateController(RelaySwitchController):

    def __init__(self, device, conf):
        RelaySwitchController.__init__(self, device, conf)
        self._power_monitor = None
        if conf.get('power_monitor'): 
            manage_memory()
            from power_monitor import PowerMonitor
            try: 
                self._power_monitor = PowerMonitor(conf['power_monitor'], device.i2c)
            except Exception as exc:
                LOG.exc(exc, 'Power monitor init error')

        self._reverse = Pin(conf['reverse'], Pin.INOUT)
        self.reverse = False
        self._reverse_threshold = device.settings.get('reverse_threshold')
        self._reverse_duration = device.settings.get('reverse_duration')
        self._expired_limit = device.settings.get('expired_limit')
        self._reverse_delay = 2       
        self._delay = 0
        self.flag_pins = None
        if conf.get('buttons'):
            self._buttons = []
            for idx, pin in enumerate(conf['buttons']):
                reverse = bool(idx)
                self._buttons.append(Pin(pin, Pin.IN, Pin.PULL_UP, 
                    handler=self.on_button_reverse if reverse else self.on_button, trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING))
        if conf.get('flag_pins'):
            self.flag_pins = [Pin(pin, Pin.IN, Pin.PULL_UP) for pin in conf['flag_pins']]

    @property
    def state(self):
        return self.pin.value()

    @state.setter
    def state(self, value):
        self.on(value=value)         

    @property
    def gate_state(self):
        #0 - closed, 1 - open, None - unknown
        if self.flag_pins:
            for idx, flag_pin in enumerate(self.flag_pins):
                if flag_pin.value() == 0:
                    return 0 if idx == 1 else 1
        return None                    

    async def set_gate_state(self, value):
        if self.gate_state != value:
            self.reverse = 1 if value else 0
            expired = 0
            retries = 0
            prev_time = utime.time()
            self.on()

            def continue_flag():
                nonlocal retries, expired
                if retries >= 3:
                    return False
                if self._expired_limit and expired > self._expired_limit:
                    return False    
                if self.flag_pins:
                    flag_pin = self.flag_pins[0 if self.reverse else 1]
                    if flag_pin.value() == 0:
                        self.device.append_log_entries("%s task success" % self._timers_param)
                        return False
                return True

            while continue_flag():
                await uasyncio.sleep(1)
                now = utime.time()
                expired += now - prev_time
                prev_time = now
                if self._power_monitor and self._reverse_threshold:
                    current = self._power_monitor.current()
                    if current:
                        self.log_current(current)
                        if current > self._reverse_threshold:
                            await self.engine_reverse()
                            await uasyncio.sleep(self._reverse_duration)
                            expired -= self._reverse_duration + 2 * self._reverse_delay
                            retries += 1
                            await self.engine_reverse()
            self.off()

    @state.setter
    def state(self, value):
        self.on(value=value)         

    def on_button_reverse(self, pin):
        self.on_button(pin, True)

    def on_button(self, pin, reverse=False):
        print('button {0} {1} {2}'.format(
            pin, pin.value(), 'reverse' if reverse else ''
        ))
        if pin.value():
            self.on(False, 'manual')
        else:
            self.reverse = reverse
            self.on(True, 'manual')

    async def check_current(self):
        if self._power_monitor:
            while self.state:
                cur = self._power_monitor.current()
                self.log_current(cur)
                await uasyncio.sleep(1)

    def log_current(self, cur):
        self.device.append_log_entries("{0} current: {1:+.2f}".format(self._timers_param, cur))

    async def adjust_switch(self, once=False):
        while True:
            now_tuple = machine.RTC().now()     
            now = time_tuple_to_seconds(now_tuple, seconds=True)
            next_time_on = None
            if self._schedule_params:
                day = self.device.schedule.current_day()
                if day:
                    limits = [day[idx] if idx and day[idx] else None for idx in self._schedule_params_idx]
                    if limits[0] and ((limits[0] <= now and not limits[1]) or (limits[0] <= now < limits[1]) or (limits[0] < limits[1] <= now)):
                        self.set_gate_state(1)
                    if limits[1] and ((limits[1] <= now and not limits[0]) or (limits[1] <= now < limits[0]) or (limits[1] < limits[0] <= now)):
                        self.set_gate_state(0)
            else:
                if now == 0:
                    self.init_timers()
                passed_timers = [timer for timer in self.timers if timer.time_on <= now]
                if not passed_timers and self.timers:
                    passed_timers = [self.timers[-1]]
                if passed_timers:
                    last_timer = passed_timers[-1]
                    await self.set_gate_state(1 if last_timer.duration == 0 else 0)
                    next_timers = [timer for timer in self.timers if timer.time_on > now]
                    if next_timers and last_timer.time_on < next_timers[0].time_on < last_timer.time_on + 60:
                        next_time_on = next_timers[0].time_on - last_timer.time_on
            if once:
                break               
            manage_memory()
            if next_time_on:
                await uasyncio.sleep(next_time_on)
            else:    
                await uasyncio.sleep(60 - machine.RTC().now()[5])

    async def engine_reverse(self):
        self.device.append_log_entries("%s engine reverse" % self._timers_param)
        self.pin.value(0)
        await uasyncio.sleep(self._reverse_delay)
        self.reverse = 0 if self.reverse else 1
        await uasyncio.sleep(self._reverse_delay)
        self.pin.value(1)

    @property
    def reverse(self):
        return self._reverse.value()

    def update_settings(self):
        RelaySwitchController.update_settings(self)
        if 'reverse_threshold' in self.device.settings:
            self._reverse_threshold = self.device.settings['reverse_threshold']
        if 'reverse_duration' in self.device.settings:
            self._reverse_duration = self.device.settings['reverse_duration']
        if 'expired_limit' in self.device.settings:
            self._expired_limit = self.device.settings['expired_limit']

    @reverse.setter
    def reverse(self, value):
        if value != self.reverse:            
            self._reverse.value(value)
