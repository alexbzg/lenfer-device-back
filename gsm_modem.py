import ulogging
import ujson

from SIM800L import Modem

LOG = ulogging.getLogger("Main")

class GsmModem:

    def __init__(self, conf):

        self._modem = Modem(**conf['pins'])
        self._apn = conf['apn']
        self._modem.initialize()
        self.connect()

    def connect(self):
        try:
            self._modem.connect(**self._apn)
            return True
        except Exception as exc:
            LOG.exc(exc, 'GSM connect error')
        return False
    
    def request(self, url, method='GET', data=None, binary_output=False):
        if self.connect():
            json_data = ujson.dumps(data) if data else None
            return self._modem.http_request(url, method, data=json_data, binary_output=binary_output)


    def get(self, url, binary_output=False):
        return self.request(url, binary_output=binary_output)

    def post(self, url, data=None):
        return self.request(url, 'POST', data)
