import ulogging
import ujson

from SIM800L import Modem

LOG = ulogging.getLogger("Main")

class GsmModem:

    def __init__(self, conf):

        self._modem = Modem(**conf['pins'])
        self._apn = conf['apn']
        self.connected = False

    def connect(self):

        retries = 0
        while not self.connected and retries < 3:
            try:
                # Initialize the modem
                self._modem.initialize()

                # Connect the modem
                self._modem.connect(**self['apn'])
                self.connected = True
            except Exception as exc:
                LOG.exc(exc, 'GSM connection error')
                retries += 1
        return self.connected
    
    def request(self, url, method='GET', data=None):
        
        if self.connected or self.connect():

            return self._modem.http_request(url, method, ujson.dumps(data))

    def get(self, url):
        return self.request(url)

    def post(self, url, data=None):
        return self.request(url, 'POST', data)
