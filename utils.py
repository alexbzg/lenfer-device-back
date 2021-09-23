import gc

import micropython
import ujson
import lib.ulogging as ulogging

def load_json(path):
    LOG = ulogging.getLogger("Main")
    try:
        with open(path, 'r', encoding="utf-8") as _file:
            return ujson.load(_file)
    except Exception as exc:
        LOG.exc(exc, 'JSON file loading failed: %s' % path)     
        return None

def save_json(data, path):
    LOG = ulogging.getLogger("Main")
    try:
        with open(path, 'w', encoding="utf-8") as _file:
            _file.write(ujson.dumps(data))
    except Exception as exc:
        LOG.exc(exc, 'JSON file save failed: %s' % path)     

def manage_memory():
    gc.collect()
    gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())
#    micropython.mem_info()
#    print('-----------------------------')
#    print('Free: {} allocated: {}'.format(gc.mem_free(), gc.mem_alloc()))


