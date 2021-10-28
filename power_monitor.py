from ina219 import INA219

class PowerMonitor:

    def __init__(self, conf, _i2c):
        i2c = _i2c[conf["i2c"]]
        self._ina219 = INA219(conf["shunt_ohms"], i2c)
        self._ina219.configure()

    def voltage(self):
        return self._ina219.voltage()

    def current(self):
        return self._ina219.current()