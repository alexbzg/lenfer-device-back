import machine
from machine import Pin
import logging

import lib.uasyncio as uasyncio

from Suntime import Sun

from lenfer_controller import LenferController
from utils import manage_memory
from timers import time_tuple_to_seconds, Timer

LOG = logging.getLogger("Relay")

class RelaySwitchController(LenferController):

    def __init__(self, device, conf):
        LenferController.__init__(self, device)
        self._conf = conf
        self.pin = Pin(conf['pin'], Pin.INOUT)
        self.pin.value(0)
        self.timers = []
        self._schedule_params = None
        self._timers_param = None
        self._pulse_interval = conf.get('pulse_interval')
        self._pulse_length = conf.get('pulse_length')
        if conf.get('schedule_params'):
            self._schedule_params = conf['schedule_params']
            self._schedule_params_idx = [self.device.schedule.param_idx(param) for param in self._schedule_params]
        else:
            self._timers_param = conf.get('timers_param') or 'timers'
            self.init_timers()
        if self._pulse_length:
            self._on = False
            uasyncio.get_event_loop().create_task(self.pulse_task())
        self._log_prop_name = conf.get('log_prop_name') or self._timers_param
        
    async def pulse_task(self):
        while True:
            if self._on:
                self.pin.value(1)
                await uasyncio.sleep_ms(self._pulse_length)
                self.pin.value(0)
            await uasyncio.sleep(self._pulse_interval)
    
    def create_timer(self, conf):
        return Timer(conf, self)

    @property
    def state(self):
        return self._on if self._pulse_interval else self.pin.value()

    @state.setter
    def state(self, value):
        self.on(value=value)

    def init_timers(self):
        self.timers = []
        sun_data = None
        self.time_table = []
        if self.device.settings.get('location') and self.device.settings.get('timezone'):
            sun = Sun(self.device.settings['location'][0], self.device.settings['location'][1], 
                self.device.settings['timezone'])
            sun_data = [time_tuple_to_seconds(sun.get_sunrise_time()), time_tuple_to_seconds(sun.get_sunset_time())]
        for timer_conf in self.device.settings[self._timers_param]:
            timer = self.create_timer(timer_conf)
            if timer.sun:
                if sun_data:
                    time_on = sun_data[0 if timer.sun == 1 else 1] + timer.time_on
                    timer.time_on = time_on
                else:
                    continue
            self.timers.append(timer)
            
        self.timers.sort(key=lambda timer: timer.time_on)
        logging.info(self.timers)

    def delete_timer(self, timer_idx, change_settings=True):
        if change_settings:
            del self.device.settings[self._timers_param][timer_idx]
        del self.timers[timer_idx]

    def on(self, value=True, manual=False):
        if self.state != value:
            if self._pulse_length:
                self._on = value
            else:
                self.pin.value(value)
            self.log_relay_switch('start' if value else 'stop', 'manual' if manual else 'timer')
        manage_memory()

    def log_relay_switch(self, operation, source):
        self.device.append_log_entries("%s %s %s" % (
            self._log_prop_name,
            operation,
            source
        ))

    def off(self):
        self.on(False)    

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
                        self.on()
                    if limits[1] and ((limits[1] <= now and not limits[0]) or (limits[1] <= now < limits[0]) or (limits[1] < limits[0] <= now)):
                        self.off()
            else:
                if now == 0:
                    self.init_timers()
                passed_timers = [timer for timer in self.timers if timer.time_on <= now]
                if not passed_timers and self.timers:
                    passed_timers = [self.timers[-1]]
                if passed_timers:
                    last_timer = passed_timers[-1]
                    self.on(last_timer.duration == 0)
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

    def update_settings(self):
        if self._timers_param in self.device.settings:
            while self.timers:
                self.delete_timer(0, change_settings=False)
            self.init_timers() 

