from time import sleep

import network

import ulogging

from utils import load_json, save_json

class WlanController:

    def __init__(self):
        LOG = ulogging.getLogger("Main")
        self.conf = load_json('wlan.json')
        if not self.conf:
            LOG.warning('Default WLAN conf was loaded')
            self.conf = load_json('wlan_default.json')

        self.mode = None
        self.nic = network.WLAN(network.STA_IF)
        self.nic.active(True)
        self.host = '0.0.0.0'
        if self.conf['enable_ssid'] and self.conf['ssid']:
            try:
                self.nic.connect(self.conf['ssid'], self.conf['key'])
                sleep(10)
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
            self.nic.config(essid=self.conf['name'], password=self.conf['ap_key'], authmode=authmode)
            self.nic.ifconfig((self.conf['address'], self.conf['mask'], self.conf['address'], self.conf['address']))
            self.host = self.conf['address']
            self.mode = network.AP_IF

    def save_conf(self):
        save_json(self.conf, 'wlan.json')

    def online(self):
        return self.mode == network.STA_IF and self.nic and self.nic.isconnected()
