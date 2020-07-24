import network
import ujson

CONF = {}
with open('conf.json', 'r') as conf_file:
    CONF = ujson.load(conf_file)
    print('config loaded')

if CONF['network']['mode'] == 'AP':
    NETWORK_MODE = network.AP_IF
    AP = network.WLAN(network.AP_IF)
    AP.config(essid=CONF['network']['essid'], password=CONF['network']['password'],\
        authmode=CONF['network']['authmode'])
    AP.ifconfig((CONF['network']['address'], CONF['network']['mask'],\
        CONF['network']['address'], CONF['network']['address']))
    AP.active(True)
else:
    nic = network.WLAN(network.STA_IF)
    nic.active(True)
    nic.connect(CONF['network']['essid'], CONF['network']['password'])
