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
        if self.gsm and self._gsm_pwr_key:
            self._gsm_pwr_key.value(1)
            utime.sleep_ms(200)
            self._gsm_pwr_key.value(0)
            utime.sleep(1)
            self._gsm_pwr_key.value(1)
    
    def off(self):
        if self.gsm:
            if self._gsm_pwr_key:
                self._gsm_pwr_key.value(0)
            if self._gsm_rst:
                self._gsm_rst.value(0)

    def gsm_start(self, apn_settings):
        import gsm
        gsm.debug(True)  # see more logs, investigate issues, etc.

        gsm.start(tx=self._conf['gsm_modem']['tx'], rx=self._conf['gsm_modem']['rx'], **apn_settings)

        sys.stdout.write('Waiting for AT command response...')
        for retry in range(20):
            machine.resetWDT()
            if gsm.atcmd('AT'):
                return True
            else:
                sys.stdout.write('.')
                utime.sleep(5)
        else:
            sys.stdout.write("Modem not responding!")
            machine.reset()

    def gsm_connect(self):
        import gsm
        gsm.connect()
        while gsm.status()[0] != 1:
            pass
        LOG.info('IP: %s' % gsm.ifconfig()[0])

    def __init__(self):
        self._conf = load_json('conf.json')
        self._wlan = None
        self.gsm = False
        self._gsm_settings = {}
        if 'gsm_modem' in self._conf and self._conf['gsm_modem']:
            import gsm
            #'\r\n+COPS: 0,0,"MTS"\r\n\r\nOK\r\n'
            self.gsm = True
            self._gsm_settings = load_json('gsm_settings.json') or {}
            gsm_apns = load_json('gsm_apns.json')
            apn_settings = {}

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

            if 'network' not in self._gsm_settings or not self._gsm_settings['network']:
                self.gsm_start({'apn': ''})
                machine.resetWDT()

                network_cmd = gsm.atcmd('AT+COPS?', timeout=1000, response='OK')
                network_name = [key for key in gsm_apns.keys() if key in network_cmd]
                if network_name:
                    self._gsm_settings['network'] = network_name[0]
                    save_json(self._gsm_settings, 'gsm_settings.json')
                    gsm.stop()
                else:
                    LOG.info('Network apn data not found. Trying empty apn.')

            if 'network' in self._gsm_settings and self._gsm_settings['network']:
                apn_settings = gsm_apns[self._gsm_settings['network']]          

            if apn_settings:
                self.gsm_start(apn_settings)

            machine.resetWDT()
            self.gsm_connect()
            machine.resetWDT()

    def online(self):
        if self.gsm:
            import gsm
            return gsm.status()[0] == 1
        if self._wlan:
            return self._wlan.online()
        return False





            
