import gc
from machine import Pin, I2C, RTC

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