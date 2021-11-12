import ujson
import logging
import urequests
import utime
import lib.uasyncio as uasyncio
import machine

from utils import load_json

LOG = logging.getLogger("Main")

def response_success(rsp):
    return rsp and rsp.status_code == 200

class HttpClient:

    def __init__(self):
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
            LOG.error('server is unreachable')
            if utime.time() - self._srv_last_contact > 300:
                LOG.error("server unreachable for 5 minutes: reboot")
                machine.reset()

    def get_to_file(self, url, local_path):

        with open(local_path, 'wb') as local_file:
            new_line = False
            try:
                rsp = urequests.get(url)
                if response_success(rsp):
                    rsp.raw.settimeout(60)
                    buf = rsp.raw.read(1024)
                    while buf:
                        local_file.write(buf)
                        print('.', end="")
                        new_line = True
                        buf = rsp.raw.read(1024)
                    return True
            except Exception as exc:
                self.log_exception(exc, url)
            finally:
                if new_line:
                    print("")
                if rsp:
                    rsp.close()           

    def get_json(self, url):
        rsp = None
        try:
            rsp = urequests.get(url)
            if response_success(rsp):
                return ujson.load(rsp.raw)
        except Exception as exc:
            self.log_exception(exc, url)
        finally:
            if rsp:
                rsp.close()
        return None

    async def post(self, url, data):
        while self._srv_req_pending:
            await uasyncio.sleep_ms(50)
        machine.resetWDT()
        rsp = None
        result = None
        try:
            LOG.info("url: %s\ndata: %s" % (url, data))
            rsp = urequests.post(url, json=data)
            machine.resetWDT()
            if rsp.status_code != 200:
                self.log_exception(None, url, data, rsp.status_code)
                rsp.close()
                rsp = None
            self._srv_last_contact = utime.time()
        except Exception as exc:
            self.log_exception(exc, url, data)
        finally:
            self._srv_req_pending = False
            machine.resetWDT()
        if rsp:
            try:
                result = ujson.load(rsp.raw)
            except Exception as exc:
                LOG.exc(exc, 'Server response reading error')
                print(rsp.raw.read())
            finally:
                rsp.close()
                rsp = None
        LOG.info("return: %s" % result)
        return result            
