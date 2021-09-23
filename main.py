import sys
import gc
import re

import lib.uasyncio as uasyncio
import machine
import ujson
import lib.ulogging as ulogging
import sys

import lib.picoweb as picoweb

from network_controller import NetworkController
from lenfer_device import LenferDevice
from software_update import load_version, perform_software_update
from utils import manage_memory, load_json

APP = picoweb.WebApp(__name__)

LOG = ulogging.getLogger("Main")
LOG.setLevel(ulogging.DEBUG)

LOOP = uasyncio.get_event_loop()

async def wdt_feed():
    await uasyncio.sleep(10)
    machine.resetWDT()

LOOP.create_task(wdt_feed())
machine.WDT(True)

NETWORK_CONTROLLER = NetworkController()

if NETWORK_CONTROLLER.online():
    software_version = load_version()
    if software_version['update']:
        perform_software_update()
        machine.reset()

manage_memory()

DEVICE = LenferDevice(NETWORK_CONTROLLER)

async def send_json(rsp, data):
    await picoweb.start_response(rsp, 'application/json', "200", {'cache-control': 'no-store'})
    await rsp.awrite(ujson.dumps(data).encode('UTF-8'))
    gc.collect()


@APP.route('/api/settings/wlan')
async def get_wlan_settings(req, rsp):
    if req.method == 'POST':
        await req.read_json()
        NETWORK_CONTROLLER._wlan.conf.update(req.json)
        NETWORK_CONTROLLER._wlan.save_conf()
        if DEVICE:
            DEVICE.status["ssid_delay"] = True
        uasyncio.get_event_loop().create_task(delayed_reset(5))
        await send_json(rsp, {"reset": True})
    else:
        await send_json(rsp, WLAN.conf)

async def delayed_reset(delay):
    await uasyncio.sleep(delay)
    NETWORK_CONTROLLER._wlan.enable_ssid(True)
    #machine.reset()

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

@APP.route('/api/modules')
async def get_modules(req, rsp):
    await send_json(rsp, {key: bool(value) for key, value in DEVICE.modules.items()})

@APP.route('/api/device_hash')
async def get_device_hash(req, rsp):
    await send_json(rsp, DEVICE.id['hash'])

try:
    DEVICE.start()
    gc.collect()
    if NETWORK_CONTROLLER._wlan:
        APP.run(debug=True, host=NETWORK_CONTROLLER._wlan.host, port=80)
    else:
        uasyncio.get_event_loop().run_forever()
except Exception as exc:
    LOG.exc(exc, "Abnormal program termination")
    machine.reset()
