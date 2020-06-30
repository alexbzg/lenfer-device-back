from time import sleep_ms

from machine import Pin, I2C
import onewire
import ds18x20
import ujson

import BME280
from microWebSrv import MicroWebSrv

OW_PIN = 32
SCL_PIN = 26
SDA_PIN = 14

HEAT_PIN = 19
VENT_OUT_PIN = 23
VENT_MIX_PIN = 22

try:
    
    OW = onewire.OneWire(Pin(OW_PIN))
    DS = ds18x20.DS18X20(OW)
    OW_ROMS = DS.scan()
    OW_TEMPS = [None for rom in OW_ROMS]
except Exception as exc:
    print('Onewire initialization failed')
    print(exc)

HEAT = Pin(HEAT_PIN, Pin.OUT)
VENT_OUT = Pin(VENT_OUT_PIN, Pin.OUT)
VENT_MIX = Pin(VENT_MIX_PIN, Pin.OUT)

LIMITS_PATH = 'www/limits.json'
LIMITS = {
    'temperature': [20, 35],
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
    LIMITS.update(req_json)
    export_limits()
    http_response.WriteResponseOk()

@MicroWebSrv.route('/api/data', 'GET')
def get_data(http_client, http_response):
    http_response.WriteResponseJSONOk(obj=DATA, headers={'cache-control': 'no-store'})

srv = MicroWebSrv(webPath='www/')
srv.Start(threaded=True)

I2C_DEVICE = I2C(scl=Pin(SCL_PIN), sda=Pin(SDA_PIN), freq=10000)
DATA = {'ow': [None for rom in OW_ROMS],
        'bme': {'pressure': None, 'temperature': None, 'humidity': None}}

while True:
    ow_flag = False
    if OW:
        try:
            DS.convert_temp()
            ow_flag = True
        except Exception as exc:
            print('Onewire error')
            print(exc)            
    sleep_ms(750)
    if ow_flag:
        for c, rom in enumerate(OW_ROMS):
            DATA['ow'][c] = round(DS.read_temp(rom), 1)
    try:
        bme = BME280.BME280(i2c=I2C_DEVICE)
        DATA['bme']['pressure'] = int((bme.read_pressure() // 256) * 0.0075)
        DATA['bme']['temperature'] = round((bme.read_temperature() / 100), 1)
        DATA['bme']['humidity'] = int(bme.read_humidity() // 1024)
        with open('www/data.json', 'w') as jsonf:
            print(ujson.dumps(DATA))
        if DATA['bme']['temperature'] < LIMITS['temperature'][0]:
            HEAT.value(1)
        elif DATA['bme']['temperature'] > LIMITS['temperature'][0] + 2:
            HEAT.value(0)
        if ow_flag:
            if DATA['bme']['temperature'] > DATA['ow'][0] + 3 or DATA['bme']['temperature'] < DATA['ow'][0] - 3:
                VENT_MIX.value(1)
            elif DATA['bme']['temperature'] < DATA['ow'][0] + 1 and DATA['bme']['temperature'] > DATA['ow'][0] - 1:
                VENT_MIX.value(0)
        else:
            VENT_MIX.value(0)                            
        if DATA['bme']['humidity'] > LIMITS['humidity'][1] or DATA['bme']['temperature'] > LIMITS['temperature'][1]:
            VENT_OUT.value(1)
        elif DATA['bme']['humidity'] < LIMITS['humidity'][1] - 5 and DATA['bme']['temperature'] < LIMITS['temperature'][1] - 2:
            VENT_OUT.value(0)
    except Exception as exc:
        print(exc)
