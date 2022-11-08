import lib.uasyncio as uasyncio
import machine
import re
import ujson
import logging

from network_controller import NetworkController
from lenfer_device import LenferDevice
from utils import manage_memory, load_json

LOOP = uasyncio.get_event_loop()
LOG = logging.getLogger("Main")

async def wdt_feed():
    await uasyncio.sleep(10)
    machine.resetWDT()

LOOP.create_task(wdt_feed())
machine.WDT(True)

NETWORK_CONTROLLER = NetworkController()

if NETWORK_CONTROLLER.online():
    software_version = load_json('version.json')
    if software_version and software_version['update']:
        from software_update import perform_software_update
        perform_software_update()
        machine.reset()

manage_memory()

DEVICE = LenferDevice(NETWORK_CONTROLLER)
manage_memory()

import lib.picoweb as picoweb
APP = picoweb.WebApp(__name__)

async def send_json(rsp, data):
    await picoweb.start_response(rsp, 'application/json', "200", {'cache-control': 'no-store'})
    await rsp.awrite(ujson.dumps(data).encode('UTF-8'))
    manage_memory()

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
        await send_json(rsp, NETWORK_CONTROLLER._wlan.conf)

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
            machine.RTC().init(req.json)
    await send_json(rsp, machine.RTC().now())

@APP.route('/')
async def get_index(req, rsp):
    await APP.sendfile(rsp, 'html/index.html', content_type="text/html; charset=utf-8")
    manage_memory()

@APP.route('/api/modules')
async def get_modules(req, rsp):
    await send_json(rsp, 
        {module_type: [module.name if module.name else idx for idx, module in enumerate(modules)] for module_type, modules in DEVICE.modules.items()})

@APP.route('/api/device_hash')
async def get_device_hash(req, rsp):
    await send_json(rsp, DEVICE.id['hash'])

@APP.route(re.compile('^\/api\/device\/(\w+)\/(\w+)\/(\w+)$'))
async def api(req, rsp):
    module_type = req.url_match.group(1)
    module_id = int(req.url_match.group(2))
    module_api_method = req.url_match.group(3)
    args = {}
    if req.method == 'POST':
        await req.read_json()
        args = req.json
    if module_type in DEVICE.modules and len(DEVICE.modules[module_type]) > module_id:
        module = DEVICE.modules[module_type][module_id]
        if hasattr(module, 'api') and module.api.get(module_api_method):
            result = await module.api[module_api_method](**args)
            await send_json(rsp, {'result': result})
            return
    await picoweb.http_error(rsp, "404")

try:
    DEVICE.start()
    manage_memory()
    if NETWORK_CONTROLLER._wlan:
        APP.run(debug=True, host=NETWORK_CONTROLLER._wlan.host, port=80)
    else:
        uasyncio.get_event_loop().run_forever()
except Exception as exc:
    LOG.exc(exc, "Abnormal program termination")
    machine.reset()
