from time import sleep_ms

import network
import machine
from machine import WDT
import ujson

from microWebSrv import MicroWebSrv

from climate import ClimateController

CONF = {}
with open('conf.json', 'r') as conf_file:
    CONF = ujson.load(conf_file)
    print('config loaded')

nic = network.WLAN(mode=network.STA_IF)
WLANS_AVAILABLE = [wlan.ssid for wlan in nic.scan()]
if 'ssid' in CONF['wlan'] and CONF['wlan']['ssid'] in WLANS_AVAILABLE:
    nic.connect(CONF['wlan']['ssid'], CONF['wlan']['key'])
if not nic.isconnected():
    AP = network.WLAN(network.AP_IF)
    AP.config(essid=CONF['wlan']['name'], password=CONF['wlan']['ap_key'],\
        authmode=CONF['wlan']['authmode'])
    AP.ifconfig((CONF['wlan']['address'], CONF['wlan']['mask'],\
        CONF['wlan']['address'], CONF['wlan']['address']))
    AP.active(True)

HTML_INDEX = ''
with open('html/index.html', 'r') as _file:
    HTML_INDEX = _file.read()
    modules = {'climate': ''}
    if CONF['climate']['enabled']:
        with open('html/climate.html', 'r') as _file:
            modules['climate'] = _file.read()
    HTML_INDEX = HTML_INDEX % modules

CLIMATE_CONTROLLER = None
if CONF['climate']['enabled']:
    try:
        CLIMATE_CONTROLLER = ClimateController(CONF['climate'])
    except Exception as exc:
        print('Climate controller initialization error')
        print(exc)

def save_conf():
    with open('conf.json', 'w') as _conf_file:
        _conf_file.write(ujson.dumps(CONF))

@MicroWebSrv.route('/api/climate/limits', 'GET')
def limits(http_client, http_response):
    if CLIMATE_CONTROLLER:
        http_response.WriteResponseJSONOk(obj=CLIMATE_CONTROLLER.limits,\
            headers={'cache-control': 'no-store'})

@MicroWebSrv.route('/api/climate/limits', 'POST')
def edit_limits(http_client, http_response):
    if CLIMATE_CONTROLLER:
        req_json = http_client.ReadRequestContentAsJSON()
        CLIMATE_CONTROLLER.limits.update(req_json)
        save_conf()
        limits(http_client, http_response)

@MicroWebSrv.route('/api/timers', 'GET')
def timers(http_client, http_response):
    http_response.WriteResponseJSONOk(obj=CONF['timers'],\
        headers={'cache-control': 'no-store'})

@MicroWebSrv.route('/api/timers', 'POST')
def edit_timers(http_client, http_response):
    req_json = http_client.ReadRequestContentAsJSON()
    for key in req_json.keys():
        if key == 'new':
            CONF['timers'].append(req_json[key])
        else:
            CONF['timers'][int(key)] = req_json[key]
    save_conf()
    timers(http_client, http_response)

@MicroWebSrv.route('/api/timers', 'DELETE')
def delete_timer(http_client, http_response):
    req_json = http_client.ReadRequestContentAsJSON()
    del CONF['tmers'][req_json]
    save_conf()
    timers(http_client, http_response)

@MicroWebSrv.route('/api/settings/wlan', 'GET')
def get_wlan_settings(http_client, http_response):
    http_response.WriteResponseJSONOk(obj=CONF['network'],\
        headers={'cache-control': 'no-store'})

@MicroWebSrv.route('/api/settings/wlan/scan', 'GET')
def get_wlan_scan(http_client, http_response):
    http_response.WriteResponseJSONOk(obj=WLANS_AVAILABLE,\
        headers={'cache-control': 'no-store'})

@MicroWebSrv.route('/api/settings/wlan', 'POST')
def set_wlan_settings(http_client, http_response):
    req_json = http_client.ReadRequestContentAsJSON()
    CONF['network'].update(req_json)
    save_conf()
    http_response.WriteResponseOk(headers=None, contentType="text/html",\
        contentCharset="UTF-8", content='OK')
    machine.reset()

@MicroWebSrv.route('/api/climate/data', 'GET')
def get_data(http_client, http_response):
    if CLIMATE_CONTROLLER:
        http_response.WriteResponseJSONOk(obj=CLIMATE_CONTROLLER.data,\
            headers={'cache-control': 'no-store'})


@MicroWebSrv.route('/', 'GET')
def get_index(http_client, http_response):
    http_response.WriteResponseOk(headers=None, contentType="text/html",\
        contentCharset="UTF-8", content=HTML_INDEX)

srv = MicroWebSrv(webPath="www/")
srv.Start(threaded=True)

DEV_WDT = WDT(timeout=5000)

while True:
    try:
        if CLIMATE_CONTROLLER:
            CLIMATE_CONTROLLER.read()
        else:
            sleep_ms(CONF['sleep'])
    finally:
        DEV_WDT.feed()
