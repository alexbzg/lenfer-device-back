from machine import RTC

import lib.uasyncio as uasyncio
import lib.ulogging as ulogging

from lenfer_controller import LenferController
from utils import manage_memory

LOG = ulogging.getLogger("Main")

class RtcController(LenferController):

    def __init__(self, device, conf):
        LenferController.__init__(self, device)
        self.i2c = device.i2c[conf["i2c"]]

    def get_time(self, set_rtc=False):
        from ds3231_port import DS3231
        ds3231 = DS3231(self.i2c)
        ds3231.get_time(set_rtc=set_rtc)

    def save_time(self):
        from ds3231_port import DS3231
        ds3231 = DS3231(self.i2c)
        ds3231.save_time()

    def set_time(self, datetime_tuple):
        rtc = RTC()
        rtc.init(datetime_tuple)
        self.save_time()

    async def adjust_time(self, once=False):
        while True:
            self.get_time(set_rtc=True)
            if once:
                break
            await uasyncio.sleep(600)
            manage_memory()


def timer_minutes(entry):
    return int(entry['hr'])*60 + int(entry['mn'])

def timer_seconds(entry):
    return timer_minutes(entry)*60 + int(entry['sc'])

def time_tuple_to_seconds(time_tuple):
    return time_tuple[3]*3600 + time_tuple[4]*60

class Timer:

    def __init__(self, conf, relay):
        self.time_on = conf['on']
        self.time_off = conf['off'] if 'off' in conf else None
        self.duration = conf['duration'] if 'duration' in conf else None
        self.period = conf['period'] if 'period' in conf else None
        self.sun = conf['sun'] if 'sun' in conf else 0
        self.relay = relay
        self.active = False

    def on(self, value=True):
        self.active = value
        if value:
            self.relay.value(1)
        else:
            self.relay.value(0)

    def off(self):
        self.on(False)

    def on_off(self):
        self.on()
        uasyncio.get_event_loop().call_later(self.duration, self.off)

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
