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
        if conf.get('schedule_params'):
            self._schedule_params = conf['schedule_params']
            self._schedule_params_idx = [self.device.schedule.param_idx(param) for param in self._schedule_params]
        else:
            self._timers_param = conf['timers_param'] if 'timers_param' in conf else 'timers'
            self.init_timers()
    
    def create_timer(self, conf):
        return Timer(conf, self)

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

    def delete_timer(self, timer_idx, change_settings=True):
        if change_settings:
            del self.device.settings[self._timers_param][timer_idx]
        del self.timers[timer_idx]

    def on(self, value=True):
        if self.pin.value() != value:
            if self.pin.value():
                self.pin.value(0)
                self.device.append_log_entries("Feeder stop timer")                
            else:
                self.pin.value(1)
                self.device.append_log_entries("Feeder start timer")
        manage_memory()

    def off(self):
        self.on(False)    

    async def adjust_switch(self, once=False):
        while True:
            now = time_tuple_to_seconds(machine.RTC().now())
            next_time_on = None
            if self._schedule_params:
                day = self.device.schedule.current_day()
                if day:
                    limits = [day[idx] if idx and day[idx] else None for idx in self._schedule_params_idx]
                    if limits[0] and ((limits[0] <= now and not limits[1]) or (limits[0] <= now < limits[1]) or (limits[0] < limits[1] <= now)):
                        if not self.pin.value():
                            self.pin.value(1)
                    if limits[1] and ((limits[1] <= now and not limits[0]) or (limits[1] <= now < limits[0]) or (limits[1] < limits[0] <= now)):
                        if self.pin.value():
                            self.pin.value(0)
            else:
                if now == 0:
                    self.init_timers()
                passed_timers = [timer for timer in self.timers if timer.time_on <= now]
                if not passed_timers and self.timers:
                    passed_timers = [self.timers[-1]]
                if passed_timers:
                    last_timer = passed_timers[-1]
                    last_state = last_timer.duration == 0
                    if last_state != self.pin.value():
                        self.on(last_state)
                    next_timers = [timer for timer in self.timers if timer.time_on > now]
                    if next_timers and next_timers[0].time_on - last_timer.time_on < 60:
                        next_time_on = next_timers[0].time_on - last_timer.time_on
            if once:
                break               
            manage_memory()
            if next_time_on:
                await next_time_on
            else:    
                await uasyncio.sleep(60 - machine.RTC().now()[5])

    def update_settings(self):
        if self._timers_param in self.device.settings:
            while self.timers:
                self.delete_timer(0, change_settings=False)
            self.init_timers() 

