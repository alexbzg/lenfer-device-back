from time import sleep_ms

from machine import WDT
import ujson

from microWebSrv import MicroWebSrv

from climate import ClimateController

CONF = {}
with open('conf.json', 'r') as conf_file:
    CONF = ujson.load(conf_file)
    print('config loaded')

HTML_INDEX = ''
with open('html/index', 'r') as _file:
    HTML_INDEX = _file.read()
    modules = {'climate': ''}
    if CONF['climate']['enabled']:
        with open('html/climate', 'r') as _file:
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
def edit_timers(http_client, http_response):
    req_json = http_client.ReadRequestContentAsJSON()
    del CONF['tmers'][req_json]
    save_conf()
    timers(http_client, http_response)

@MicroWebSrv.route('/api/climate/data', 'GET')
def get_data(http_client, http_response):
    if CLIMATE_CONTROLLER:
        http_response.WriteResponseJSONOk(obj=CLIMATE_CONTROLLER.data,\
            headers={'cache-control': 'no-store'})

@MicroWebSrv.route('/', 'GET')
def get_index(http_client, http_response):
    http_response.WriteResponseOk(headers=None, contentType="text/html",\
        contentCharset="UTF-8", content=HTML_INDEX)

srv = MicroWebSrv()
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
