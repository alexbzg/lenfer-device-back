import ujson
import ulogging
import urequests
import utime
import uasyncio
import machine

from utils import load_json

LOG = ulogging.getLogger("Main")

def response_success(rsp):
    return rsp and rsp.status_code == 200

class HttpClient:

    def __init__(self):
        self._conf = load_json('conf.json')
        self._modem = None
        if 'gsm_modem' in self._conf and self._conf['gsm_modem']:
            try:
                from SIM800L import Modem
                self._modem = Modem(**self._conf['gsm_modem']['pins'])
                self._modem.initialize()
                self._modem.connect(**self._conf['gsm_modem']['apn'])
            except Exception as exc:
                LOG.exc(exc, 'GSM modem initialization error')
        self._srv_last_contact = utime.time()
        self._srv_req_pending = False

    def log_exception(self, exc, url, data=None, status_code=None):
        msg = 'Error loading server data: %s' % url
        if exc:
            LOG.exc(exc, msg)
        else:
            LOG.error(msg)
            LOG.error('response status: %s' % status_code)
        if data:
            LOG.error('Postdata: %s' % data)
        if (exc and isinstance(exc, OSError) or (status_code and status_code > 599)):
            if utime.time() - self._srv_last_contact > 1800:
                LOG.error("server unreachable for 30 minutes: reboot")
                machine.reset()

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
                self.log_exception(exc, url)
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
            self.log_exception(exc, url)
        finally:
            if rsp and not self._modem:
                rsp.close()
        return None

    async def post(self, url, data):
        while self._srv_req_pending:
            await uasyncio.sleep_ms(50)
        rsp = None
        rsp = None
        try:
            if (self._modem):
                data = ujson.dumps(data) if data else None
                rsp = self._modem.http_request(url, 'POST', data)
            else:
                rsp = urequests.post(url, json=data, parse_headers=False)
            if rsp.status_code != 200:
                self.log_exception(None, url, data, rsp.status_code)
                if not self._modem:
                    rsp.close()
                rsp = None
            self._srv_last_contact = utime.time()
        except Exception as exc:
            self.log_exception(exc, url, data)
        finally:
            self._srv_req_pending = False
        if rsp:
            try:
                result = ujson.loads(rsp.content) if self._modem else ujson.load(rsp.raw)
            except Exception as exc:
                LOG.exc(exc, 'Server response reading error')
                print(rsp.content if self._modem else rsp.raw.read())
            finally:
                if not self._modem:
                    rsp.close()
                rsp = None
        return result

            
            
