import ujson
import machine
import uos

import ulogging
import urequests

from utils import load_json, save_json, manage_memory


LOG = ulogging.getLogger("Main")

UPDATES_SERVER_URL = 'http://my.lenfer.ru/device2/'
UPDATES_SERVER_URL_DEV = 'http://my.lenfer.ru/dev_device/'

GSM_MODEM = None
CONF = load_json('conf.json')
if not CONF:
    CONF = {}

def updates_url():
    id_data = load_json('id.json')
    if 'debug' in id_data and id_data['debug']:
        return UPDATES_SERVER_URL_DEV
    else:
        return UPDATES_SERVER_URL

def get_device_type():
    id_data = load_json('id.json')
    device_type = 'base'
    if 'type' in id_data and id_data['type']:
        device_type = id_data['type']
    return device_type

def load_version():
    version_data = load_json('version.json')
    if not version_data:
        version_data = {
            'hash': None,
            'files': {},
            'update': False
        }
    return version_data

def save_version(version_data):
    save_json(version_data, 'version.json')

def check_software_update():
    device_type = get_device_type()
    version_data = load_version()
    srv_versions = load_srv_json('devices')
    return srv_versions and device_type in srv_versions and version_data['hash'] != srv_versions[device_type]

def load_srv_json(file, srv_url=None):
    global GSM_MODEM
    if not srv_url:
        srv_url = updates_url()
    file_url = srv_url + file + '.json'
    try:
        content = ''
        if 'gsm_modem' in CONF and CONF['gsm_modem']:
            if not GSM_MODEM:
                from gsm_modem import GsmModem
                GSM_MODEM = GsmModem(CONF['gsm_modem'])
            content = GSM_MODEM.get(file_url).content
        else:
            content = urequests.get(file_url).raw
        return ujson.load(content)
    except Exception as exc:
        LOG.exc(exc, 'Error loading server data: %s' % file)
        return None
    finally:
        manage_memory()

def schedule_software_update():
    version_data = load_version()
    version_data['update'] = True
    save_version(version_data)
    machine.reset()

def perform_software_update():
    wdt = machine.WDT(timeout=20000)
    manage_memory()
    version_data = load_version()
    device_type = get_device_type()
    srv_url = updates_url()
    srv_index = load_srv_json('index', srv_url=srv_url)
    wdt.feed()
    srv_versions = load_srv_json('devices', srv_url=srv_url)
    wdt.feed()
    if srv_index:
        for path, entry in srv_index.items():
            if 'devices_types' in entry and 'base' not in entry['devices_types'] and device_type not in entry['devices_types']:
                continue
            if path in version_data['files'] and version_data['files'][path] == entry['hash']:
                continue
            local_path = entry['path'] if 'path' in entry else path
            print(local_path)
            ensure_file_path(local_path)
            with open(local_path, 'wb') as local_file:
                file_url = srv_url + 'software/' + path
                print(file_url)
                rsp = urequests.get(file_url)
                if rsp:
                    wdt.feed()
                    buf = rsp.raw.read(1024)
                    while buf:
                        wdt.feed()
                        local_file.write(buf)
                        buf = rsp.raw.read(1024)
                    if version_data['hash']:
                        version_data['hash'] = None
                    version_data['files'][path] = entry['hash']
                    save_version(version_data)
                    rsp.close()
                    print('complete')
        wdt.feed()
        version_data['hash'] = srv_versions[device_type]
        version_data['update'] = False
        save_version(version_data)
    machine.reset()
    
def ensure_file_path(path):
    split_path = path.split('/')
    if len(split_path) > 1:
        for i, fragment in enumerate(split_path):
            if i > 0:
                parent = '/'.join(split_path[:i])
                try:
                    uos.mkdir(parent)
                except OSError as exc:
                    LOG.exc(exc, 'Error creating folder: %s' % parent)
