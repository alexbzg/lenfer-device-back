import machine
import ubinascii

import lib.uasyncio as uasyncio
import logging

from lenfer_controller import LenferController
from utils import manage_memory

LOG = logging.getLogger("PowerMonitor")

class PowerMonitorController(LenferController):

    def __init__(self, device, conf):
        LenferController.__init__(self, device)
        self._sensors = conf.sensors
        self._uart = machine.UART(conf['uart']['id'], tx=conf['uart']['tx'], rx=conf['uart']['rx'], baudrate=9600, timeout=3)
        self._uart.init()
        self.data = {}
        self._sleep = device.settings['sleep']

    async def read(self, once=False):
        while True:
            self._uart.write(b"\xf8\x04\x00\x00\x00\x0a\x64\x64")   
            msg_raw = self._uart.read(25)
            if msg_raw:
                try:
                    msg = ubinascii.hexlify(msg_raw).decode()
                    self.data[self._sensors['voltage']] = int(msg[6:10], 16) / 10
                    self.data[self._sensors['current']] = int(msg[10:14], 16) / 1000
                except Exception as exc:
                    LOG.exc('exc', 'PZEM UART reading error')
            if once:
                return
            await uasyncio.sleep(self._sleep)



        

