import gc
import uasyncio
from time import sleep

import network
import machine
from machine import WDT, Pin
import ujson
import utime

import picoweb

from climate import ClimateController
from timers import RtcController, Timer

APP = picoweb.WebApp(__name__)

CONF = {}
with open('conf.json', 'r') as conf_file:
    CONF = ujson.load(conf_file)
    print('config loaded')

nic = network.WLAN(network.STA_IF)
nic.active(True)
WLANS_AVAILABLE = [wlan[0].decode('utf-8') for wlan in nic.scan()]
print(WLANS_AVAILABLE)
HOST = '0.0.0.0'
if 'ssid' in CONF['wlan'] and CONF['wlan']['ssid'] in WLANS_AVAILABLE:
    nic.connect(CONF['wlan']['ssid'], CONF['wlan']['key'])
    sleep(5)
    HOST = nic.ifconfig()[0]
if not nic.isconnected():
    AP = network.WLAN(network.AP_IF)
    AP.active(True)
    AP.config(essid=CONF['wlan']['name'], password=CONF['wlan']['ap_key'],\
        authmode=CONF['wlan']['authmode'])
    AP.ifconfig((CONF['wlan']['address'], CONF['wlan']['mask'],\
        CONF['wlan']['address'], CONF['wlan']['address']))
    HOST = CONF['wlan']['address']

RTC_CONTROLLER = RtcController(scl_pin_no=CONF["i2c"]["scl"], sda_pin_no=CONF["i2c"]["sda"])
RTC_CONTROLLER.get_time(set_rtc=True)

CLIMATE_CONTROLLER = None
if CONF['modules']['climate']['enabled']:
    try:
        CLIMATE_CONTROLLER = ClimateController(CONF['modules']['climate'])
    except Exception as exc:
        print('Climate controller initialization error')
        print(exc)

LED = Pin(33, Pin.OUT)
Pin(2, Pin.OUT).value(False)

TIMERS = []
def update_timers():
    global TIMERS
    TIMERS = [Timer(timer_conf) for timer_conf in CONF['timers']]
update_timers()

def save_conf():
    with open('conf.json', 'w') as _conf_file:
        _conf_file.write(ujson.dumps(CONF))

async def send_json(rsp, data):
    await picoweb.start_response(rsp, 'application/json', {'cache-control': 'no-store'})
    await rsp.awrite(ujson.dumps(data))
    gc.collect()

@APP.route('/api/climate/limits')
def limits(req, rsp):
    if CLIMATE_CONTROLLER:
        if req.method == "POST":
            await req.read_json()
            CLIMATE_CONTROLLER.limits.update(req.json)
            save_conf()
        await send_json(rsp, CLIMATE_CONTROLLER.limits)        

@APP.route('/api/timers')
def timers(req, rsp):
    if req.method == 'POST':
        await req.read_json()
        for key in req.json.keys():
            if key == 'new':
                CONF['timers'].append(req.json[key])
            else:
                CONF['timers'][int(key)] = req.json[key]
        save_conf()
        update_timers()
    elif req.method == 'DELETE':
        await req.read_json()
        del CONF['timers'][req.json]
        save_conf()
        update_timers()
    await send_json(rsp, CONF['timers'])

@APP.route('/api/settings/wlan')
def get_wlan_settings(req, rsp):
    if req.method == 'POST':
        await req.read_json()
        CONF['wlan'].update(req.json)
        save_conf()
        await picoweb.start_response(rsp, "text/plain")
        await rsp.awrite("Ok")
        await asyncio.sleep(5)
        machine.reset()
    else:
        await send_json(rsp, CONF['wlan'])        

@APP.route('/api/settings/wlan/scan')
def get_wlan_scan(req, rsp):
    await send_json(rsp, WLANS_AVAILABLE)

@APP.route('/api/climate/data')
def get_data(req, rsp):
    if CLIMATE_CONTROLLER:
        await send_json(rsp, CLIMATE_CONTROLLER.data)

@APP.route('/api/time')
def get_time(req, rsp):
    if req.method == 'POST':
        await req.read_json()
        try:
            utime.mktime(req.json)
        except:
            await picoweb.start_response(resp, status="400")
            await resp.awrite("Некорректная дата/время!")
            gc.collect()
            return
        RTC_CONTROLLER.set_time(req.json)
    await send_json(rsp, machine.RTC().datetime())

@APP.route('/')
def get_index(req, rsp):
    await APP.sendfile(rsp, 'html/index.html', content_type="text/html; charset=utf-8")
    gc.collect()

#DEV_WDT = WDT(timeout=5000)

async def adjust_rtc():
    while True:
        RTC_CONTROLLER.get_time(set_rtc=True)
        await uasyncio.sleep(600)
        gc.collect()

async def bg_work():
    led_state = False
    while True:
        led_state = not led_state
        LED.value(1 if led_state else 0)
        try:
            if CLIMATE_CONTROLLER:
                CLIMATE_CONTROLLER.read()
            else:
                await uasyncio.sleep_ms(CONF['sleep'])
        finally:
            #DEV_WDT.feed()
            gc.collect()

async def check_timers():
    while True:
        time_tuple = machine.RTC().datetime()
        time = time_tuple[4]*60 + time_tuple[5]
        for timer in TIMERS:
            timer.check(time)
        gc.collect()
        await uasyncio.sleep(60)


LOOP = uasyncio.get_event_loop()
LOOP.create_task(bg_work())
LOOP.create_task(adjust_rtc())
LOOP.create_task(check_timers())
APP.run(debug=True, host=HOST, port=80)
