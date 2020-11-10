import gc
from time import sleep
import re

import uasyncio
import network
import machine
from machine import Pin
import ujson
import ulogging

import picoweb

from lenfer_device import LenferDevice

APP = picoweb.WebApp(__name__)

LOG = ulogging.getLogger("Main")

DEVICE = None

CONF = {}
def save_conf():
    with open('conf.json', 'w', encoding="utf-8") as _conf_file:
        _conf_file.write(ujson.dumps(CONF))
    if DEVICE:
        DEVICE.status["ssid_delay"] = True

def load_def_conf():
    global CONF
    with open('conf_default.json', 'r', encoding="utf-8") as conf_def_file:
        CONF = ujson.load(conf_def_file)
        print('default config loaded')
        save_conf()
try:
    with open('conf.json', 'r', encoding="utf-8") as conf_file:
        CONF = ujson.load(conf_file)
        if CONF:
            print('config loaded')
except Exception as exc:
    LOG.exc(exc, 'Config load error')

if not CONF:
    load_def_conf()

DEVICE = LenferDevice(CONF)

nic = None
WLANS_AVAILABLE = None
nic = network.WLAN(network.STA_IF)
nic.active(True)
#WLANS_AVAILABLE = [wlan[0].decode('utf-8') for wlan in nic.scan()]
#print(WLANS_AVAILABLE)
HOST = '0.0.0.0'
if CONF['wlan']['enable_ssid'] and CONF['wlan']['ssid']:
    try:
        DEVICE.status["ssid_failure"] = True
        nic.connect(CONF['wlan']['ssid'], CONF['wlan']['key'])
        sleep(5)
        HOST = nic.ifconfig()[0]
    except Exception as exc:
        LOG.exc(exc, 'WLAN connect error')
        

if nic and nic.isconnected():
    DEVICE.status["wlan"] = network.STA_IF
    DEVICE.status["ssid_failure"] = False
else:
    if nic:
        nic.active(False)
    AP = network.WLAN(network.AP_IF)
    AP.active(True)
    authmode = 4 if CONF['wlan']['ap_key'] else 0
    AP.config(essid=CONF['wlan']['name'], password=CONF['wlan']['ap_key'],\
        authmode=authmode)
    AP.ifconfig((CONF['wlan']['address'], CONF['wlan']['mask'],\
        CONF['wlan']['address'], CONF['wlan']['address']))
    HOST = CONF['wlan']['address']
    DEVICE.status["wlan"] = network.AP_IF

def wlan_switch_irq(pin):
    if pin.value():
        LOG.info('wlan switch was activated')
        DEVICE.status['wlan_switch'] = 'true'

WLAN_SWITCH_BUTTON = Pin(CONF['wlan_switch'], Pin.IN, Pin.PULL_UP)
WLAN_SWITCH_BUTTON.irq(wlan_switch_irq)

def factory_reset_irq(pin):
    if pin.value():
        if DEVICE.status['factory_reset'] == 'pending':
            DEVICE.status['factory_reset'] = 'cancel'
    else:
        if not DEVICE.status['factory_reset']:
            DEVICE.status['factory_reset'] = 'pending'
            uasyncio.get_event_loop().create_task(factory_reset())

async def factory_reset():
    LOG.info('factory reset is pending')
    for co in range(50):
        await uasyncio.sleep_ms(100)
        if DEVICE.status['factory_reset'] != 'pending':
            LOG.info('factory reset is cancelled')
            DEVICE.status['factory_reset'] = None
            return
    for led in DEVICE.leds.values():
        led.on()
    load_def_conf()
    save_conf()
    machine.reset()
if 'factory_reset' in CONF and CONF['factory_reset']:
    FACTORY_RESET_BUTTON = Pin(CONF['factory_reset'], Pin.IN)
    FACTORY_RESET_BUTTON.irq(factory_reset_irq)

async def send_json(rsp, data):
    await picoweb.start_response(rsp, 'application/json', "200", {'cache-control': 'no-store'})
    await rsp.awrite(ujson.dumps(data).encode('UTF-8'))
    gc.collect()

@APP.route('/api/climate/limits')
def limits(req, rsp):
    ctrl = DEVICE.modules['climate']
    if ctrl:
        if req.method == "POST":
            await req.read_json()
            ctrl.limits.update(req.json)
            save_conf()
        await send_json(rsp, ctrl.limits)

@APP.route(re.compile(r'/api/(\w+)/sensors/info'))
def get_sensors_info(req, rsp):
    ctrl_type = picoweb.utils.unquote_plus(req.url_match.group(1))
    ctrl = DEVICE.modules[ctrl_type]
    if ctrl and hasattr(ctrl, 'sensors_roles'):
        await send_json(rsp, [
            {'type': _type,
             'limits': ctrl.limits[_type],
             'sensors': [
                 {'id': _id, 'title': ctrl.sensors_titles[str(_id)]}
                 for _id in sensors
             ]} for _type, sensors in ctrl.sensors_roles.items()
        ])
    else:
        gc.collect()

@APP.route(re.compile(r'/api/(\w+)/sensors/data'))
def get_sensors_data(req, rsp):
    ctrl_type = picoweb.utils.unquote_plus(req.url_match.group(1))
    ctrl = DEVICE.modules[ctrl_type]
    if ctrl and hasattr(ctrl, 'data'):
        await send_json(rsp, {str(_id): value  for _id, value in ctrl.data.items()})
    else:
        gc.collect()

@APP.route('/api/timers')
def timers(req, rsp):
    ctrl = DEVICE.modules['relays']
    if ctrl:
        if req.method == 'POST':
            await req.read_json()
            for key in req.json.keys():
                timer_conf = req.json[key]
                if key == 'new':
                    ctrl.add_timer(timer_conf)
                else:
                    ctrl.update_timer(int(key), timer_conf)
            save_conf()
        elif req.method == 'DELETE':
            await req.read_json()
            ctrl.delete_timer(req.json)
            save_conf()
        await send_json(rsp, CONF['timers'])

@APP.route('/api/settings/wlan')
def get_wlan_settings(req, rsp):
    if req.method == 'POST':
        await req.read_json()
        reset_flag = (CONF['wlan']['enable_ssid'] != req.json['enable_ssid']) or\
            (req.json['enable_ssid'] and\
                (CONF['wlan']['ssid'] != req.json['ssid'] or\
                    CONF['wlan']['key'] != req.json['key'])) or\
            ((not req.json['enable_ssid']) and\
                (CONF['wlan']['name'] != req.json['name'] or\
                    CONF['wlan']['ap_key'] != req.json['ap_key']))
        CONF['wlan'].update(req.json)
        save_conf()
        await picoweb.start_response(rsp, "text/plain")
        await send_json(rsp, {"reset": reset_flag})
        await uasyncio.sleep(5)
        if reset_flag:
            machine.reset()
    else:
        await send_json(rsp, CONF['wlan'])

@APP.route('/api/settings/wlan/scan')
def get_wlan_scan(req, rsp):
    await send_json(rsp, WLANS_AVAILABLE)

@APP.route('/api/climate/data')
def get_data(req, rsp):
    ctrl = DEVICE.modules['climate']
    if ctrl:
        await send_json(rsp, ctrl.data)

@APP.route('/api/time')
def get_time(req, rsp):
    if req.method == 'POST':
        ctrl = DEVICE.modules['rtc']
        if ctrl:
            await req.read_json()
            ctrl.set_time(req.json)
        else:
            machine.RTC().datetime(req.json)    
    await send_json(rsp, machine.RTC().datetime())

@APP.route('/')
def get_index(req, rsp):
    await APP.sendfile(rsp, 'html/index.html', content_type="text/html; charset=utf-8")
    gc.collect()

@APP.route('/api/relay')
def relay_api(req, rsp):
    ctrl = DEVICE.modules['relays']
    if ctrl:
        if req.method == 'POST':
            await req.read_json()
            ctrl.relays[req.json['relay']].on(value=req.json['value'], source='manual')
            await picoweb.start_response(rsp, 'text/plain', {'cache-control': 'no-store'})
            await rsp.awrite('Ok')
        else:
            await picoweb.start_response(rsp, status="405")
        gc.collect()

@APP.route('/api/modules')
def get_modules(req, rsp):
    await send_json(rsp, {key: bool(value) for key, value in DEVICE.modules.items()})

async def check_wlan_switch():
    while True:
        await uasyncio.sleep(5)
        if DEVICE.status['wlan_switch'] and DEVICE.status['wlan'] == network.STA_IF:
            enable_ssid(False)

def enable_ssid(val):
    CONF['wlan']['enable_ssid'] = val
    save_conf()
    machine.reset()

async def delayed_ssid_switch():
    LOG.info("delayed wlan switch activated")
    while True:
        await uasyncio.sleep(120)
        if DEVICE.status["ssid_delay"]:
            DEVICE.status["ssid_delay"] = False
        else:
            enable_ssid(True)

DEVICE.start_async()
LOOP = uasyncio.get_event_loop()
LOOP.create_task(check_wlan_switch())
if DEVICE.status['wlan'] == network.AP_IF and (not DEVICE.status["ssid_failure"]) and CONF['wlan']['ssid']:
    LOOP.create_task(delayed_ssid_switch())
gc.collect()
APP.run(debug=True, host=HOST, port=80)
