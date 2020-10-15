import gc
import uasyncio
import ulogging

from machine import Pin
import ds18x20
import onewire

import BME280


LOG = ulogging.getLogger("Climate")

class SensorDevice:
    "generic sensor handler"

    def __init__(self, conf, controller):
        self.sensor_type = conf['type']
        self._controller = controller
        self._sensors_ids = conf['sensors_ids']
        if controller:
            for sensor_id in self._sensors_ids:
                if not sensor_id in controller.data:
                    controller.data[sensor_id] = None

class SensorDeviceBME280(SensorDevice):
    "BME280 sensor handler"

    def __init__(self, conf, controller, i2c_list):
        SensorDevice.__init__(self, conf, controller)
        self._i2c = i2c_list[conf['i2c']]

    def read(self):
        "reads sensors data and stores in into controller data field"
        humid, temp = None, None
        try:
            bme = BME280.BME280(i2c=self._i2c)
            temp = round((bme.read_temperature() / 100), 1)
            humid = int(bme.read_humidity() // 1024)
        except Exception as exc:
            LOG.exc(exc, 'BME280 error')
        finally:
            self._controller.data[self._sensors_ids[0]] = temp
            self._controller.data[self._sensors_ids[1]] = humid
        

class SensorDeviceDS18x20(SensorDevice):
    "ds18x20 sensor handler"

    def __init__(self, conf, controller, ow_list):
        SensorDevice.__init__(self, conf, controller)
        print('ds18x20 init')
        self._rom = None
        self._ds = None
        _ow = ow_list[conf['ow']]
        if _ow:
            self._ds = ds18x20.DS18X20(onewire.OneWire(Pin(ow_list[conf['ow']])))
            ow_roms = self._ds.scan()
            if ow_roms:
                self.rom = ow_roms[0]
                print('ds18x20 rom found ' + str(self.rom))
            else:
                print('no ds18x20 rom found')
        else:
            print('invalid onewire settings')
        self._convert = False

    def convert(self):
        "requests sensor readings"
        if self.rom:
            try:
                self._ds.convert_temp()
                self._convert = True
            except Exception as exc:
                LOG.exc(exc, 'onewire error')

    def read(self):
        "reads sensors data and stores in into controller data field"
        if self._convert:
            try:
                self._controller.data[self._sensors_ids[0]] =\
                    round(self._ds.read_temp(self.rom), 1)
            except Exception as exc:
                LOG.exc(exc, 'onewire error')
                self._controller.data[self._sensors_ids[0]] = None
            finally:
                self._convert = False

class ClimateController:

    def __init__(self, conf, i2c_list, ow_list):

        self.limits = conf['limits']
        self.sensors_roles = conf['sensors_roles']
        self._switches = conf['switches']
        self._sleep = conf['sleep']
        self.data = {}
        self.sensor_devices = []
        self.heat = Pin(conf["switches"]['heat'], Pin.OUT)
        self.vent_out = Pin(conf["switches"]['vent_out'], Pin.OUT)
        self.vent_mix = Pin(conf["switches"]['vent_mix'], Pin.OUT)
        for sensor_device_conf in conf['sensor_devices']:
            if sensor_device_conf['type'] == 'bme280':
                self.sensor_devices.append(SensorDeviceBME280(sensor_device_conf, self, i2c_list))
            elif sensor_device_conf['type'] == 'ds18x20':
                self.sensor_devices.append(SensorDeviceDS18x20(sensor_device_conf, self, ow_list))

    async def read(self):

        while True:
            for sensor_device in self.sensor_devices:
                if sensor_device.sensor_type == 'ds18x20':
                    sensor_device.convert()
            await uasyncio.sleep_ms(self._sleep)
            for sensor_device in self.sensor_devices:
                sensor_device.read()
                temp = [
                    self.data[self.sensors_roles['temperature'][0]],
                    self.data[self.sensors_roles['temperature'][1]]
                    ]
                humid = self.data[self.sensors_roles['humidity'][0]]
                if temp[0]:
                    if temp[0] < self.limits['temperature'][0]:
                        self.heat.value(1)
                    elif temp[0] > self.limits['temperature'][0] + 2:
                        self.heat.value(0)
                    if temp[1]:
                        if temp[0] > temp[1] + 3 or temp[0] < temp[1] - 3:
                            self.vent_mix.value(1)
                        elif temp[0] < temp[1] + 1 and temp[0] > temp[1] - 1:
                            self.vent_mix.value(0)
                if not temp[0] or not temp[1]:
                    self.vent_mix.value(0)
                if (humid and humid > self.limits['humidity'][1]) or\
                    (temp[0] and temp[0] > self.limits['temperature'][1]):
                    self.vent_out.value(1)
                elif (not humid or humid < self.limits['humidity'][1] - 5) and\
                    (not temp[0] or temp[0] < self.limits['temperature'][1] - 2):
                    self.vent_out.value(0)
            gc.collect()
