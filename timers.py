import gc
from machine import Pin, I2C, RTC

import uasyncio
import ulogging

from ds3231_port import DS3231

from lenfer_controller import LenferController

LOG = ulogging.getLogger("Main")

class RtcController(LenferController):

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
        self.time_on = conf['on']
        self.time_off = conf['off'] if 'off' in conf else None
        self.duration = conf['duration'] if 'duration' in conf else None
        self.period = conf['period'] if 'period' in conf else None
        self.relay = relay
        self.active = False

    def on(self, value=True):
        self.active = value
        if value:
            self.relay.on()
        else:
            self.relay.off()

    def off(self):
        self.on(False)

    async def delayed_off(self):
        await uasyncio.sleep(self.duration)
        self.off()

    def on_off(self):
        uasyncio.get_event_loop().create_task(self.delayed_off())
        self.on()

    def check(self, time):
        if self.duration:
            if self.time_on == time and not self.period:
                self.on_off()
            elif self.period and self.time_on <= time < self.time_off and not self.active and\
                ((time - self.time_on) % self.period) * 60 < self.duration:
                self.on_off()
        else:
            if self.time_on <= time < self.time_off:
                self.on()
            elif self.time_off == time and self.active:
                self.off()
