import ujson
import machine

from utils import load_json, save_json
from http_client import http_get, http_get_to_file

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
            'files': {}
        }
    return version_data

def save_version(version_data):
    save_json(version_data, 'version.json')


def check_update():
    device_type = get_device_type()
    version_data = load_version()
    srv_versions = load_srv_json('devices')
    return srv_versions and version_data['hash'] != srv_versions[device_type]

def load_srv_json(file):
    try:
        return ujson.loads(http_get(UPDATES_SERVER_URL + file + '.json'))    
    except Exception as exc:
        ulogging.exc(exc, 'Error loading server data: %s' % file)
        return None

def schedule_update():
    version_data = load_version()
    version_data['update'] = True
    save_version(version_data)
    machine.reset()

def perform_update():
    version_data = load_version()
    device_type = get_device_type()
    srv_index = load_srv_json('index')
    srv_versions = load_srv_json('devices')
    if srv_index:
        for path, entry in srv_index.items():
            if 'devices_types' in entry and 'base' not in entry['devices_types'] and device_type not in entry['devices_types']:
                continue
            if path in version_data['files'] and version_data['files'][path] == entry['hash']:
                continue
            local_path = entry['path'] if 'path' in entry else path
            http_get_to_file(UPDATES_SERVER_URL + path, local_path)
            if version_data['hash']:
                version_data['hash'] = None
            version_data['files'][path] = entry['hash']
            save_version(version_data)
        version_data['hash'] = srv_versions[device_type]
        version_data['update'] = False
        save_version(version_data)
    machine.reset()
    

  