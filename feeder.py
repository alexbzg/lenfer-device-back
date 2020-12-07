from machine import Pin, I2C
import uasyncio

from ina219 import INA219

from relay import RelaysController, Relay

class PowerMonitor:

    def __init__(self, conf, _i2c):
        i2c = _i2c[conf["i2c"]]
        self._ina219 = INA219(conf["shunt_ohms"], I2C(scl=Pin(i2c["scl"]), sda=Pin(i2c["sda"])))
        self._ina219.configure()

    def voltage(self):
        return self._ina219.voltage()

    def current(self):
        return self._ina219.current()

class FeederController(RelaysController):

    def __init__(self, device, conf, i2c):

        RelaysController.__init__(self, device, conf['relays'])
        self._power_monitor = PowerMonitor(conf['power_monitor'], i2c)
        self._reverse = Relay(conf['reverse'])
        uasyncio.get_event_loop().create_task(self.power_monitor_check())

    @property
    def state(self):
        return self.relays[0].pin.value()

    @state.setter
    def state(self, value):
        self.relays[0].on(value=value)

    @property
    def reverse(self):
        return self._reverse.pin.value()

    @reverse.setter
    def reverse(self, value):
        self._reverse.on(value=value)

    async def power_monitor_check(self):
        while True:
            if self.state:
                print('current: ' + str(self._power_monitor.current()))
            await uasyncio.sleep(1)
