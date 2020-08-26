import gc
import uasyncio
from time import sleep

import network
import machine
from machine import WDT, Pin
import ujson
import utime
import ulogging

import picoweb

from climate import ClimateController
from timers import RtcController, Timer
from relay import Relay

APP = picoweb.WebApp(__name__)

LOG = ulogging.getLogger("main")

CONF = {}
def save_conf():
    with open('conf.json', 'w') as _conf_file:
        _conf_file.write(ujson.dumps(CONF))

def load_def_conf():
    global CONF
    with open('conf_default.json', 'r') as conf_def_file:
        CONF = ujson.load(conf_def_file)
        print('default config loaded')
        save_conf()
try:
    with open('conf.json', 'r') as conf_file:
        CONF = ujson.load(conf_file)
        if CONF:
            print('config loaded')               
except Exception as exc:
    LOG.exc(exc, 'Config load error')

if not CONF:
    load_def_conf()

RTC_CONTROLLER = RtcController(scl_pin_no=CONF["i2c"]["scl"], sda_pin_no=CONF["i2c"]["sda"])
RTC_CONTROLLER.get_time(set_rtc=True)

CLIMATE_CONTROLLER = None
if CONF['modules']['climate']['enabled']:
    try:
        CLIMATE_CONTROLLER = ClimateController(CONF['modules']['climate'])
    except Exception as exc:
        LOG.exc(exc, 'Climate controller initialization error')

LEDS = {led: Pin(pin_no, Pin.OUT) for led, pin_no in CONF['leds'].items()}
for led in LEDS.values():
    led.off()

STATUS = {"wlan": None, "factory_reset": False}

nic = network.WLAN(network.STA_IF)
nic.active(True)
WLANS_AVAILABLE = [wlan[0].decode('utf-8') for wlan in nic.scan()]
print(WLANS_AVAILABLE)
HOST = '0.0.0.0'
if 'ssid' in CONF['wlan'] and CONF['wlan']['ssid'] in WLANS_AVAILABLE:
    nic.connect(CONF['wlan']['ssid'], CONF['wlan']['key'])
    sleep(5)
    HOST = nic.ifconfig()[0]
if nic.isconnected():
    STATUS["wlan"] = network.STA_IF
else:
    AP = network.WLAN(network.AP_IF)
    AP.active(True)
    AP.config(essid=CONF['wlan']['name'], password=CONF['wlan']['ap_key'],\
        authmode=CONF['wlan']['authmode'])
    AP.ifconfig((CONF['wlan']['address'], CONF['wlan']['mask'],\
        CONF['wlan']['address'], CONF['wlan']['address']))
    HOST = CONF['wlan']['address']
    STATUS["wlan"] = network.AP_IF

    
async def blink(leds, count, time_ms):
    for co in range(count):
        for led in leds:
            LEDS[led].on()
        await uasyncio.sleep_ms(time_ms)
        for led in leds:
            LEDS[led].off()
        if co < count - 1:
            await uasyncio.sleep_ms(time_ms)

RELAYS = [Relay(pin_no) for pin_no in CONF["relays"]]

TIMERS = []
def update_timers():
    global TIMERS
    TIMERS = [Timer(timer_conf, RELAYS[0]) for timer_conf in CONF['timers']]
    gc.collect()
update_timers()

RELAY_BUTTONS = [Pin(pin_no, Pin.IN) for pin_no in CONF["relay_buttons"]]

def set_relay_button_irq(idx):

    def handler(pin):
        RELAYS[idx].on(value=not RELAY_BUTTONS[idx].value(), source='manual')

    RELAY_BUTTONS[idx].irq(handler)

for idx in range(len(RELAY_BUTTONS)):
    set_relay_button_irq(idx)

def factory_reset_irq(pin):
    if pin.value():
        if STATUS['factory_reset'] == 'pending':
            STATUS['factory_reset'] == 'cancel'
    else:
        if not STATUS['factory_reset']:
            STATUS['factory_reset'] = 'pending'
            uasyncio.get_event_loop().create_task(factory_reset())
    
async def factory_reset():
    LOG.info('factory reset is pending')
    for co in range(50):
        await uasyncio.sleep_ms(100)
        if STATUS['factory_reset'] != 'pending':
            LOG.info('factory reset is cancelled')            
            STATUS['factory_reset'] = None
            return
    for led in LEDS.values():
        led.on()
    load_def_conf()
    save_conf()
    machine.reset()


FACTORY_RESET_BUTTON = Pin(CONF['factory_reset'], Pin.IN)
FACTORY_RESET_BUTTON.irq(factory_reset_irq)

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
        await uasyncio.sleep(5)
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

@APP.route('/api/relay')
def relay_api(req, rsp):
    if req.method == 'POST':
        await req.read_json()
        RELAYS[req.json['relay']].on(value=req.json['value'], source='manual')
        await picoweb.start_response(rsp, 'text/plain', {'cache-control': 'no-store'})
        await rsp.awrite('Ok')
    else:
        await picoweb.start_response(resp, status="405")
    gc.collect()

#DEV_WDT = WDT(timeout=5000)

async def adjust_rtc():
    while True:
        RTC_CONTROLLER.get_time(set_rtc=True)
        await uasyncio.sleep(600)
        gc.collect()

async def check_timers():
    while True:
        time_tuple = machine.RTC().datetime()
        time = time_tuple[4]*60 + time_tuple[5]
        for timer in TIMERS:
            timer.check(time)
        gc.collect()
        await uasyncio.sleep(60)

async def bg_leds():
    while True:
        await blink(("status",), 1 if STATUS["wlan"] == network.AP_IF else 2, 100)
        await uasyncio.sleep(5)
        gc.collect()

LOOP = uasyncio.get_event_loop()
LOOP.create_task(bg_leds())
LOOP.create_task(adjust_rtc())
LOOP.create_task(check_timers())
APP.run(debug=True, host=HOST, port=80)
