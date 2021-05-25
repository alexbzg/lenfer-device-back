import gc
import micropython
import uerrno
#from time import sleep

import uasyncio
import network
import machine
from machine import WDT, Pin, SoftI2C
import ujson
import ulogging

import urequests

from timers import RtcController
from utils import load_json, save_json, manage_memory
from software_update import check_software_update, schedule_software_update

LOG = ulogging.getLogger("Main")

SERVER_URI = "http://my.lenfer.ru/api/"
SERVER_URI_DEV = "http://dev-api.lenfer.ru/api/"

class LenferDevice:

    MODULES_LIST = ["rtc", "climate", "relays", "power_monitor", "feeder"]

    def save_settings(self):
        save_json(self.settings, 'settings.json')
        self.status["ssid_delay"] = True

    def load_def_settings(self):
        self.settings = load_json('settings_default.json')
        print('default settings loaded')
        self.save_settings()

    def __init__(self, wlan):
        self.WDT = None
        self._schedule = None
        self._wlan = wlan
        self.status = {
            "wlan": None,
            "factory_reset": False,
            "wlan_switch": False,
            "ssid_failure": False,
            "ssid_delay": False,
            "srv_req_pending": False,
            "srv_unreach_count": 0
            }
        self.log_queue = []
        self._conf = load_json('conf.json')
        self.settings = load_json('settings.json')
        if not self.settings:
            self.load_def_settings()

        wlan_switch_button = Pin(self._conf['wlan_switch'], Pin.IN, Pin.PULL_UP)
        wlan_switch_button.irq(self.wlan_switch_irq)

        if 'factory_reset' in self._conf and self._conf['factory_reset']:
            factory_reset_button = Pin(self._conf['factory_reset'], Pin.IN)
            factory_reset_button.irq(self.factory_reset_irq)

        self.modules = {item: None for item in LenferDevice.MODULES_LIST}
        self.i2c = [SoftI2C(scl=Pin(i2c_conf['scl']), sda=Pin(i2c_conf['sda']))
            for i2c_conf in self._conf['i2c']]
        self.leds = {led: Pin(pin_no, Pin.OUT) for led, pin_no in self._conf['leds'].items()}
        self.id = load_json('id.json')
        if 'debug' in self.id and self.id['debug']:
            self.server_uri = SERVER_URI_DEV
        else:
            self.server_uri = SERVER_URI
        for led in self.leds.values():
            led.off()
        for module, module_conf in self._conf['modules'].items():
            if module_conf['enabled']:
                try:
                    if module == 'climate':
                        from climate import ClimateController
                        self.modules[module] = ClimateController(self, module_conf)
                    elif module == 'rtc':
                        self.modules[module] = RtcController(module_conf, self._conf['i2c'])
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
        self.schedule = load_json('schedule.json')
        if not self.schedule:
            self.schedule = {'hash': None, 'start': None}

    def append_log_entries(self, entries):
        tstamp = self.post_tstamp()
        if isinstance(entries, str):
            entries = [entries,]
        for idx, entry in enumerate(entries):
            if isinstance(entry, str):
                entries[idx] = {'txt': entry}
            if not 'log_tstamp' in entries[idx] or not entries[idx]['log_tstamp']:
                entries[idx]['log_tstamp'] = tstamp
        if self.online():
            self.log_queue.extend(entries)
        for entry in entries:
            LOG.info(entry)

    def wlan_switch_irq(self, pin):
        if not pin.value():
            LOG.info('wlan switch was activated')
            self.status['wlan_switch'] = 'true'

    async def check_wlan_switch(self):
        while True:
            await uasyncio.sleep(5)
            if self.status['wlan_switch']:
                self._wlan.enable_ssid(not self._wlan.conf['enable_ssid'])

    async def delayed_ssid_switch(self):
        LOG.info("delayed wlan switch activated")
        while True:
            await uasyncio.sleep(300)
            if self.status["ssid_delay"]:
                self.status["ssid_delay"] = False
            else:
                self._wlan.enable_ssid(True)

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
        for _ in range(50):
            await uasyncio.sleep_ms(100)
            if self.status['factory_reset'] != 'pending':
                LOG.info('factory reset is cancelled')
                self.status['factory_reset'] = None
                return
        for led in self.leds.values():
            led.on()
        self.load_def_settings()
        self._wlan.load_def_conf()
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
            await self.blink(("status",), 1 if self._wlan.mode == network.AP_IF else 2, 100)
            await uasyncio.sleep(2)
            gc.collect()


    async def task_check_software_updates(self):
        while True:
            self.WDT.feed()
            if check_software_update():
                schedule_software_update()
            self.WDT.feed()
            await uasyncio.sleep(3600)

    async def check_updates(self):
        while True:
            try:
                data = {
                    'schedule': {
                        'hash': self.schedule['hash'],
                        'start': self.schedule['start']
                    },
                    'props': self.settings
                }
                updates = await self.srv_post('device_updates', data)
                if updates:
                    if 'schedule' in updates and updates['schedule']:
                        self.schedule = updates['schedule']
                    if 'props' in updates and updates['props']:
                        self.settings = updates['props']
                        self.save_settings()
                        for ctrl in self.modules.values():
                            if ctrl:
                                ctrl.update_settings()
            except Exception as exc:
                LOG.exc(exc, 'Server updates check error')
            manage_memory()
            await uasyncio.sleep(30)

    async def post_sensor_data(self):
        while True:
            await uasyncio.sleep(58)
            try:
                data = {'data': []}
                tstamp = self.post_tstamp()
                for ctrl in self.modules.values():
                    if ctrl and hasattr(ctrl, 'data'):
                        data['data'] += [{'sensor_id': _id, 'tstamp': tstamp, 'value': value}\
                            for _id, value in ctrl.data.items()]
                if data['data']:
                    await self.srv_post('sensors_data', data)
                data = {'data': []}
                tstamp = self.post_tstamp()
                for ctrl in self.modules.values():
                    if ctrl and hasattr(ctrl, 'switches'):
                        data['data'] += [{'device_type_switch_id': switch['id'], 'tstamp': tstamp, 'state': switch['pin'].value() == 1}\
                            for switch in ctrl.switches.values() if switch]
                if data['data']:
                    await self.srv_post('switches_state', data)
            except Exception as exc:
                LOG.exc(exc, 'Server sensors data post error')
            manage_memory()

    async def post_log(self):
        while True:
            await uasyncio.sleep(59)
            try:
                if self.log_queue and not self.status['srv_req_pending']:
                    await self.srv_post('devices_log/post', {'entries': self.log_queue})
                    self.log_queue = []
            except Exception as exc:
                LOG.exc(exc, 'Server log post error')
            manage_memory()


    @staticmethod
    def post_tstamp(time_tuple=None):
        if not time_tuple:
            time_tuple = machine.RTC().datetime()
        return "{0:0>1d}/{1:0>1d}/{2:0>1d} {4:0>1d}:{5:0>1d}:{6:0>1d}".format(*time_tuple)

    async def srv_post(self, url, data, raw=False):
        while self.status['srv_req_pending']:
            await uasyncio.sleep_ms(50)
        self.status['srv_req_pending'] = True
        rsp = None
        result = None
        try:
            data['device_id'] = self.id['id']
            data['token'] = self.id['token']
            manage_memory()
            self.WDT.feed()
            rsp = urequests.post(self.server_uri + url, json=data, parse_headers=False)
            if rsp.status_code != 200:
                raise Exception(rsp.reason)
        except OSError as exc:
            LOG.exc(exc, 'Data posting error')
            LOG.error("URL: %s", self.server_uri + url)
            LOG.error("data: %s", data)
            self.status['srv_unreach_count'] += 1
            LOG.error("server unreachable count: %s", self.status['srv_unreach_count'])
            if self.status['srv_unreach_count'] > 2:
                machine.reset()
        except Exception as exc:
            LOG.exc(exc, 'Data posting error')
            LOG.error("URL: %s", self.server_uri + url)
            LOG.error("data: %s", data)
        finally:
            if hasattr(self, 'WDT'):
                self.WDT.feed()
            self.status['srv_req_pending'] = False
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
        manage_memory()
        return result

    def online(self):
        return 'id' in self.id and self.id['id'] and self._wlan.online()

    def start_async(self):
        self.WDT = WDT(timeout=60000)        
        loop = uasyncio.get_event_loop()     
        loop.create_task(self.bg_leds())
        loop.create_task(self.check_wlan_switch())
        if self._wlan.mode == network.AP_IF and self._wlan.conf['ssid']:
            loop.create_task(self.delayed_ssid_switch())
        if self.modules['climate']:
            loop.create_task(self.modules['climate'].read())
            if self.online():
                loop.create_task(self.post_sensor_data())
            if self.modules['climate'].light:
                loop.create_task(self.modules['climate'].adjust_light())                
        if self.modules['rtc']:
            loop.create_task(self.modules['rtc'].adjust_time())
        for relay_module in ('relays', 'feeder'):
            if self.modules[relay_module]:
                loop.create_task(self.modules[relay_module].check_timers())
        if self.online():
            loop.create_task(self.post_log())
            if 'updates' in self.id and self.id['updates']:
                loop.create_task(self.check_updates())
            if 'disable_software_updates' not in self.id or not self.id['disable_software_updates']:
                loop.create_task(self.task_check_software_updates())

        self.append_log_entries('device start')

