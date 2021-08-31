import ulogging
import ujson

from SIM800L import Modem

LOG = ulogging.getLogger("Main")

class GsmModem:

    def __init__(self, conf):

        self._modem = Modem()
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
    
    def request(self, url, method='GET', data=None):
        if self.connect():
            return self._modem.http_request(url, method, ujson.dumps(data))

    def get(self, url):
        return self.request(url)

    def post(self, url, data=None):
        return self.request(url, 'POST', data)
