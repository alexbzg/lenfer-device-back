from time import sleep_ms
<<<<<<< HEAD

from machine import Pin, I2C
import onewire
import ds18x20

import BME280

class ClimateController:

    def __init__(self, config):

        self.dev_ow = onewire.OneWire(Pin(config['pins']['ow']))
        self.dev_ds = ds18x20.DS18X20(self.dev_ow)
        self.ow_roms = self.dev_ds.scan()

        self.dev_i2c = I2C(scl=Pin(config['pins']['ics']['scl']),\
            sda=Pin(config['pins']['ics']['sda']), freq=10000)

        self.heat = Pin(config['pins']['heat'], Pin.OUT)
        self.vent_out = Pin(config['pins']['vents']['out'], Pin.OUT)
        self.vent_mix = Pin(config['pins']['vents']['mix'], Pin.OUT)

        self.limits = config['limits']
        self.data = {'ow': [None for rom in self.ow_roms],\
                'bme': {'pressure': None, 'temperature': None, 'humidity': None}}
        self.sleep = config['sleep']

    def read(self):

        ow_flag = False
        if self.dev_ow:
            try:
                self.dev_ds.convert_temp()
                ow_flag = True
            except Exception as exc:
                print('Onewire error')
                print(exc)
        sleep_ms(self.sleep)
        if ow_flag:
            for cnt, rom in enumerate(self.ow_roms):
                self.data['ow'][cnt] = round(self.dev_ds.read_temp(rom), 1)
        try:
            bme = BME280.BME280(i2c=self.dev_i2c)
            self.data['bme']['pressure'] = int((bme.read_pressure() // 256) * 0.0075)
            self.data['bme']['temperature'] = round((bme.read_temperature() / 100), 1)
            self.data['bme']['humidity'] = int(bme.read_humidity() // 1024)
            if self.data['bme']['temperature'] < self.limits['temperature'][0]:
                self.heat.value(1)
            elif self.data['bme']['temperature'] > self.limits['temperature'][0] + 2:
                self.heat.value(0)
            if ow_flag:
                if self.data['bme']['temperature'] > self.data['ow'][0] + 3\
                    or self.data['bme']['temperature'] < self.data['ow'][0] - 3:
                    self.vent_mix.value(1)
                elif self.data['bme']['temperature'] < self.data['ow'][0] + 1\
                    and self.data['bme']['temperature'] > self.data['ow'][0] - 1:
                    self.vent_mix.value(0)
            else:
                self.vent_mix.value(0)
            if self.data['bme']['humidity'] > self.limits['humidity'][1]\
                or self.data['bme']['temperature'] > self.limits['temperature'][1]:
                self.vent_out.value(1)
            elif self.data['bme']['humidity'] < self.limits['humidity'][1] - 5 and\
                self.data['bme']['temperature'] < self.limits['temperature'][1] - 2:
                self.vent_out.value(0)
        except Exception as exc:
            print(exc)
=======
>>>>>>> 5c881bfcca8cc76e21627ce13b9edb441a70fda1
