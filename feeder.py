from machine import Pin, I2C, RTC
import uasyncio
import utime

from ina219 import INA219

from relay import RelaysController
from timers import Timer

class PowerMonitor:

    def __init__(self, conf, _i2c):
        i2c = _i2c[conf["i2c"]]
        self._ina219 = INA219(conf["shunt_ohms"], I2C(scl=Pin(i2c["scl"]), sda=Pin(i2c["sda"])))
        self._ina219.configure()

    def voltage(self):
        return self._ina219.voltage()

    def current(self):
        return self._ina219.current()

class FeederTimer(Timer):

    def on_off(self):
        uasyncio.get_event_loop().create_task(self.relay.run_for(self.duration))

class FeederController(RelaysController):

    def __init__(self, device, conf, i2c):

        RelaysController.__init__(self, device, conf['relay'])
        self._power_monitor = PowerMonitor(conf['power_monitor'], i2c)
        self._reverse = Pin(conf['reverse'], Pin.OUT)
        self._delay = 0

    @property
    def state(self):
        return self.pin.value()

    @state.setter
    def state(self, value):
        self.on(value=value)

    def on(self, value=True, source='timer'):
        if self.state != value:
            RelaysController.on(self, value, source)
            self.device.post_log("Feeder: {0} Reverse: {1}".format(self.state, self.reverse))

    async def run_for(self, duration):
        start = utime.time()
        now = start
        expired = 0
        retries = 0
        self.on()
        while now - start < duration and retries < 3:
            await uasyncio.sleep(1)
            now = utime.time()
            cur = self._power_monitor.current()
            self.device.post_log("Feeder current: {0:+.2f}".format(cur))
            expired = now - start
            if cur > 1000:
                self.device.post_log("Feeder reverse")
                self.engine_reverse(True)
                await uasyncio.sleep(5)
                expired -= 5
                retries += 1
                self.engine_reverse(False)
                self.device.post_log("Feeder resume")
        self.off()

    def engine_reverse(self, reverse):
        self.pin.value(False)
        self.reverse = reverse
        self.pin.value(True)

    def create_timer(self, conf):
        return FeederTimer(conf, self)

    @property
    def reverse(self):
        return self._reverse.value()

    @reverse.setter
    def reverse(self, value):
        self._reverse.value(value)
