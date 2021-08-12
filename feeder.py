import gc
import machine
from machine import Pin, RTC
import uasyncio
import utime
import ulogging

from Suntime import Sun

from timers import Timer, time_tuple_to_seconds
from power_monitor import PowerMonitor
from utils import manage_memory

LOG = ulogging.getLogger("Main")

class FeederTimer(Timer):

    def _on_off(self):
        uasyncio.get_event_loop().create_task(self.relay.run_for(self.duration))

class FeederController:

    def __init__(self, device, conf):

        self._power_monitor = None
        if conf['power_monitor']: 
            try: 
                self._power_monitor = PowerMonitor(conf['power_monitor'], device._conf['i2c'])
            except Exception as exc:
                LOG.exc(exc, 'Power monitor init error')
        self._conf = conf
        self._active = {'timer': False, 'manual': False}
        self.timers = []
        self.init_timers(device.settings['timers'])

        self._log_queue = []
        self._reverse = Pin(conf['reverse'], Pin.OUT)
        self.reverse = False
        self._reverse_threshold = device.settings['reverse_threshold']
        self._reverse_duration = device.settings['reverse_duration']
        self._reverse_delay = 2
        self._delay = 0
        if conf['buttons']:
            for idx, pin in enumerate(conf['buttons']):
                button = Pin(pin, Pin.IN, Pin.PULL_UP)
                reverse = bool(idx)
                button.irq(lambda pin, reverse=reverse: self.on_button(pin, reverse))

    def on_button(self, pin, reverse=False):
        print('button {0} {1} {2}'.format(
            pin, pin.value(), 'reverse' if reverse else ''
        ))
        if pin.value():
            self.on(False, 'manual')
        else:
            self.reverse = reverse
            self.on(True, 'manual')

    def init_timers(self, conf=None):
        self.timers = []
        if conf != None:
            self._conf['timers'] = conf
        sun_data = None
        self.time_table = []
        if ('location' in self.device.settings and self.device.settings['location']
            and 'tzone' in self.device.settings and self.device.settings['tzone']):
            sun = Sun(self.device.settings['location'][0], self.device.settings['location'][1], 
                self.device.settings['tzone'])
            sun_data = [time_tuple_to_seconds(sun.get_sunrise_time()), time_tuple_to_seconds(sun.get_sunset_time())]
        for timer_conf in conf:
            timer = self.create_timer(timer_conf)
            if timer.sun:
                if sun_data:
                    time_on = sun_data[0 if timer.sun == 1 else 1] + timer.time_on
                    timer.time_on = time_on
            self.timers.append(timer)
        self.timers.sort(key=lambda timer: timer.time_on)

    @property
    def state(self):
        return self.pin.value()

    @state.setter
    def state(self, value):
        self.on(value=value)

    def on(self, value=True, source='timer'):
        if self.state != value:
            if self._active[source] != value:
                self._active[source] = value
                for state in self._active.values():
                    if state:
                        self.pin.on()
                        gc.collect()
            self.pin.off()
            self.device.append_log_entries("Feeder {0} {1}{2}".format(
                'start' if self.state else 'stop',
                ' (reverse) ' if self.reverse else '',
                source))
            if value and source == 'manual' and self._power_monitor:
                uasyncio.get_event_loop().create_task(self.check_current())
            if not value:
                self.reverse = False
            manage_memory()

    def off(self, source='timer'):
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
            time = time_tuple_to_seconds(machine.RTC().datetime())
            if time == 0:
                self.init_timers()
            for timer in self.timers:
                if timer.time_on <= time < timer.time_on + timer.duration:
                    start = utime.time()
                    now = start
                    prev_time = start
                    expired = timer.time_on + timer.duration - time
                    retries = 0
                    self.on()
                    while expired < timer.duration and retries < 3:
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
                if timer.time_on > time:
                    break
            manage_memory()
            await uasyncio.sleep(60 - machine.RTC().datetime()[6])

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
        if 'timers' in self.device.settings:
            while self.timers:
                self.delete_timer(0, change_settings=False)
            self.init_timers(self.device.settings['timers']) 
        if 'reverse_threshold' in self.device.settings:
            self._reverse_threshold = self.device.settings['reverse_threshold']
        if 'reverse_duration' in self.device.settings:
            self._reverse_duration = self.device.settings['reverse_duration']

    @reverse.setter
    def reverse(self, value):
        if value != self.reverse:
            self.device.append_log_entries("Feeder reverse {0}".format('on' if value else 'off'))
            self._reverse.value(value)
