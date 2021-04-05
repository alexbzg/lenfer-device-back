import gc
import utime
import machine
from machine import Pin
import ds18x20
import onewire

import uasyncio
import ulogging

import BME280
from lenfer_controller import LenferController
from utils import manage_memory

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
            pass
            #LOG.exc(exc, 'BME280 error')
        finally:
            self._controller.data[self._sensors_ids[0]] = temp
            self._controller.data[self._sensors_ids[1]] = humid
        

class SensorDeviceDS18x20(SensorDevice):
    "ds18x20 sensor handler"

    def __init__(self, conf, controller, ow_list):
        SensorDevice.__init__(self, conf, controller)
        print('ds18x20 init')
        self.rom = None
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

class ClimateController(LenferController):

    def __init__(self, device, conf):        
        LenferController.__init__(self, device)
        self.limits = device.settings['limits'] if 'limits' in device.settings else False
        self.sensors_roles = conf['sensors_roles']
        self.sensors_titles = conf['sensors_titles']
        self._switches = conf['switches']
        self.switches = {}
        self._sleep = conf['sleep']
        self.data = {}
        self.sensor_devices = []
        if 'switches' in conf and conf['switches']:
            
            self.switches['heat'] = {
                'pin': Pin(conf['switches']['heat']['pin'], Pin.OUT),
                'id': conf['switches']['heat']['id']
            } if 'heat' in conf['switches'] and conf['switches']['heat'] else None
            if self.switches['heat']:
                self.switches['heat']['pin'].value(0)
            self.switches['vent_out'] = {
                'pin': Pin(conf['switches']['vent_out']['pin'], Pin.OUT),
                'id': conf['switches']['vent_out']['id']
            } if 'vent_out' in conf['switches'] and conf['switches']['vent_out'] else None
            if self.switches['vent_out']:
                self.switches['vent_out']['pin'].value(0)
            self.switches['vent_mix'] = {
                'pin': Pin(conf['switches']['vent_mix']['pin'], Pin.OUT),
                'id': conf['switches']['vent_mix']['id']
            } if 'vent_mix' in conf['switches'] and conf['switches']['vent_mix'] else None
            if self.switches['vent_mix']:
                self.switches['vent_mix']['pin'].value(0)
        for sensor_device_conf in conf['sensor_devices']:
            if sensor_device_conf['type'] == 'bme280':
                self.sensor_devices.append(SensorDeviceBME280(sensor_device_conf, self, device.i2c))
            elif sensor_device_conf['type'] == 'ds18x20':
                self.sensor_devices.append(SensorDeviceDS18x20(sensor_device_conf, self, device._conf['ow']))

    async def read(self):

        while True:
            for sensor_device in self.sensor_devices:
                if sensor_device.sensor_type == 'ds18x20':
                    sensor_device.convert()
            await uasyncio.sleep_ms(self._sleep)
            for sensor_device in self.sensor_devices:
                sensor_device.read()
            if self._switches:
                self.adjust_switches()
            manage_memory()

    def adjust_switches(self):
        temp = [
            self.data[self.sensors_roles['temperature'][0]],
            self.data[self.sensors_roles['temperature'][1]]
            ]
        humid = self.data[self.sensors_roles['humidity'][0]]
        temp_limits, humid_limits = None, None
        if self.schedule and 'items' in self.schedule and self.schedule['items'] and 'start' in self.schedule and self.schedule['start']:
            day_no = 0
            start = utime.mktime(self.schedule['start'])
            today = utime.mktime(machine.RTC().datetime())
            if start < today:
                day_no = int((today-start)/86400)
            if day_no >= len(self.schedule['items']):
                day_no = len(self.schedule['items']) - 1
            day = self.schedule['items'][day_no]
            temp_idx = self.schedule['params'].index('temperature')
            temp_delta = float(day[temp_idx][1])
            temp_limits = [
                float(day[temp_idx][0]) - temp_delta,
                float(day[temp_idx][0]) + temp_delta,
            ]

            humid_idx = self.schedule['params'].index('humidity')
            humid_delta = float(day[humid_idx][1])
            humid_limits = [
                float(day[humid_idx][0]) - humid_delta,
                float(day[humid_idx][0]) + humid_delta,
            ]

        elif self.limits:
            temp_limits = [
                self.limits['temperature'][0] - self.limits['temperature'][1],
                self.limits['temperature'][0] + self.limits['temperature'][1],
            ]

            humid_limits = [
                self.limits['humidity'][0] - self.limits['humidity'][1],
                self.limits['humidity'][0] + self.limits['humidity'][1],
            ]

        if temp[0]:
            if self.switches['heat'] and temp_limits:
                if temp[0] < temp_limits[0]:
                    if not self.switches['heat']['pin'].value():
                        self.switches['heat']['pin'].value(1)
                        LOG.info('Heat on')
                else:
                    if self.switches['heat']['pin'].value():
                        self.switches['heat']['pin'].value(0)
                        LOG.info('Heat off')
            if self.switches['vent_mix']:
                if temp[1]:
                    if temp[0] > temp[1] + 3 or temp[0] < temp[1] - 3:
                        if not self.switches['vent_mix']['pin'].value():
                            self.switches['vent_mix']['pin'].value(1)
                            LOG.info('Mix on')
                    elif temp[0] < temp[1] + 1 and temp[0] > temp[1] - 1:
                        if self.switches['vent_mix']['pin'].value():
                            self.switches['vent_mix']['pin'].value(0)
                            LOG.info('Mix off') 
        if self.switches['vent_mix']:
            if not temp[0] or not temp[1]:
                if self.switches['vent_mix']['pin'].value():
                    self.switches['vent_mix']['pin'].value(0)
                    LOG.info('Mix off')
        if self.switches['vent_out']:
            if (humid and humid_limits and humid > humid_limits[1]) or\
                (temp[0] and temp_limits and temp[0] > temp_limits[1]):
                if not self.switches['vent_out']['pin'].value():
                    self.switches['vent_out']['pin'].value(1)
                    LOG.info('Out on')
            elif (not humid or not humid_limits or humid < humid_limits[1]) and\
                (not temp[0] or not temp_limits or temp[0] < temp_limits[1]):
                if self.switches['vent_out']['pin'].value():
                    self.switches['vent_out']['pin'].value(0)
                    LOG.info('Out off')
        gc.collect()
