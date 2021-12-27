import machine
import ubinascii

import lib.uasyncio as uasyncio
import logging

from lenfer_controller import LenferController
from utils import manage_memory

LOG = logging.getLogger("PowerMonitor")

class PowerMonitor(LenferController):

    def __init__(self, device, conf):
        LenferController.__init__(self, device)
        self.data = {}
        self._sleep = device.settings['sleep']
        self.sensor_devices = []
        for sensor_device_conf in conf['sensor_devices']:
            if sensor_device_conf['type'] == 'pzem004t':                
                from sensors import SensorDevicePZEM004T
                self.sensor_devices.append(SensorDevicePZEM004T(sensor_device_conf, self))

    async def read(self, once=False):
        while True:
            for sensor_device in self.sensor_devices:
                sensor_device.read()
            if once:
                return
            await uasyncio.sleep(self._sleep)



        

