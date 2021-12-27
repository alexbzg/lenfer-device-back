import gc
from network import AP_IF
import machine
from machine import WDT, Pin, I2C

import lib.uasyncio as uasyncio
import logging

from utils import load_json, save_json, manage_memory
from software_update import check_software_update, schedule_software_update
from schedule import Schedule
from http_client import HttpClient

LOG = logging.getLogger("Device")

SERVER_URI = "http://my.lenfer.ru/api/"
SERVER_URI_DEV = "http://dev-api.lenfer.ru/api/"

class LenferDevice:

    MODULES_LIST = ["rtc", "climate", "relays", "power_monitor", "feeder"]

    def module_enabled(self, module_conf):
        if 'enabled' in module_conf and not module_conf['enabled']:
            return False
        if self.mode and module_conf.get('modes') and self.mode not in module_conf['modes']:
            return False
        return True

    def save_settings(self):
        save_json(self.settings, 'settings.json')
        self.status["ssid_delay"] = True

    def load_def_settings(self):
        self.settings = load_json('settings_default.json')
        print('default settings loaded')
        self.save_settings()

    def __init__(self, network_controller):
        LOG.info("LenferDevice init")
        self._schedule = None
        self._network = network_controller
        self.mode = None
        self.status = {
            "wlan": None,
            "factory_reset": False,
            "wlan_switch": False,
            "ssid_failure": False,
            "ssid_delay": False,
            "srv_req_pending": False
            }
        self.log_queue = []
        self._conf = load_json('conf.json')
        self.settings = load_json('settings.json')
        self._http = HttpClient()
        if not self.settings:
            self.load_def_settings()
        if self.settings.get('mode'):
            self.mode = self.settings['mode']

        if self._conf.get('wlan_switch'):
            self._wlan_switch_button = Pin(self._conf['wlan_switch'], Pin.IN, Pin.PULL_UP, 
                handler=self.wlan_switch_irq, trigger=Pin.IRQ_FALLING)

        if self._conf.get('factory_reset'):
            self._factory_reset_button = Pin(self._conf['factory_reset'], Pin.IN, 
                handler=self.factory_reset_irq, trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING)

        self.modules = {}
        self.i2c = [I2C(scl=Pin(i2c_conf['scl']), sda=Pin(i2c_conf['sda']))
            for i2c_conf in self._conf['i2c']]
        LOG.info('I2C init')

        self.leds = {led: Pin(pin_no, Pin.OUT) for led, pin_no in self._conf['leds'].items()}
        self.id = load_json('id.json')
        if 'debug' in self.id and self.id['debug']:
            self.server_uri = SERVER_URI_DEV
        else:
            self.server_uri = SERVER_URI
        for led in self.leds.values():
            led.value(0)

        self.schedule = Schedule()
        manage_memory()
        machine.resetWDT()

        if 'rtc' in self._conf['modules'] and self.module_enabled(self._conf['modules']['rtc']):
            try:
                from timers import RtcController
                self.modules['rtc'] = RtcController(self, self._conf['modules']['rtc'])
                self.modules['rtc'].get_time(set_rtc=True)
                LOG.info('RTC init')

            except Exception as exc:
                LOG.exc(exc, 'RTC initialization error')
            machine.resetWDT()
            manage_memory()
        if 'climate' in self._conf['modules'] and self.module_enabled(self._conf['modules']['climate']):
            try:
                from climate import ClimateController
                self.modules['climate'] = ClimateController(self, self._conf['modules']['climate'])
                LOG.info('ClimateController init')

            except Exception as exc:
                LOG.exc(exc, 'Climate initialization error')
                if self._conf['modules']['climate'].get('obligatory'):
                    LOG.error('Obligatory module initialization fail -- machine reset')
                    machine.reset()
            machine.resetWDT()
            manage_memory()
        if 'power_monitor' in self._conf['modules'] and self.module_enabled(self._conf['modules']['power_monitor']):
            try:
                from power_monitor_controller import PowerMonitor
                self.modules['power_monitor'] = PowerMonitor(self, self._conf['modules']['power_monitor'])
                LOG.info('PowerMonitor init')

            except Exception as exc:
                LOG.exc(exc, 'PowerMonitor initialization error')
                if self._conf['modules']['power_monitor'].get('obligatory'):
                    LOG.error('Obligatory module initialization fail -- machine reset')
                    machine.reset()
            machine.resetWDT()
            manage_memory()

        if 'feeder' in self._conf['modules'] and self.module_enabled(self._conf['modules']['feeder']):
            try:
                from feeder import FeederController
                self.modules['feeder'] = FeederController(self, self._conf['modules']['feeder'])
                LOG.info('Feeder init')
            except Exception as exc:
                LOG.exc(exc, 'Feeder initialization error')
            machine.resetWDT()
            manage_memory()

        if 'gate' in self._conf['modules'] and self.module_enabled(self._conf['modules']['gate']):
            try:
                from gate_controller import GateController
                self.modules['gate'] = GateController(self, self._conf['modules']['gate'])
                LOG.info('Gate init')
            except Exception as exc:
                LOG.exc(exc, 'Gate initialization error')
            machine.resetWDT()
            manage_memory()

        if 'relay_switch' in self._conf['modules'] and self.module_enabled(self._conf['modules']['relay_switch']):
            try:
                from relay_switch import RelaySwitchController
                self.modules['relay_switch'] = RelaySwitchController(self, self._conf['modules']['relay_switch'])
                LOG.info('Relay init')
            except Exception as exc:
                LOG.exc(exc, 'RelaySwitch initialization error')
            machine.resetWDT()
            manage_memory()

        LOG.info(self.modules)

    def append_log_entries(self, entries):
        tstamp = self.post_tstamp()
        if isinstance(entries, str):
            entries = [entries,]
        for idx, entry in enumerate(entries):
            if isinstance(entry, str):
                entries[idx] = {'txt': entry}
            if not entries[idx].get('log_tstamp'):
                entries[idx]['log_tstamp'] = tstamp
        if self.online():
            self.log_queue.extend(entries)
        for entry in entries:
            LOG.info(entry)

    def wlan_switch_irq(self, pin):
        LOG.info("WLAN switch irq %s" % pin.value())
        if not pin.value():
            LOG.info('wlan switch was activated')
            self.status['wlan_switch'] = 'true'

    async def check_wlan_switch(self):
        while True:
            await uasyncio.sleep(5)
            if self.status['wlan_switch']:
                self._network._wlan.enable_ssid(not self._network._wlan.conf['enable_ssid'])

    async def delayed_ssid_switch(self):
        LOG.info("delayed wlan switch activated")
        while True:
            await uasyncio.sleep(300)
            if self.status["ssid_delay"]:
                self.status["ssid_delay"] = False
            else:
                self._network._wlan.enable_ssid(True)

    def factory_reset_irq(self, pin):
        LOG.info("factory reset irq %s" % pin.value())
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
        if self._network._wlan:
            self._network._wlan.load_def_conf()
        machine.reset()

    async def blink(self, leds, count, time_ms):
        for co in range(count):
            for led in leds:
                if led in self.leds:
                    self.leds[led].value(1)
            await uasyncio.sleep_ms(time_ms)
            for led in leds:
                if led in self.leds:
                    self.leds[led].value(0)
            if co < count - 1:
                await uasyncio.sleep_ms(time_ms)

    async def bg_leds(self):
        while True:
            machine.resetWDT()
            if self._network._wlan:
                await self.blink(("status",), 1 if self._network._wlan.mode == AP_IF else 2, 100)
            elif self._network.gsm:
                await self.blink(("status",), 4 if self._network.online() else 3, 100)
            await uasyncio.sleep(2)
            gc.collect()


    async def task_check_software_updates(self, once=False):
        while True:
            machine.resetWDT()
            if check_software_update():
                schedule_software_update()
            machine.resetWDT()
            if once:
                break
            await uasyncio.sleep(3600)

    async def check_updates(self, once=False):
        while True:
            deepsleep = bool(self.deepsleep())
            try:
                data = {
                    'schedule': {
                        'hash': self.schedule.hash,
                        'start': self.schedule.start
                    },
                    'props': self.settings
                }
                updates = await self.srv_post('device_updates', data, retry=once)
                if updates:
                    if updates.get('schedule'):
                        self.schedule.update(updates['schedule'])
                    if 'props' in updates and updates['props']:
                        self.settings = updates['props']
                        self.save_settings()
                        for ctrl in self.modules.values():
                            if ctrl:
                                ctrl.update_settings()
                    if deepsleep != bool(self.deepsleep()):
                        machine.reset()                    
                    if 'mode' in self.settings and self.mode != self.settings['mode']:
                        machine.reset()
            except Exception as exc:
                LOG.exc(exc, 'Server updates check error')
            manage_memory()
            if once:
                break
            await uasyncio.sleep(30)

    async def post_sensor_data(self, once=False):
        while True:
            if not once:
                await uasyncio.sleep(58)
            try:
                data = {'data': []}
                tstamp = self.post_tstamp()
                for ctrl in self.modules.values():
                    if ctrl and hasattr(ctrl, 'data'):
                        data['data'] += [{'sensor_id': _id, 'tstamp': tstamp, 'value': value}\
                            for _id, value in ctrl.data.items()]
                if data['data']:
                    rsp = await self.srv_post('sensors_data', data, retry=once)
                    if once and not rsp:
                        machine.reset()
                data = {'data': []}
                tstamp = self.post_tstamp()
                for ctrl in self.modules.values():
                    if ctrl and hasattr(ctrl, 'switches'):
                        data['data'] += [{'device_type_switch_id': switch['id'], 'tstamp': tstamp, 'state': switch['pin'].value() == 1}\
                            for switch in ctrl.switches.values() if switch['enabled']]
                if data['data']:
                    await self.srv_post('switches_state', data, retry=once)
            except Exception as exc:
                LOG.exc(exc, 'Server sensors data post error')
            manage_memory()
            if once:
                break

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


    def post_tstamp(self, time_tuple=None):
        if not time_tuple:
            time_tuple = machine.RTC().now()
        return "{0:0>1d}/{1:0>1d}/{2:0>1d} {3:0>1d}:{4:0>1d}:{5:0>1d}".format(*time_tuple) if time_tuple else None

    async def srv_post(self, url, data, retry=False):        
        data['device_id'] = self.id['id']
        data['token'] = self.id['token']
        manage_memory()
        machine.resetWDT()
        result = await self._http.post(self.server_uri + url, data)
        if retry:
            while not result:
                machine.resetWDT()
                result = await self._http.post(self.server_uri + url, data)
        machine.resetWDT()
        manage_memory()
        return result

    def online(self):
        return self.id.get('id') and self._network.online()

    def deepsleep(self):
        return self.settings.get('deepsleep')

    def start(self):
        WDT(True)        
        if self.deepsleep():
            loop = uasyncio.get_event_loop()
            for module_type in self.modules:
                if module_type == 'rtc':
                    loop.run_until_complete(self.modules['rtc'].adjust_time(once=True))
                    machine.resetWDT()
                elif module_type == 'climate':
                    loop.run_until_complete(self.modules['climate'].read(once=True))
                    machine.resetWDT()
                    if self.online():
                        loop.run_until_complete(self.post_sensor_data(once=True))
                        machine.resetWDT()
                    if self.modules['climate'].light:
                        loop.run_until_complete(self.modules['climate'].adjust_light(once=True))                
                        machine.resetWDT()
                if self.online():
                    if self.id.get('updates'):
                        loop.run_until_complete(self.check_updates(once=True))
                        machine.resetWDT()
                    if not self.id.get('disable_software_updates'):
                        loop.run_until_complete(self.task_check_software_updates(once=True))
                        machine.resetWDT()
                if self.deepsleep():
                    if self._network:
                        self._network.off()
                    machine.deepsleep(self.deepsleep()*60000)
                
        self.start_async()

    def start_async(self):
        loop = uasyncio.get_event_loop()     
        loop.create_task(self.bg_leds())
        loop.create_task(self.check_wlan_switch())
        if self._network._wlan and (self._network._wlan.mode == AP_IF and self._network._wlan.conf['ssid']):
            loop.create_task(self.delayed_ssid_switch())
        for module_type in self.modules:
            if module_type == 'climate' or module_type == 'power_monitor':
                loop.create_task(self.modules[module_type].read())
                if self.online():
                    loop.create_task(self.post_sensor_data())
            elif module_type =='relay_switch':
                loop.create_task(self.modules['relay_switch'].adjust_switch())                
            elif module_type =='gate':
                loop.create_task(self.modules['gate'].adjust_switch())                
            elif module_type == 'rtc':
                loop.create_task(self.modules['rtc'].adjust_time())
            elif module_type == 'feeder':
                loop.create_task(self.modules['feeder'].check_timers())
        if self.online():
            loop.create_task(self.post_log())
            if self.id.get('updates'):
                loop.create_task(self.check_updates())
            if not self.id.get('disable_software_updates'):
                loop.create_task(self.task_check_software_updates())

        self.append_log_entries('device start')

