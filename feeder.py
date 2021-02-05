from machine import Pin, I2C
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

    def __init__(self, device, conf):

        RelaysController.__init__(self, device, conf['relay'])
        self._power_monitor = PowerMonitor(conf['power_monitor'], device._conf['i2c'])
        self._reverse = Pin(conf['reverse'], Pin.OUT)
        self.reverse = False
        self._reverse_threshold = device.settings['reverse_threshold']
        self._reverse_duration = device.settings['reverse_duration']
        self._reverse_delay = 2
        self._delay = 0
        if conf['buttons']:
            for idx, pin in enumerate(conf['buttons']):
                button = Pin(pin, Pin.IN, Pin.PULL_UP)
                reverse = bool(idx)
                button.irq(lambda pin, reverse=reverse: self.on_button(pin, reverse))

    def on_button(self, pin, reverse=False):
        print('button {0} {1} {2}'.format(
            pin, pin.value(), 'reverse' if reverse else ''
        ))
        if pin.value():
            self.on(False, 'manual')
        else:
            self.reverse = reverse
            self.on(True, 'manual')

    @property
    def state(self):
        return self.pin.value()

    @state.setter
    def state(self, value):
        self.on(value=value)

    def on(self, value=True, source='timer'):
        if self.state != value:
            RelaysController.on(self, value, source)
            self.device.post_log("Feeder {0} {1}{2}".format(
                'start' if self.state else 'stop',
                ' (reverse) ' if self.reverse else '',
                source))
            if value and source == 'manual':
                uasyncio.get_event_loop().create_task(self.check_current())
            if not value:
                self.reverse = False

    async def check_current(self):
        while self.state:
            await uasyncio.sleep(1)
            cur = self._power_monitor.current()
            self.device.post_log("Feeder current: {0:+.2f}".format(cur))

    async def run_for(self, duration):
        start = utime.time()
        now = start
        prev_time = start
        expired = 0
        retries = 0
        self.on()
        while expired < duration and retries < 3:
            await uasyncio.sleep(1)
            now = utime.time()
            cur = self._power_monitor.current()
            self.device.post_log("Feeder current: {0:+.2f}".format(cur))
            expired += now - prev_time
            prev_time = now
            if cur > self._reverse_threshold:
                await self.engine_reverse(True)
                await uasyncio.sleep(self._reverse_duration)
                expired -= self._reverse_duration + 2 * self._reverse_delay
                retries += 1
                await self.engine_reverse(False)
        self.off()

    async def engine_reverse(self, reverse):
        self.pin.value(False)
        await uasyncio.sleep(self._reverse_delay)
        self.reverse = reverse
        await uasyncio.sleep(self._reverse_delay)
        self.pin.value(True)

    def create_timer(self, conf):
        return FeederTimer(conf, self)

    @property
    def reverse(self):
        return self._reverse.value()

    def update_settings(self):
        RelaysController.update_settings(self)
        if 'reverse_threshold' in self.device.settings:
            self._reverse_threshold = self.device.settings['reverse_threshold']
        if 'reverse_duration' in self.device.settings:
            self. _reverse_duration = self.device.settings['reverse_duration']

    @reverse.setter
    def reverse(self, value):
        if value != self.reverse:
            self.device.post_log("Feeder reverse {0}".format('on' if value else 'off'))
            self._reverse.value(value)
