from machine import Pin, I2C
import ujson
import ulogging

#from ds3231_port import DS3231

def load_conf(use_default=False):
    conf_path = 'conf_default.json' if use_default else 'conf.json'
    return load_json(conf_path)

def save_conf(conf):
    save_json(conf, 'conf.json')

def load_json(path):
    try:
        with open(path, 'r', encoding="utf-8") as _file:
            return ujson.load(_file)
    except Exception as exc:
        ulogging.exc(exc, 'JSON file loading failed: %s' % path)     
        return None

def save_json(data, path):
    try:
        with open(path, 'w', encoding="utf-8") as _file:
            _file.write(ujson.dumps(data))
    except Exception as exc:
        ulogging.exc(exc, 'JSON file save failed: %s' % path)     



