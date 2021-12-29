import machine

import lib.uasyncio as uasyncio
import logging

from lenfer_controller import LenferController
from utils import manage_memory

LOG = logging.getLogger("PowerMonitor")

class PowerMonitor(LenferController):

    def __init__(self, device, conf):
        LenferController.__init__(self, device)
        self.data = {}
        self.data_log = []
        self.sensor_devices = []
        for sensor_device_conf in conf['sensor_devices']:
            if sensor_device_conf['type'] == 'pzem004t':                
                from sensors import SensorDevicePZEM004T
                self.sensor_devices.append(SensorDevicePZEM004T(sensor_device_conf, self))
        LOG.info(self.sensor_devices)
        self._uart_id = conf['uart_id']
        self._uart = machine.UART(self._uart_id, baudrate=9600, timeout=3, 
            tx=self.sensor_devices[0]._uart_conf['tx'], rx=self.sensor_devices[0]._uart_conf['rx'])

    async def read(self, once=False):
        while True:
            tstamp = self.device.post_tstamp()
            for sensor_device in self.sensor_devices:
                data_read = sensor_device.read()
                for sensor_id in sensor_device._sensors_ids:
                    self.data_log.append([sensor_id, tstamp, self.data[sensor_id] if data_read else None])                    
            if once:
                return
            await uasyncio.sleep(self.device.settings['sleep'])




        

