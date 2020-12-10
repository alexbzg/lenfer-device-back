import gc
from time import sleep

import uasyncio
import network
import machine
from machine import WDT, Pin, I2C
import ujson
import ulogging

import urequests

from timers import RtcController, Timer

LOG = ulogging.getLogger("Main")

SERVER_URI = "http://dev-api.lenfer.ru/api/"

class LenferDevice:

    MODULES_LIST = ["rtc", "climate", "relays", "power_monitor", "feeder"]

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
                        from climate import ClimateController
                        self.modules[module] = ClimateController(self, module_conf, conf['ow'])
                    elif module == 'rtc':
                        self.modules[module] = RtcController(module_conf, conf['i2c'])
                        self.modules['rtc'].get_time(set_rtc=True)
                    elif module == 'relays':
                        from relay import RelaysController
                        self.modules[module] = RelaysController(self, module_conf)
                    elif module == 'feeder':
                        from feeder import FeederController
                        self.modules[module] = FeederController(self, module_conf, conf['i2c'])
                except Exception as exc:
                    LOG.exc(exc, 'Controller initialization error')
                    LOG.error(module)
                    LOG.error(module_conf)
        with open('schedule.json', 'r') as file_schedule:
            try:
                self.schedule = ujson.load(file_schedule)
            except Exception as exc:
                LOG.exc(exc, 'Schedule loading error')
        if not self.schedule:
            self.schedule = {'hash': None, 'start': None}

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
        while True:
            data = {
                'schedule': {
                    'hash': self.schedule['hash'],
                    'start': self.schedule['start']
                }
            }
            rsp = self.srv_post('device_updates', data)
            if rsp:
                LOG.info(rsp)
                updates = ujson.loads(rsp)
                if 'schedule' in updates:
                    self.schedule = updates['schedule']
            await uasyncio.sleep(30)

    async def post_sensor_data(self):
        while True:
            await uasyncio.sleep(60)
            data = {'data': []}
            tstamp = self.post_tstamp()
            for ctrl in self.modules.values():
                if ctrl and hasattr(ctrl, 'data'):
                    data['data'] += [{'sensor_id': _id, 'tstamp': tstamp, 'value': value}\
                        for _id, value in ctrl.data.items()]
            self.srv_post('sensors_data', data)

    def post_log(self, entries):
        tstamp = self.post_tstamp()
        if isinstance(entries, str):
            entries = [entries,]
        for idx in range(len(entries)):
            if isinstance(entries[idx], str):
                entries[idx] = {'txt': entries[idx]}
            if not 'log_tstamp' in entries[idx] or not entries[idx]['log_tstamp']:
                entries[idx]['log_tstamp'] = tstamp
        LOG.info(entries)
        self.srv_post('devices_log/post', {'entries': entries})

    @staticmethod
    def post_tstamp(time_tuple=None):
        if not time_tuple:
            time_tuple = machine.RTC().datetime()
        return "{0:0>1d}/{1:0>1d}/{2:0>1d} {4:0>1d}:{5:0>1d}:{6:0>1d}".format(*time_tuple)

    def srv_post(self, url, data):
        rsp = None
        result = None
        try:
            data['device_id'] = self.id['id']
            data['token'] = self.id['token']
            rsp = urequests.post(SERVER_URI + url, json=data)
            if rsp.status_code != 200:
                raise Exception(rsp.reason)
        except Exception as exc:
            LOG.exc(exc, 'Data posting error')
            LOG.error("URL: %s", SERVER_URI + url)
            LOG.error("data: %s", data)
        if rsp:
            result = rsp.text
            rsp.close()
            rsp = None            
        gc.collect()
        return result

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
        for relay_module in ('relays', 'feeder'):
            if self.modules[relay_module]:
                loop.create_task(self.modules[relay_module].check_timers())
        self.post_log('device start')

