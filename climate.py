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
from timers import time_tuple_to_seconds

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
        self.air_con_limits = None
        self.sensors_roles = conf['sensors_roles']
        self.sensors_titles = conf['sensors_titles']
        self._switches = conf['switches']
        self.switches = {}
        self._sleep = conf['sleep']
        self.data = {}
        self.sensor_devices = []
        self.light = Pin(conf['light'], Pin.OUT) if 'light' in conf and conf['light'] else None
        if 'switches' in conf and conf['switches']:
            
            for switch_type in ('heat', 'vent_out', 'vent_mix', 'humid', 'air_con'):
                if switch_type in conf['switches'] and conf['switches'][switch_type]:
                    switch_conf = conf['switches'][switch_type]
                    self.switches[switch_type] = {
                        'pin': Pin(switch_conf['pin'], Pin.OUT),
                        'id': switch_conf['id']
                    }
                    self.switches[switch_type]['pin'].value(0)
                else:
                    self.switches[switch_type] = None

        self.update_settings()

        for sensor_device_conf in conf['sensor_devices']:
            if sensor_device_conf['type'] == 'bme280':
                self.sensor_devices.append(SensorDeviceBME280(sensor_device_conf, self, device.i2c))
            elif sensor_device_conf['type'] == 'ds18x20':
                self.sensor_devices.append(SensorDeviceDS18x20(sensor_device_conf, self, device._conf['ow']))  

    def update_settings(self):
        if 'air_con' in self.device.settings and self.device.settings['air_con']:
            acs = self.device.settings['air_con']
            self.air_con_limits = [acs[0] - acs[1], acs[0] + acs[1]]
        else:
            self.air_con_limits = None

    async def read(self):

        while True:
            for sensor_device in self.sensor_devices:
                if sensor_device.sensor_type == 'ds18x20':
                    sensor_device.convert()
            await uasyncio.sleep_ms(self._sleep)
            for sensor_device in self.sensor_devices:
                sensor_device.read()
            if self.switches:
                self.adjust_switches()
            manage_memory()

    def get_schedule_day(self):
        if self.schedule and 'items' in self.schedule and self.schedule['items'] and 'start' in self.schedule and self.schedule['start']:
            day_no = 0
            start = utime.mktime(self.schedule['start'])
            today = utime.mktime(machine.RTC().datetime())
            if start < today:
                day_no = int((today-start)/86400)
            if day_no >= len(self.schedule['items']):
                day_no = len(self.schedule['items']) - 1
            return self.schedule['items'][day_no]
        else:
            return None

    async def adjust_light(self):
        while True:
            day = self.get_schedule_day()
            if day:
                on_idx = self.get_schedule_param_idx('light_on')
                off_idx = self.get_schedule_param_idx('light_off')
                on = day[on_idx] if on_idx and day[on_idx] else None
                off = day[off_idx] if off_idx and day[off_idx] else None
                now = time_tuple_to_seconds(machine.RTC().datetime())
                if on and ((on <= now and not off) or (on <= now < off) or (off < on <= now)):
                    if not self.light.value():
                        print("Light on")
                        self.light.value(1)
                if off and ((off <= now and not on) or (off <= now < on) or (on < off <= now)):
                    if self.light.value():
                        print("Light off")
                        self.light.value(0)
            await uasyncio.sleep(59)

    def get_schedule_param_idx(self, param):
        return self.schedule['params_list'].index(param)
        
    def adjust_switches(self):
        temp = [
            self.data[self.sensors_roles['temperature'][0]],
            self.data[self.sensors_roles['temperature'][1]]
            ]
        humid = self.data[self.sensors_roles['humidity'][0]]
        temp_limits, humid_limits = None, None

        day = self.get_schedule_day()

        if day:
            temp_idx = self.get_schedule_param_idx('temperature')
            temp_delta = self.schedule['params']['delta'][temp_idx]
            temp_limits = [
                day[temp_idx] - temp_delta,
                day[temp_idx] + temp_delta,
            ]

            humid_idx = self.get_schedule_param_idx('humidity')
            humid_delta = self.schedule['params']['delta'][humid_idx]
            humid_limits = [
                day[humid_idx] - humid_delta,
                day[humid_idx] + humid_delta,
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
        if self.switches['humid']:
            if (humid and humid_limits and humid_limits < humid_limits[0]):
                if not self.switches['humid']['pin'].value():
                    self.switches['humid']['pin'].value(1)
                    LOG.info('Humid on')
            else:
                if self.switches['humid']['pin'].value():
                    self.switches['humid']['pin'].value(0)
                    LOG.info('Humid off')
        if self.switches['air_con'] and self.air_con_limits:
            if temp[0] and temp[0] > self.air_con_limits[1]:
                if not self.switches['air_con']['pin'].value():
                    self.switches['air_con']['pin'].value(1)
                    LOG.info('Air con on')
            elif not temp[0] or temp[0] < self.air_con_limits[0]:
                if self.switches['air_con']['pin'].value():
                    self.switches['air_con']['pin'].value(0)
                    LOG.info('Air con off')       

        gc.collect()
