# ds3231_port.py Portable driver for DS3231 precison real time clock.
# Adapted from WiPy driver at https://github.com/scudderfish/uDS3231

# Author: Peter Hinch
# Copyright Peter Hinch 2018 Released under the MIT license.
import sys

import utime
import machine

DS3231_I2C_ADDR = 104

try:
    rtc = machine.RTC()
except:
    print('Warning: machine module does not support the RTC.')
    rtc = None

def bcd2dec(bcd):
    return (((bcd & 0xf0) >> 4) * 10 + (bcd & 0x0f))

def dec2bcd(dec):
    tens, units = divmod(dec, 10)
    return (tens << 4) + units

def tobytes(num):
    return num.to_bytes(1, 'little')

class DS3231:
    def __init__(self, i2c):
        self.ds3231 = i2c
        self.timebuf = bytearray(7)
        if DS3231_I2C_ADDR not in self.ds3231.scan():
            raise RuntimeError("DS3231 not found on I2C bus at %d" % DS3231_I2C_ADDR)

    def get_time(self, set_rtc=False):
        if set_rtc:
            self.await_transition()  # For accuracy set RTC immediately after a seconds transition
        else:
            self.ds3231.readfrom_mem_into(DS3231_I2C_ADDR, 0, self.timebuf) # don't wait
        return self.convert(set_rtc)

    def convert(self, set_rtc=False):  # Return a tuple in localtime() format (less yday)
        data = self.timebuf
        ss = bcd2dec(data[0])
        mm = bcd2dec(data[1])
        if data[2] & 0x40:
            hh = bcd2dec(data[2] & 0x1f)
            if data[2] & 0x20:
                hh += 12
        else:
            hh = bcd2dec(data[2])
        wday = data[3]
        DD = bcd2dec(data[4])
        MM = bcd2dec(data[5] & 0x1f)
        YY = bcd2dec(data[6])
        if data[5] & 0x80:
            YY += 2000
        else:
            YY += 1900
        # Time from DS3231 in time.localtime() format (less yday)
        result = YY, MM, DD, hh, mm, ss, wday -1, 0
        if set_rtc:
            if rtc is None:
                # Best we can do is to set local time
                secs = utime.mktime(result)
                utime.localtime(secs)
            else:
                rtc.init((YY, MM, DD, hh, mm, ss))
        return result

    def save_time(self):
        (YY, MM, mday, hh, mm, ss, wday, yday) = utime.localtime()  # Based on RTC
        self.ds3231.writeto_mem(DS3231_I2C_ADDR, 0, tobytes(dec2bcd(ss)))
        self.ds3231.writeto_mem(DS3231_I2C_ADDR, 1, tobytes(dec2bcd(mm)))
        self.ds3231.writeto_mem(DS3231_I2C_ADDR, 2, tobytes(dec2bcd(hh)))  # Sets to 24hr mode
        self.ds3231.writeto_mem(DS3231_I2C_ADDR, 3, tobytes(dec2bcd(wday + 1)))  # 1 == Monday, 7 == Sunday
        self.ds3231.writeto_mem(DS3231_I2C_ADDR, 4, tobytes(dec2bcd(mday)))  # Day of month
        if YY >= 2000:
            self.ds3231.writeto_mem(DS3231_I2C_ADDR, 5, tobytes(dec2bcd(MM) | 0b10000000))  # Century bit
            self.ds3231.writeto_mem(DS3231_I2C_ADDR, 6, tobytes(dec2bcd(YY-2000)))
        else:
            self.ds3231.writeto_mem(DS3231_I2C_ADDR, 5, tobytes(dec2bcd(MM)))
            self.ds3231.writeto_mem(DS3231_I2C_ADDR, 6, tobytes(dec2bcd(YY-1900)))

    # Wait until DS3231 seconds value changes before reading and returning data
    def await_transition(self):
        self.ds3231.readfrom_mem_into(DS3231_I2C_ADDR, 0, self.timebuf)
        ss = self.timebuf[0]
        while ss == self.timebuf[0]:
            self.ds3231.readfrom_mem_into(DS3231_I2C_ADDR, 0, self.timebuf)
        return self.timebuf

    # Test hardware RTC against DS3231. Default runtime 10 min. Return amount
    # by which DS3231 clock leads RTC in PPM or seconds per year.
    # Precision is achieved by starting and ending the measurement on DS3231
    # one-seond boundaries and using ticks_ms() to time the RTC.
    # For a 10 minute measurement +-1ms corresponds to 1.7ppm or 53s/yr. Longer
    # runtimes improve this, but the DS3231 is "only" good for +-2ppm over 0-40C.
    def rtc_test(self, runtime=600, ppm=False, verbose=True):
        if rtc is None:
            raise RuntimeError('machine.RTC does not exist')
        verbose and print('Waiting {} minutes for result'.format(runtime//60))
        factor = 1000000 if ppm else 114155200  # seconds per year

        self.await_transition()  # Start on transition of DS3231. Record time in .timebuf
        t = utime.ticks_ms()  # Get system time now
        ss = rtc.datetime()[5]  # Seconds from system RTC
        while ss == rtc.datetime()[5]:
            pass
        ds = utime.ticks_diff(utime.ticks_ms(), t)  # ms to transition of RTC
        ds3231_start = utime.mktime(self.convert())  # Time when transition occurred
        t = rtc.datetime()
        rtc_start = utime.mktime((t[0], t[1], t[2], t[4], t[5], t[6], t[3] - 1, 0))  # y m d h m s wday 0

        utime.sleep(runtime)  # Wait a while (precision doesn't matter)

        self.await_transition()  # of DS3231 and record the time
        t = utime.ticks_ms()  # and get system time now
        ss = rtc.now()[5]  # Seconds from system RTC
        while ss == rtc.now()[5]:
            pass
        de = utime.ticks_diff(utime.ticks_ms(), t)  # ms to transition of RTC
        ds3231_end = utime.mktime(self.convert())  # Time when transition occurred
        t = rtc.now()
        rtc_end = utime.mktime((t[0], t[1], t[2], t[3], t[4], t[5]))  # y m d h m s wday 0

        d_rtc = 1000 * (rtc_end - rtc_start) + de - ds  # ms recorded by RTC
        d_ds3231 = 1000 * (ds3231_end - ds3231_start)  # ms recorded by DS3231
        ratio = (d_ds3231 - d_rtc) / d_ds3231
        ppm = ratio * 1000000
        verbose and print('DS3231 leads RTC by {:4.1f}ppm {:4.1f}mins/yr'.format(ppm, ppm*1.903))
        return ratio * factor
