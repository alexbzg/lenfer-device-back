import gc
from time import sleep

import uasyncio
import network
import machine
from machine import WDT, Pin, I2C
import ujson
import utime
import ulogging
import onewire

import urequests

import ds18x20

from climate import ClimateController
from timers import RtcController, Timer
from relay import RelaysController

LOG = ulogging.getLogger("Main")

SERVER_URI = "http://dev-api.lenfer.ru"

class LenferDevice:

    MODULES_LIST = ["rtc", "climate", "relays", "power_monitor"]

    def __init__(self, conf):
        self._schedule = None
        self.modules = {item: None for item in LenferDevice.MODULES_LIST}
        self.i2c = [I2C(scl=Pin(i2c_conf['scl']), sda=Pin(i2c_conf['sda'])) for i2c_conf in conf['i2c']]
        self.status = {"wlan": None, "factory_reset": False, "wlan_switch": False, "ssid_failure": False, "ssid_delay": False}
        self.leds = {led: Pin(pin_no, Pin.OUT) for led, pin_no in conf['leds'].items()}
        self._conf = conf
        with open('id.json', 'r') as file_id:
            self.id = ujson.load(file_id)
        for led in self.leds.values():
            led.off()
        for module, module_conf in conf['modules'].items():
            if module_conf['enabled']:
                try:
                    if module == 'climate':
                        self.modules[module] = ClimateController(module_conf, self.i2c, conf['ow'])
                    elif module == 'rtc':
                        self.modules[module] = RtcController(module_conf, conf['i2c'])
                        self.modules['rtc'].get_time(set_rtc=True)
                    elif module == 'relays':
                        self.modules[module] = RelaysController(module_conf)
                except Exception as exc:
                    LOG.exc(exc, 'Controller initialization error')
                    LOG.error(module)
                    LOG.error(module_conf)
        with open('schedule.json', 'r') as file_schedule:
            self.schedule = ujson.load(file_schedule)

    @property
    def schedule(self):
        return self._schedule

    @schedule.setter
    def schedule(self, value):
        if self._schedule:
            with open('schedule.json', 'w', encoding="utf-8") as schedule_file:
                schedule_file.write(ujson.dumps(value))
        self._schedule = value
        for ctrl in self.modules.values():
            if ctrl and hasattr(ctrl, 'schedule'):
                ctrl.schedule = value

    async def blink(self, leds, count, time_ms):
        for co in range(count):
            for led in leds:
                if led in self.leds:
                    self.leds[led].on()
            await uasyncio.sleep_ms(time_ms)
            for led in leds:
                if led in self.leds:
                    self.leds[led].off()
            if co < count - 1:
                await uasyncio.sleep_ms(time_ms)

    async def bg_leds(self):
        while True:
            self.WDT.feed()
            await self.blink(("status",), 1 if self.status["wlan"] == network.AP_IF else 2, 100)
            await uasyncio.sleep(5)
            gc.collect()

    async def check_updates(self):
        rsp = None
        while True:
            await uasyncio.sleep(30)
            try:
                print('updates check')
                data = {
                    'device_id': self.id['id'],
                    'token': self.id['token'],
                    'schedule': {
                        'hash': self.schedule['hash'],
                        'start': self.schedule['start']
                    }
                }
                rsp = urequests.post(SERVER_URI + '/api/device_updates', json=data)
                print('post finished')
                print(rsp.text)
                updates = ujson.loads(rsp.text)
                if 'schedule' in updates:
                    self.schedule = updates['schedule']
            except Exception as exc:
                LOG.exc(exc, 'Check updates error')
            if rsp:
                rsp.close()
                rsp = None
            print("mem_free: " + str(gc.mem_free()))
            gc.collect()

    async def post_sensor_data(self):
        rsp = None
        while True:
            await uasyncio.sleep(60)
            try:
                print('posting sensors data')
                time_tuple = machine.RTC().datetime()
                tstamp = "{0:d}/{1:d}/{2:d} {4:d}:{5:d}".format(*time_tuple)
                data = {
                    'device_id': self.id['id'],
                    'token': self.id['token'],
                    'data': []
                }
                for ctrl in self.modules.values():
                    if ctrl and hasattr(ctrl, 'data'):
                        data['data'] += [{'sensor_id': _id, 'tstamp': tstamp, 'value': value}\
                            for _id, value in ctrl.data.items()]
                print(data)
                rsp = urequests.post(SERVER_URI + '/api/sensors_data', json=data)
                print('post finished')
                print(rsp.text)
            except Exception as exc:
                LOG.exc(exc, 'Data posting error')
            if rsp:
                rsp.close()
                rsp = None
            print("mem_free: " + str(gc.mem_free()))
            gc.collect()

    def start_async(self):
        self.WDT = WDT(timeout=20000)        
        loop = uasyncio.get_event_loop()        
        loop.create_task(self.bg_leds())
        if self.modules['climate']:
            loop.create_task(self.modules['climate'].read())
            if self.status['wlan'] == network.STA_IF:
                loop.create_task(self.post_sensor_data())
                loop.create_task(self.check_updates())
        if self.modules['rtc']:
            loop.create_task(self.modules['rtc'].adjust_time())
        if self.modules['relays']:
            loop.create_task(self.modules['relays'].check_timers())

