import gc
import micropython
#from time import sleep

import uasyncio
import network
import machine
from machine import WDT, Pin, I2C
import ujson
import ulogging

import urequests

from timers import RtcController
from utils import load_json, save_json, load_conf, save_conf
#from update import check_update

LOG = ulogging.getLogger("Main")

SERVER_URI = "http://dev-api.lenfer.ru/api/"

class LenferDevice:

    MODULES_LIST = ["rtc", "climate", "relays", "power_monitor", "feeder"]

    def save_conf(self):
        save_conf(self.conf)
        self.status["ssid_delay"] = True

    def load_def_conf(self):
        self.conf = load_conf(use_default=True)
        print('default config loaded')
        self.save_conf()

    def __init__(self, wlan):
        self._schedule = None
        self._wlan = wlan
        self.status = {"wlan": None, "factory_reset": False, "wlan_switch": False, "ssid_failure": False, "ssid_delay": False}
        self.conf = load_conf()

        if not self.conf:
            self.load_def_conf()

        wlan_switch_button = Pin(self.conf['wlan_switch'], Pin.IN, Pin.PULL_UP)
        wlan_switch_button.irq(self.wlan_switch_irq)

        if 'factory_reset' in self.conf and self.conf['factory_reset']:
            factory_reset_button = Pin(self.conf['factory_reset'], Pin.IN)
            factory_reset_button.irq(self.factory_reset_irq)

        self.modules = {item: None for item in LenferDevice.MODULES_LIST}
        self.i2c = [I2C(scl=Pin(i2c_conf['scl']), sda=Pin(i2c_conf['sda'])) for i2c_conf in self.conf['i2c']]
        self.leds = {led: Pin(pin_no, Pin.OUT) for led, pin_no in self.conf['leds'].items()}
        self.id = load_json('id.json')
        for led in self.leds.values():
            led.off()
        for module, module_conf in self.conf['modules'].items():
            if module_conf['enabled']:
                try:
                    if module == 'climate':
                        from climate import ClimateController
                        self.modules[module] = ClimateController(self, module_conf)
                    elif module == 'rtc':
                        self.modules[module] = RtcController(module_conf, self.conf['i2c'])
                        self.modules['rtc'].get_time(set_rtc=True)
                    elif module == 'relays':
                        from relay import RelaysController
                        self.modules[module] = RelaysController(self, module_conf)
                    elif module == 'feeder':
                        from feeder import FeederController
                        self.modules[module] = FeederController(self, module_conf)
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

    def wlan_switch_irq(self, pin):
        if pin.value():
            LOG.info('wlan switch was activated')
            self.status['wlan_switch'] = 'true'

    async def check_wlan_switch(self):
        while True:
            await uasyncio.sleep(5)
            if self.status['wlan_switch'] and self._wlan.mode() != network.AP_IF:
                self.enable_ssid(False)

    def enable_ssid(self, val):
        self._wlan.conf['enable_ssid'] = val
        self._wlan.save_conf()
        machine.reset()

    async def delayed_ssid_switch(self):
        LOG.info("delayed wlan switch activated")
        while True:
            await uasyncio.sleep(300)
            if self.status["ssid_delay"]:
                self.status["ssid_delay"] = False
            else:
                self.enable_ssid(True)

    def factory_reset_irq(self, pin):
        if pin.value():
            if self.status['factory_reset'] == 'pending':
                self.status['factory_reset'] = 'cancel'
        else:
            if not self.status['factory_reset']:
                self.status['factory_reset'] = 'pending'
                uasyncio.get_event_loop().create_task(self.factory_reset())

    async def factory_reset(self):
        LOG.info('factory reset is pending')
        for co in range(50):
            await uasyncio.sleep_ms(100)
            if self.status['factory_reset'] != 'pending':
                LOG.info('factory reset is cancelled')
                self.status['factory_reset'] = None
                return
        for led in self.leds.values():
            led.on()
        self.load_def_conf()
        machine.reset()

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
                },
                'props': {}
            }
            for ctrl in self.modules.values():
                if ctrl:
                    data['props'].update(ctrl.get_updates_props())
            updates = self.srv_post('device_updates', data)
            if updates:
                if 'schedule' in updates:
                    self.schedule = updates['schedule']
                if 'props' in updates:
                    for ctrl in self.modules.values():
                        if ctrl:
                            ctrl.set_updates_props(updates['props'])
                    self.save_conf()

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

    def srv_post(self, url, data, raw=False):
        rsp = None
        result = None
        try:
            data['device_id'] = self.id['id']
            data['token'] = self.id['token']
            gc.collect()
            gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())            
            micropython.mem_info()
            print('-----------------------------')
            print('Free: {} allocated: {}'.format(gc.mem_free(), gc.mem_alloc()))
            rsp = urequests.post(SERVER_URI + url, json=data, parse_headers=False)
            if rsp.status_code != 200:
                raise Exception(rsp.reason)
        except Exception as exc:
            LOG.exc(exc, 'Data posting error')
            LOG.error("URL: %s", SERVER_URI + url)
            LOG.error("data: %s", data)
        if rsp:
            if raw:
                return rsp.raw
            try:
                result = ujson.load(rsp.raw)
            except Exception as exc:
                LOG.exc(exc, 'Server response reading error')
                print(rsp.raw.read())
            finally:
                rsp.close()
                rsp = None            
        gc.collect()
        gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())            
        return result

    def online(self):
        return 'id' in self.id and self.id['id'] and self._wlan.online()

    def start_async(self):
        self.WDT = WDT(timeout=20000)        
        loop = uasyncio.get_event_loop()     
        loop.create_task(self.bg_leds())
        loop.create_task(self.check_wlan_switch())
        if self._wlan.mode == network.AP_IF and self._wlan.conf['ssid'] and self._wlan.conf['enable_ssid']:
            loop.create_task(self.delayed_ssid_switch())
        if self.modules['climate']:
            loop.create_task(self.modules['climate'].read())
            if self.online():
                loop.create_task(self.post_sensor_data())
        if self.modules['rtc']:
            loop.create_task(self.modules['rtc'].adjust_time())
        for relay_module in ('relays', 'feeder'):
            if self.modules[relay_module]:
                loop.create_task(self.modules[relay_module].check_timers())
        if self.online():
            loop.create_task(self.check_updates())

        self.post_log('device start')

