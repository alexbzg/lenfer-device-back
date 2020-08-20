import gc
from machine import Pin, I2C, RTC

import uasyncio

from ds3231_port import DS3231

class RtcController:

    def __init__(self, scl_pin_no=0, sda_pin_no=2):
        self.i2c = I2C(-1, Pin(scl_pin_no, Pin.OPEN_DRAIN), Pin(sda_pin_no, Pin.OPEN_DRAIN))

    def get_time(self, set_rtc=False):
        ds3231 = DS3231(self.i2c)
        ds3231.get_time(set_rtc=set_rtc)

    def save_time(self):
        ds3231 = DS3231(self.i2c)
        ds3231.save_time()

    def set_time(self, datetime_tuple):
        rtc = RTC()
        rtc.init(datetime_tuple)
        self.save_time()

def timer_minutes(entry):
    return int(entry['hr'])*60 + int(entry['mn'])

def timer_seconds(entry):
    return timer_minutes(entry)*60 + int(entry['sc'])

class Timer:

    def __init__(self, conf, relay_pin_no):
        self.timer_type = conf['timer_type']
        self.time_on = timer_minutes(conf['conf']['on'])
        self.time_off = timer_minutes(conf['conf']['off'])
        self.relay = Pin(relay_pin_no, Pin.OUT)
        self.active = False
        if (self.timer_type == 'interval'):
            self.period = timer_minutes(conf['conf']['period'])
            self.period_off = timer_seconds(conf['conf']['period_off'])

    def on(self, value=True):
        self.active = value
        if value:
            self.relay.on()
        else:
            self.relay.off()

    def off(self):
        self.on(False)

    async def delayed_off(self):
        await uasyncio.sleep(self.period_off)
        self.off()

    def check(self, time):
        if self.timer_type == 'standart':
            if self.time_on <= time and self.time_off > time:
                self.on()
            elif self.time_off == time and self.active:
                self.off()
        elif self.timer_type == 'interval':
            if self.time_on <= time and self.time_off > time and not self.active:
                if self.period == 0 and self.time_on == time:
                    self.on()
                elif ((time - self.time_on) % self.period) * 60 < self.period_off:
                    uasyncio.get_event_loop().create_task(self.delayed_off())
                    self.on()
