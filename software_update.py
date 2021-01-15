import ujson
import machine

import ulogging
import urequests

from utils import load_json, save_json


LOG = ulogging.getLogger("Main")

UPDATES_SERVER_URL = 'http://my.lenfer.ru/device/'

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

def load_srv_json(file):
    try:
        return ujson.load(urequests.get(UPDATES_SERVER_URL + file + '.json').raw)
    except Exception as exc:
        LOG.exc(exc, 'Error loading server data: %s' % file)
        return None

def schedule_software_update():
    version_data = load_version()
    version_data['update'] = True
    save_version(version_data)
    machine.reset()

def perform_software_update():
    wdt = machine.WDT(timeout=20000)
    version_data = load_version()
    device_type = get_device_type()
    srv_index = load_srv_json('index')
    wdt.feed()
    srv_versions = load_srv_json('devices')
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
                file_url = UPDATES_SERVER_URL + 'software/' + path
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
            parent = '/'.join(split_path[:-i])
            try:
                os.mkdir(parent)
            except OSError:
                pass

  