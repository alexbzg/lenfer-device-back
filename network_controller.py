import utime
import sys
import network
import machine

import lib.ulogging as ulogging
LOG = ulogging.getLogger("Network")

from utils import load_json, save_json

class WlanController:

    def __init__(self):        
        self.conf = load_json('wlan.json')
        if not self.conf:
            LOG.warning('Default WLAN conf was loaded')
            self.conf = load_json('wlan_default.json')

        self.mode = None
        self.nic = None
        self.host = '0.0.0.0'

        self.connect()

    def connect(self):
        if self.nic:
            self.nic.active(False)
        if self.conf['enable_ssid'] and self.conf['ssid']:
            try:
                self.nic = network.WLAN(network.STA_IF)
                self.nic.active(True)
                self.nic.connect(self.conf['ssid'], self.conf['key'])
                utime.sleep(10)
                self.host = self.nic.ifconfig()[0]
            except Exception as exc:
                LOG.exc(exc, 'WLAN connect error')

        if self.nic and self.nic.isconnected():
            self.mode = network.STA_IF
        else:
            if self.nic:
                self.nic.active(False)
            self.nic = network.WLAN(network.AP_IF)
            self.nic.active(True)
            authmode = 4 if self.conf['ap_key'] else 0
            self.nic.config(essid=self.conf['name'], password=self.conf['ap_key'],
                authmode=authmode)
            self.nic.ifconfig((self.conf['address'], self.conf['mask'], self.conf['address'], 
                self.conf['address']))
            self.host = self.conf['address']
            self.mode = network.AP_IF

    def save_conf(self):
        save_json(self.conf, 'wlan.json')

    def load_def_conf(self):
        self.conf = load_json('wlan_default.json')
        self.save_conf()

    def online(self):
        return self.mode == network.STA_IF and self.nic and self.nic.isconnected()

    def enable_ssid(self, val):
        self.conf['enable_ssid'] = val
        self.save_conf()
        machine.reset()

class NetworkController():

    def gsm_pwr_key_cycle(self):
        if self._gsm_pwr_key:
            self._gsm_pwr_key.value(1)
            utime.sleep_ms(200)
            self._gsm_pwr_key.value(0)
            utime.sleep(1)
            self._gsm_pwr_key.value(1)

    def gsm_start(self):
        import gsm
        gsm.debug(True)  # Uncomment this to see more logs, investigate issues, etc.

        gsm.start(tx=self._conf['gsm_modem']['tx'], rx=self._conf['gsm_modem']['rx'],\
            apn=self._gsm_settings['apn'] if 'apn' in self._gsm_settings else None,
            user=self._gsm_settings['user'] if 'user' in self._gsm_settings else None, 
            password=self._gsm_settings['password'] if 'password' in self._gsm_settings else None)

        sys.stdout.write('Waiting for AT command response...')
        for retry in range(20):
            if gsm.atcmd('AT'):
                return True
            else:
                sys.stdout.write('.')
                utime.sleep(5)
        else:
            sys.stdout.write("Modem not responding!")
            return False

    def gsm_connect(self):
        import gsm
        gsm.connect()
        print("-----")
        while gsm.status()[0] != 1:
            pass
        print('IP:', gsm.ifconfig()[0])

    def __init__(self):
        self._conf = load_json('conf.json')
        self._wlan = None
        self._gsm_settings = {}
        if 'gsm_modem' in self._conf and self._conf['gsm_modem']:
            self._gsm_settings = load_json('gsm_modem.json')
            if not self._gsm_settings:
                self._gsm_settings = {}
            self._gsm_pwr = machine.Pin(self._conf['gsm_modem']['pwr'], machine.Pin.OUT)\
                if 'pwr' in self._conf['gsm_modem'] and self._conf['gsm_modem']['pwr'] else None
            if self._gsm_pwr:
                self._gsm_pwr.value(1)

            self._gsm_rst = machine.Pin(self._conf['gsm_modem']['rst'], machine.Pin.OUT)\
                if 'rst' in self._conf['gsm_modem'] and self._conf['gsm_modem']['rst'] else None
            if self._gsm_rst:
                self._gsm_rst.value(1)

            self._gsm_pwr_key = machine.Pin(self._conf['gsm_modem']['pwr_key'], machine.Pin.OUT)\
                if 'pwr_key' in self._conf['gsm_modem'] and self._conf['gsm_modem']['pwr_key'] else None
            self.gsm_pwr_key_cycle()

            if not self.gsm_start():
                machine.reset
            utime.sleep(2)
            self.gsm_connect()

    def online(self):
        if 'gsm_modem' in self._conf and self._conf['gsm_modem']:
            import gsm
            return gsm.status()[0] == 1
        if self._wlan:
            return self._wlan.online()
        return False





            
