import gc
import utime
import machine
from machine import Pin

import uasyncio

from Suntime import Sun

from lenfer_controller import LenferController
from utils import manage_memory
from timers import Timer, time_tuple_to_seconds


class RelaySwitchController(LenferController):

    def __init__(self, device, conf):
        LenferController.__init__(self, device)
        self._conf = conf
        self.pin = Pin(conf['pin'], Pin.OUT)
        self.pin.off()
        self.timers = []
        self._schedule_params = None
        self._timers_param = None
        if 'schedule_params' in conf and conf['schedule_params']:
            self._schedule_params = conf['schedule_params']
            self._schedule_params_idx = [self.device.schedule.param_idx(param) for param in self._schedule_params]
        else:
            self._timers_param = conf['timers_param'] if 'timers_param' in conf else 'timers'
            self.init_timers()

    def init_timers(self):
        self.timers = []
        sun_data = None
        self.time_table = []
        if ('location' in self.device.settings and self.device.settings['location']
            and 'timezone' in self.device.settings and self.device.settings['timezone']):
            sun = Sun(self.device.settings['location'][0], self.device.settings['location'][1], 
                self.device.settings['timezone'])
            sun_data = [time_tuple_to_seconds(sun.get_sunrise_time(), sun=True), time_tuple_to_seconds(sun.get_sunset_time(), sun=True)]
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
        self.off(source=self.timers[timer_idx])
        if change_settings:
            del self.device.settings[self._timers_param][timer_idx]
        del self.timers[timer_idx]


    async def adjust_switch(self, once=False):
        while True:
            now = time_tuple_to_seconds(machine.RTC().datetime())
            if self._schedule_params:
                day = self.device.schedule.current_day()
                if day:
                    limits = [day[idx] if idx and day[idx] else None for idx in self._schedule_params_idx]
                    if limits[0] and ((limits[0] <= now and not limits[1]) or (limits[0] <= now < limits[1]) or (limits[0] < limits[1] <= now)):
                        if not self.pin.value():
                            self.pin.on()
                    if limits[1] and ((limits[1] <= now and not limits[0]) or (limits[1] <= now < limits[0]) or (limits[1] < limits[0] <= now)):
                        if self.pin.value():
                            self.pin.off()
            else:
                if now == 0:
                    self.init_timers()
                passed_timers = [timer for timer in self.timers if timer.time_on <= now]
                if not passed_timers:
                    passed_timers = [self.timers[-1]]
                if passed_timers:
                    last_state = passed_timers[-1].duration == 0
                    if last_state != self.pin.value():
                        self.pin.value(last_state)
            if once:
                break               
            manage_memory()
            await uasyncio.sleep(60 - machine.RTC().datetime()[6])

    def update_settings(self):
        if self._timers_param in self.device.settings:
            while self.timers:
                self.delete_timer(0, change_settings=False)
            self.init_timers() 

