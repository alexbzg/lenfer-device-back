import gc
from machine import Pin, I2C, RTC

import uasyncio

from ds3231_port import DS3231

class RtcController:

    def __init__(self, conf, i2c_conf):
        i2c_rtc = i2c_conf[conf["i2c"]]
        self.i2c = I2C(-1, Pin(i2c_rtc["scl"], Pin.OPEN_DRAIN), Pin(i2c_rtc["sda"], Pin.OPEN_DRAIN))

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

    async def adjust_time(self):
        while True:
            self.get_time(set_rtc=True)
            await uasyncio.sleep(600)
            gc.collect()


def timer_minutes(entry):
    return int(entry['hr'])*60 + int(entry['mn'])

def timer_seconds(entry):
    return timer_minutes(entry)*60 + int(entry['sc'])

class Timer:

    def __init__(self, conf, relay):
        self.timer_type = conf['timer_type']
        self.time_on = timer_minutes(conf['conf']['on'])
        self.time_off = timer_minutes(conf['conf']['off'])
        self.relay = relay
        self.active = False
        if self.timer_type == 'interval':
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

    def on_off(self):
        uasyncio.get_event_loop().create_task(self.delayed_off())
        self.on()

    def check(self, time):
        if self.timer_type == 'standart':
            if self.time_on <= time < self.time_off:
                self.on()
            elif self.time_off == time and self.active:
                self.off()
        elif self.timer_type == 'interval':
            if self.time_on == time and self.period == 0:
                self.on_off()
            elif self.period and self.time_on <= time < self.time_off and not self.active and\
                ((time - self.time_on) % self.period) * 60 < self.period_off:
                self.on_off()
