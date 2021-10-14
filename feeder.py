import gc
import machine
from machine import Pin, RTC
import lib.uasyncio as uasyncio
import utime
import lib.ulogging as ulogging



from relay_switch import RelaySwitchController
from timers import Timer, time_tuple_to_seconds

from utils import manage_memory

LOG = ulogging.getLogger("Main")

class FeederTimer(Timer):

    def _on_off(self):
        uasyncio.get_event_loop().create_task(self.relay.run_for(self.duration))

class FeederController(RelaySwitchController):

    def __init__(self, device, conf):
        RelaySwitchController.__init__(self, device, conf)
        self._power_monitor = None
        if conf.get('power_monitor'): 
            from power_monitor import PowerMonitor
            try: 
                self._power_monitor = PowerMonitor(conf['power_monitor'], device._conf['i2c'])
            except Exception as exc:
                LOG.exc(exc, 'Power monitor init error')

        self._log_queue = []
        self._active = {}
        self._reverse = Pin(conf['reverse'], Pin.OUT)
        self.reverse = False
        self._reverse_threshold = device.settings.get('reverse_threshold')
        self._reverse_duration = device.settings.get('reverse_duration')
        self._expired_limit = device.settings.get('expired_limit')
        self._reverse_delay = 2
        self._delay = 0
        self.flag_pins = None
        if conf.get('buttons'):
            for idx, pin in enumerate(conf['buttons']):
                button = Pin(pin, Pin.IN, Pin.PULL_UP)
                reverse = bool(idx)
                button.irq(lambda pin, reverse=reverse: self.on_button(pin, reverse))
        if conf.get('flag_pins'):
            self.flag_pins = [Pin(pin, Pin.IN, Pin.PULL_UP) for pin in conf['flag_pins']]

    def on_button(self, pin, reverse=False):
        print('button {0} {1} {2}'.format(
            pin, pin.value(), 'reverse' if reverse else ''
        ))
        if pin.value():
            self.on(False, 'manual')
        else:
            self.reverse = reverse
            self.on(True, 'manual')

    @property
    def state(self):
        return self.pin.value()

    @state.setter
    def state(self, value):
        self.on(value=value)

    def on(self, value=True, source='manual'):
        if value:            
            self._active[source] = True
        else:
            if source in self._active:
                del self._active[source]
        LOG.debug('Feeder active: %s' % self._active)
        LOG.debug('Feeder state: %s' % self.state)
        if self.state != bool(self._active):
            if self.state:
                LOG.debug('feeder pin off')
                self.pin.value(0)
                self.reverse = False
                self.device.append_log_entries("Feeder stop {0}{1}".format(
                    ' (reverse) ' if self.reverse else '',
                    'manual' if source == 'manual' else 'timer'))                
            else:
                LOG.debug('feeder pin on')
                self.pin.value(1)
                self.device.append_log_entries("Feeder start {0}{1}".format(
                    ' (reverse) ' if self.reverse else '',
                    'manual' if source == 'manual' else 'timer'))                
        if 'manual' in self._active and len(self._active.keys()) == 1 and self._power_monitor:
            uasyncio.get_event_loop().create_task(self.check_current())
        LOG.debug('Feeder state: %s' % self.state)
        manage_memory()

    def off(self, source='manual'):
        self.on(False, source)

    async def check_current(self):
        if self._power_monitor:
            while self.state:
                cur = self._power_monitor.current()
                self.device.append_log_entries("Feeder current: {0:+.2f}".format(cur))
                await uasyncio.sleep(1)

    async def check_timers(self):
        off = None
        while True:
            time = time_tuple_to_seconds(machine.RTC().now())
            if time == 0:
                self.init_timers()
            for timer in self.timers:
                if timer.time_on <= time < timer.time_on + timer.duration:
                    start = utime.time()
                    now = start
                    prev_time = start
                    expired = time - timer.time_on
                    retries = 0
                    self.on(source=timer)

                    def continue_flag():
                        nonlocal retries, expired
                        if retries >= 3:
                            return False
                        if self._expired_limit and expired > self._expired_limit:
                            return False    
                        if timer.duration > 0 and expired > timer.duration:
                            return False
                        if self.flag_pins:
                            flag_pin = self.flag_pins[1 if self.reverse else 0]
                            if flag_pin.value():
                                self.device.append_log_entries("Feeder task success")
                                return False
                        return True

                    while continue_flag():
                        await uasyncio.sleep(1)
                        now = utime.time()
                        current = self._power_monitor.current() if self._power_monitor else None
                        if current:
                            self.device.append_log_entries("Feeder current: {0:+.2f}".format(current))
                        expired += now - prev_time
                        prev_time = now
                        if current and current > self._reverse_threshold:
                            await self.engine_reverse(True)
                            await uasyncio.sleep(self._reverse_duration)
                            expired -= self._reverse_duration + 2 * self._reverse_delay
                            retries += 1
                            await self.engine_reverse(False)
                    self.off(source=timer)
                if timer.time_on > time:
                    break
            manage_memory()
            await uasyncio.sleep(60 - machine.RTC().now()[6])

    async def run_for(self, duration):
        start = utime.time()
        now = start
        prev_time = start
        expired = 0
        retries = 0
        self.on()
        while expired < duration and retries < 3:
            await uasyncio.sleep(1)
            now = utime.time()
            current = self._power_monitor.current() if self._power_monitor else None
            if current:
                self.device.append_log_entries("Feeder current: {0:+.2f}".format(current))
            expired += now - prev_time
            prev_time = now
            if current and current > self._reverse_threshold:
                await self.engine_reverse(True)
                await uasyncio.sleep(self._reverse_duration)
                expired -= self._reverse_duration + 2 * self._reverse_delay
                retries += 1
                await self.engine_reverse(False)
        self.off()

    async def engine_reverse(self, reverse):
        self.pin.value(False)
        await uasyncio.sleep(self._reverse_delay)
        self.reverse = reverse
        await uasyncio.sleep(self._reverse_delay)
        self.pin.value(True)

    def create_timer(self, conf):
        return FeederTimer(conf, self)

    @property
    def reverse(self):
        return self._reverse.value()

    def update_settings(self):
        RelaySwitchController.update_settings(self)
        if 'reverse_threshold' in self.device.settings:
            self._reverse_threshold = self.device.settings['reverse_threshold']
        if 'reverse_duration' in self.device.settings:
            self._reverse_duration = self.device.settings['reverse_duration']

    @reverse.setter
    def reverse(self, value):
        if value != self.reverse:
            self.device.append_log_entries("Feeder reverse {0}".format('on' if value else 'off'))
            self._reverse.value(value)
