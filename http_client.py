import ujson
import ulogging
import urequests

from utils import load_json
from gsm_modem import GsmModem

LOG = ulogging.getLogger("Main")

def response_success(rsp):
    return rsp and rsp.status_code == 200

def log_exception(exc, url, data=None):
    LOG.exc(exc, 'Error loading server data: %s' % url)
    if data:
        LOG.error('Postdata: %s' % data)

class HttpClient:

    def __init__(self):
        self._conf = load_json('conf.json')
        self._modem = None
        if 'gsm_modem' in self._conf and self._conf['gsm_modem']:
            self._modem = GsmModem(self._conf['gsm_modem'])

    def get_to_file(self, url, local_path):

        with open(local_path, 'wb') as local_file:
            try:
                if self._modem:
                    rsp = self._modem.get(url, binary_output=True)
                    if response_success(rsp):
                        local_file.write(rsp.content)
                    return True
                else:
                    rsp = urequests.get(url)
                    if response_success(rsp):
                        buf = rsp.raw.read(1024)
                        while buf:
                            local_file.write(buf)
                            buf = rsp.raw.read(1024)
                        return True
            except Exception as exc:
                log_exception(exc, url)
            finally:
                if rsp and not self._modem:
                    rsp.close()
            
    def get_json(self, url):
        try:
            if self._modem:
                rsp = self._modem.get(url)
                if response_success(rsp):
                    return ujson.loads(rsp.content)           
            else:
                rsp = urequests.get(url)
                if response_success(url):
                    return ujson.load(rsp.raw)
        except Exception as exc:
            log_exception(exc, url)
        finally:
            if rsp and not self._modem:
                rsp.close()
        return None
            
            
