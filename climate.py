import machine
from machine import Pin, Onewire

import lib.uasyncio as uasyncio
import logging

from lenfer_controller import LenferController
from utils import manage_memory
from timers import time_tuple_to_seconds

LOG = logging.getLogger("Climate")


class ClimateController(LenferController):

    CO2_THRESHOLD = 2500

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
        self.light = Pin(conf['light'], Pin.OUT) if conf.get('light') else None
        if 'switches' in conf and conf['switches']:
            
            for switch_type in ('heat', 'vent_out', 'vent_mix', 'humid', 'air_con'):
                if conf['switches'].get(switch_type) and (not self.device.mode or 'modes' not in conf['switches'][switch_type]
                    or self.device.mode in conf['switches'][switch_type]['modes']):                       
                        switch_conf = conf['switches'][switch_type]
                        self.switches[switch_type] = {
                            'pin': Pin(switch_conf['pin'], Pin.INOUT),
                            'id': switch_conf['id'],
                            'enabled': True
                        }
                        self.switches[switch_type]['pin'].value(0)
                else:
                    self.switches[switch_type] = {'enabled': False}
            LOG.info('climate switches: %s' % self.switches)

        self.update_settings()

        for sensor_device_conf in conf['sensor_devices']:
            if sensor_device_conf['type'] == 'bme280':                
                from sensors import SensorDeviceBME280
                self.sensor_devices.append(SensorDeviceBME280(sensor_device_conf, self, device.i2c))
            elif sensor_device_conf['type'] == 'aht20':
                from sensors import SensorDeviceAHT20
                self.sensor_devices.append(SensorDeviceAHT20(sensor_device_conf, self, device.i2c))
            elif sensor_device_conf['type'] == 'ccs811':
                from sensors import SensorDeviceCCS811
                self.sensor_devices.append(SensorDeviceCCS811(sensor_device_conf, self, device.i2c))
            elif sensor_device_conf['type'] == 'ds18x20':
                from sensors import SensorDeviceDS18x20
                self.sensor_devices.append(SensorDeviceDS18x20(sensor_device_conf, self, device._conf['ow']))

    def update_settings(self):
        if self.device.settings.get('switches'):
            for switch_id, enabled in self.device.settings['switches'].items():
                switch_filter = [item for item in self.switches.values() if item.get('id') == int(switch_id)]
                if switch_filter:
                    switch = switch_filter[0]
                    if 'pin' in switch:
                        switch['enabled'] = enabled
            LOG.info('climate switches: %s' % self.switches)

    async def read(self, once=False):

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
            if once:
                break


    async def adjust_light(self, once=False):
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
            if once:
                break
            await uasyncio.sleep(59)

    def get_schedule_param_idx(self, param):
        return self.schedule['params_list'].index(param)
        
    def adjust_switches(self):
        state = {}
        schedule_day = self.device.schedule.current_day()
        for param in self.sensors_roles:
            state[param] = {
                'value': [self.data[sensor_idx] for sensor_idx in self.sensors_roles[param] if self.data[sensor_idx] != None], 
                'limits': []
                }
            if state[param]['value']:
                param_value, param_delta = None, None
                if schedule_day:
                    param_idx = self.device.schedule.param_idx(param)
                    if param_idx != -1:
                        param_value = schedule_day[param_idx]
                        param_delta = self.device.schedule.params['delta'][param_idx]
                if param_value == None or param_delta == None:
                    if self.device.settings.get(param):
                        param_value, param_delta = self.device.settings[param]
                if param_value != None and param_delta != None:
                    state[param]['limits'] = [
                        param_value - param_delta,
                        param_value + param_delta,
                    ]

        if state.get('temperature') and state['temperature']['value']:
            if self.switches['heat']['enabled'] and state['temperature']['limits']:
                if state['temperature']['value'][0] < state['temperature']['limits'][0]:
                    if not self.switches['heat']['pin'].value():
                        self.switches['heat']['pin'].value(1)
                        LOG.info('Heat on')
                else:
                    if self.switches['heat']['pin'].value():
                        self.switches['heat']['pin'].value(0)
                        LOG.info('Heat off')
            if self.switches['vent_mix']['enabled']:
                if len(state['temperature']['value']) > 1:
                    if state['temperature']['value'][0] > state['temperature']['value'][1] + 3 or\
                        state['temperature']['value'][0] < state['temperature']['value'][1] - 3:
                        if not self.switches['vent_mix']['pin'].value():
                            self.switches['vent_mix']['pin'].value(1)
                            LOG.info('Mix on')
                    elif state['temperature']['value'][0] < state['temperature']['value'][1] + 1 and\
                        state['temperature']['value'][0] > state['temperature']['value'][1] - 1:
                        if self.switches['vent_mix']['pin'].value():
                            self.switches['vent_mix']['pin'].value(0)
                            LOG.info('Mix off') 
        if self.switches['vent_mix']['enabled']:
            if not state.get('temperature') or len(state['temperature']['value']) < 2:
                if self.switches['vent_mix']['pin'].value():
                    self.switches['vent_mix']['pin'].value(0)
                    LOG.info('Mix off')
        if self.switches['vent_out']['enabled']:
            if (state.get('humidity') and state['humidity']['value'] and state['humidity']['limits'] and\
                    state['humidity']['value'][0] > state['humidity']['limits'][1]) or\
                (state.get('temperature') and state['temperature']['value'] and state['temperature']['limits'] and\
                    state['temperature']['value'][0] > state['temperature']['limits'][1]) or\
                (state.get('co2') and state['co2']['value'][0] > ClimateController.CO2_THRESHOLD):
                if not self.switches['vent_out']['pin'].value():
                    self.switches['vent_out']['pin'].value(1)
                    LOG.info('Out on')
            else:
                if self.switches['vent_out']['pin'].value():
                    self.switches['vent_out']['pin'].value(0)
                    LOG.info('Out off')
        if self.switches['humid']['enabled']:
            if state.get('humidity') and state['humidity']['value'] and state['humidity']['limits'] and\
                state['humidity']['value'][0] < state['humidity']['limits'][0]:
                if not self.switches['humid']['pin'].value():
                    self.switches['humid']['pin'].value(1)
                    LOG.info('Humid on')
            else:
                if self.switches['humid']['pin'].value():
                    self.switches['humid']['pin'].value(0)
                    LOG.info('Humid off')
        if self.switches['air_con']['enabled']:
            if state.get('temperature') and state['temperature']['value'] and state['temperature']['limits'] and\
                    state['temperature']['value'][0] > state['temperature']['limits'][1] + 3:
                if not self.switches['air_con']['pin'].value():
                    self.switches['air_con']['pin'].value(1)
                    LOG.info('Air con on')
                    if self.switches['vent_out']['enabled'] and self.switches['vent_out']['pin'].value()\
                        and (not state.get('co2') or not state['co2']['value'] or state['co2']['value'][0] < ClimateController.CO2_THRESHOLD):
                        self.switches['vent_out']['pin'].value(0)
            else:
                if self.switches['air_con']['pin'].value():
                    self.switches['air_con']['pin'].value(0)
                    LOG.info('Air con off')       

        manage_memory()
