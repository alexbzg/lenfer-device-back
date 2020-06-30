from time import sleep_ms

from machine import Pin, I2C
import onewire
import ds18x20
import ujson

import BME280
from microWebSrv import MicroWebSrv

button_count = 0
ow = onewire.OneWire(Pin(0))
ds = ds18x20.DS18X20(ow)
roms = ds.scan()
temps = [None for rom in roms]

LIMITS_PATH = 'www/limits.json'
LIMITS = {
    'temperature': [
        [20, 35],
        [18, 30]
    ],
    'humidity': [30, 60]
}
def export_limits():
    with open(LIMITS_PATH, 'w') as limits_file:
        limits_file.write(ujson.dumps(LIMITS))

try:
    with open(LIMITS_PATH, 'r') as limits_file:
        LIMITS = ujson.load(limits_file)
        print('Limits file found - load')
except Exception:
    export_limits()
    print('Limits file not found - create from scratch')

@MicroWebSrv.route('/api/limits', 'POST')
def edit_limits(http_client, http_response):
    req_json = http_client.ReadRequestContentAsJSON()
    if 'temperature' in req_json:
        for key in req_json['temperature']:
            LIMITS['temperature'][int(key)] = req_json['temperature'][key]
    if 'humidity' in req_json:
        LIMITS['humidity'] = req_json['humidity']
    export_limits()
    http_response.WriteResponseOk()

srv = MicroWebSrv(webPath='www/')
srv.Start(threaded=True)

def button_pressed(button):
    global button_count
    button_count += 1
    print('Button pressed: ' + str(button_count))

led = Pin(15, Pin.OUT)
button = Pin(2, Pin.IN)
button.irq(button_pressed, Pin.IRQ_RISING)
i2c = I2C(scl=Pin(16), sda=Pin(4), freq=10000)
DATA = {'ow': [None for rom in roms],
        'bme': {'pressure': None, 'temperature': None, 'humidity': None}}

while True:
    led.value(not led.value())
    ds.convert_temp()
    sleep_ms(750)
    for c in range(len(roms)):
        DATA['ow'][c] = int(ds.read_temp(roms[c]))
    bme = BME280.BME280(i2c=i2c)
    DATA['bme']['pressure'] = int((bme.read_pressure() // 256) * 0.0075)
    DATA['bme']['temperature'] = int(bme.read_temperature() / 100)
    DATA['bme']['humidity'] = int(bme.read_humidity() // 1024)
    with open('www/data.json', 'w') as jsonf:
        jsonf.write(ujson.dumps(DATA))
