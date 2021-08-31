import machine
import utime

from utils import load_json, save_json

class Schedule:

    def __init__(self):
        self._schedule = load_json('schedule.json')
        if not self._schedule:
            self._schedule = {'hash': None, 'start': None}

    def update(self, value):
        save_json(value, 'schedule.json')
        self._schedule = value

    def current_day(self):
        if self._schedule and 'items' in self._schedule and self._schedule['items'] and 'start' in self._schedule and self._schedule['start']:
            day_no = 0
            start = utime.mktime(self._schedule['start'])
            today = utime.mktime(machine.RTC().datetime())
            if start < today:
                day_no = int((today-start)/86400)
            if day_no >= len(self._schedule['items']):
                day_no = len(self._schedule['items']) - 1
            return self._schedule['items'][day_no]
        else:
            return None

    def param_idx(self, param):
        return self._schedule['params_list'].index(param)

    @property
    def params(self):
        return self._schedule['params']

    @property
    def hash(self):
        return self._schedule['hash']

    @property
    def start(self):
        return self._schedule['start']
    




