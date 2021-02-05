import gc
import re

import uasyncio
import machine
import ujson
import ulogging

import picoweb

from wlan import WlanController
from lenfer_device import LenferDevice
from software_update import load_version, perform_software_update
from utils import manage_memory

APP = picoweb.WebApp(__name__)

LOG = ulogging.getLogger("Main")
LOG.setLevel(ulogging.DEBUG)

WLAN = WlanController()

if WLAN.online():
    software_version = load_version()
    if software_version['update']:
        perform_software_update()
        machine.reset()

manage_memory()

DEVICE = LenferDevice(WLAN)

async def send_json(rsp, data):
    await picoweb.start_response(rsp, 'application/json', "200", {'cache-control': 'no-store'})
    await rsp.awrite(ujson.dumps(data).encode('UTF-8'))
    gc.collect()

@APP.route('/api/climate/limits')
async def limits(req, rsp):
    ctrl = DEVICE.modules['climate']
    if ctrl:
        if req.method == "POST":
            await req.read_json()
            ctrl.limits.update(req.json)
            DEVICE.save_settings()
        await send_json(rsp, ctrl.limits)

@APP.route(re.compile(r'/api/(\w+)/sensors/info'))
async def get_sensors_info(req, rsp):
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

def get_ctrl(req):
    ctrl_type = picoweb.utils.unquote_plus(req.url_match.group(1))
    return DEVICE.modules[ctrl_type]

@APP.route(re.compile(r'/api/(\w+)/sensors/data'))
async def get_sensors_data(req, rsp):
    ctrl = get_ctrl(req)
    if ctrl and hasattr(ctrl, 'data'):
        await send_json(rsp, {str(_id): value  for _id, value in ctrl.data.items()})
    else:
        gc.collect()

@APP.route(re.compile(r'/api/(\w+)/timers'))
async def timers(req, rsp):
    ctrl = get_ctrl(req)
    if ctrl:
        if req.method == 'POST':
            await req.read_json()
            for key in req.json.keys():
                timer_conf = req.json[key]
                if key == '-1':
                    ctrl.add_timer(timer_conf)
                else:
                    ctrl.update_timer(int(key), timer_conf)
            DEVICE.save_settings()
        elif req.method == 'DELETE':
            await req.read_json()
            ctrl.delete_timer(req.json)
            DEVICE.save_settings()
        await send_json(rsp, DEVICE.settings['timers'])

@APP.route('/api/settings/wlan')
async def get_wlan_settings(req, rsp):
    if req.method == 'POST':
        await req.read_json()
        reset_flag = ((WLAN.conf['enable_ssid'] != req.json['enable_ssid']) or
            (req.json['enable_ssid'] and
                (WLAN.conf['ssid'] != req.json['ssid'] or
                    WLAN.conf['key'] != req.json['key'])) or
            ((not req.json['enable_ssid']) and
                (WLAN.conf['name'] != req.json['name'] or
                    WLAN.conf['ap_key'] != req.json['ap_key'])))
        WLAN.conf.update(req.json)
        WLAN.save_conf()
        if DEVICE:
            DEVICE.status["ssid_delay"] = True
        if reset_flag:
            uasyncio.get_event_loop().create_task(delayed_reset(5))
        await send_json(rsp, {"reset": reset_flag})
    else:
        await send_json(rsp, WLAN.conf)

async def delayed_reset(delay):
    await uasyncio.sleep(delay)
    machine.reset()

@APP.route('/api/climate/data')
async def get_data(req, rsp):
    ctrl = DEVICE.modules['climate']
    if ctrl:
        await send_json(rsp, ctrl.data)

@APP.route('/api/time')
async def get_time(req, rsp):
    if req.method == 'POST':
        ctrl = DEVICE.modules['rtc']
        await req.read_json()
        if ctrl:
            ctrl.set_time(req.json)
        else:
            machine.RTC().datetime(req.json)
    await send_json(rsp, machine.RTC().datetime())

@APP.route('/')
async def get_index(req, rsp):
    await APP.sendfile(rsp, 'html/index.html', content_type="text/html; charset=utf-8")
    gc.collect()

@APP.route(re.compile(r'/api/(\w+)/relay'))
async def relay_api(req, rsp):
    ctrl = get_ctrl(req)
    if ctrl:
        if req.method == 'POST':
            await req.read_json()
            if 'reverse' in req.json and hasattr(ctrl, 'reverse'):
                ctrl.reverse = req.json['reverse']
            ctrl.on(value=req.json['value'], source='manual')
            if not req.json['value'] and hasattr(ctrl, 'reverse') and ctrl.reverse:
                ctrl.reverse = False
            await send_json(rsp, 'OK')
        else:
            await picoweb.start_response(rsp, status="405")
        gc.collect()

@APP.route('/api/modules')
async def get_modules(req, rsp):
    await send_json(rsp, {key: bool(value) for key, value in DEVICE.modules.items()})

DEVICE.start_async()
gc.collect()
APP.run(debug=True, host=WLAN.host, port=80)
